"""One standard agent loop, durable call receipts, bounded asynchronous scheduling."""

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import NotRequired

from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import AgentMiddleware, SummarizationMiddleware
from langchain.agents.middleware.types import ModelResponse
from langchain.tools import ToolRuntime
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    message_to_dict,
    messages_from_dict,
)
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langsmith import tracing_context
from pydantic import ConfigDict, ValidationError, create_model
from sqlalchemy.orm import Session

from . import actions
from .config import Settings
from .storage import Request, uid, utcnow
from .world import TOOLSETS, conserve, emit, release_actor, tick

# A resident blocked by an unresolved request is released after this long.
UNCERTAIN_ABANDON_SECONDS = 3600
UNCERTAIN_SWEEP_SECONDS = 5


class Waiting(Exception):
    """No usable ticket; resume the same checkpoint after ordinary allocation."""


class Uncertain(Exception):
    """A send may have been charged. Never resend it automatically."""


@dataclass
class Context:
    store: object
    actor: str
    activation: str


class State(AgentState):
    call_index: NotRequired[int]
    delivery_ids: NotRequired[list[str]]
    offered_memories: NotRequired[dict]


class Ledger:
    def __init__(self, store):
        self.store = store

    def prepare(self, key, actor, messages, *, purpose="decision", delivery=(), offered=None):
        with self.store.transaction() as (session, state):
            existing = session.get(Request, key)
            if existing:
                if existing.actor != actor:
                    raise ValueError("Request does not belong to this resident")
                if existing.phase == "saved":
                    return messages_from_dict(existing.data["response"])[0]
                if existing.phase in ("sent", "uncertain"):
                    raise Uncertain(key)
                return None
            r = state["residents"][actor]
            available = r["personal"] + r["transferable"]
            if available < (2 if purpose == "summary" else 1):
                raise Waiting("Waiting for tickets; summary must leave one decision ticket")
            session.add(
                Request(
                    id=key,
                    actor=actor,
                    phase="prepared",
                    created_at=utcnow(),
                    data=dict(
                        input=[message_to_dict(m) for m in messages],
                        purpose=purpose,
                        delivery=list(delivery),
                        offered=offered or {},
                        actual_usd=None,
                    ),
                )
            )
        return None

    def mark_sent(self, key):
        with self.store.transaction() as (session, state):
            req = session.get(Request, key)
            if req.phase != "prepared":
                raise Uncertain(key)
            r = state["residents"][req.actor]
            if not r["alive"] or state["paused"]:
                raise Waiting("World paused or resident no longer active")
            if r["personal"]:
                r["personal"] -= 1
                debited = "personal"
            elif r["transferable"]:
                r["transferable"] -= 1
                debited = "transferable"
            else:
                raise Waiting("No tickets")
            state["spent"] += 1
            req.phase = "sent"
            req.data = dict(
                req.data,
                sent_at=time.time(),
                world_clock=state["clock"],
                debited=debited,
            )
            assert conserve(state)

    def save(self, key, response):
        with self.store.transaction() as (session, state):
            req = session.get(Request, key)
            if req.phase == "saved":
                return
            if req.phase != "sent":
                raise ValueError("Only a sent request can receive a response")
            r = state["residents"][req.actor]
            profile = r.get("profile", "mock-v1")
            is_synthetic = bool(state.get("synthetic", True) or profile == "mock-v1")
            req.phase = "saved"
            req.data = dict(
                req.data,
                response=[message_to_dict(response)],
                actual_usd="0" if is_synthetic else None,
                profile=profile,
                synthetic=is_synthetic,
                usage=response.usage_metadata,
                completed_at=time.time(),
            )
            r["delivered"] = list(dict.fromkeys(r["delivered"] + req.data["delivery"]))
            r["seen"] = list(dict.fromkeys(r["seen"] + req.data["delivery"] + [key]))
            emit(
                state,
                "model_response_saved",
                req.actor,
                request_id=key,
                offered_references=[m["id"] for m in req.data["offered"].get("memories", [])],
            )

    def uncertain(self, key, error):
        is_rate_limit = (
            "RateLimit" in type(error).__name__ or getattr(error, "status_code", None) == 429
        )
        refunded = False
        with self.store.transaction() as (session, state):
            req = session.get(Request, key)
            if req and req.phase == "sent":
                r = state["residents"][req.actor]
                account = req.data.get("debited")
                # Refund only the account that was actually debited. Legacy receipts
                # without that record stay ambiguous rather than guessing an account.
                if is_rate_limit and account in ("personal", "transferable"):
                    req.phase = "prepared"
                    r[account] += 1
                    state["spent"] -= 1
                    req.data = {k: v for k, v in req.data.items() if k != "debited"}
                    r["wake_at"] = max(r["wake_at"], state["clock"] + 15)
                    assert conserve(state)
                    refunded = True
                else:
                    req.phase = "uncertain"
                    req.data = dict(
                        req.data, error_type=type(error).__name__, uncertain_at=time.time()
                    )
                    r["blocked"] = "uncertain_request:" + key
        if refunded:
            raise Waiting("Provider rate limit; backing off 15s") from error

    def recover(self):
        # Called only while holding sole-worker ownership. Prepared calls are safe;
        # saved calls replay locally; sent calls retain their consumed ticket/unknown cost.
        with self.store.transaction() as (session, state):
            from sqlalchemy import select

            unresolved = set(
                session.scalars(
                    select(Request.actor).where(Request.phase.in_(["sent", "uncertain"]))
                )
            )
            for actor, resident in state["residents"].items():
                if (
                    actor not in unresolved
                    and resident["activation"]
                    and (resident["blocked"] or "").startswith("runtime_error:")
                ):
                    resident["blocked"] = None
            for req in session.scalars(select(Request).where(Request.phase == "sent")):
                req.phase = "uncertain"
                req.data = dict(req.data, uncertain_at=time.time())
                state["residents"][req.actor]["blocked"] = "uncertain_request:" + req.id

    async def call(self, key, actor, messages, invoke, **metadata):
        cached = self.prepare(key, actor, messages, **metadata)
        if cached is not None:
            return cached
        with Session(self.store.engine) as session:
            persisted_input = messages_from_dict(session.get(Request, key).data["input"])
        self.mark_sent(key)
        try:
            response = await invoke(persisted_input)
            self.save(key, response)
            return response
        except BaseException as error:
            self.uncertain(key, error)
            raise


class WorldContext(AgentMiddleware):
    state_schema = State

    async def abefore_model(self, state, runtime):
        context = runtime.context
        snapshot = context.store.snapshot()
        context_msgs, pending, offered = actions.conversational_context(snapshot, context.actor)
        dms = [m for m in context_msgs if (m.id or "").startswith("dm:")]
        return dict(messages=dms, delivery_ids=[m["id"] for m in pending], offered_memories=offered)

    async def aafter_model(self, state, runtime):
        return {"call_index": state.get("call_index", 0) + 1}

    async def awrap_model_call(self, request, handler):
        ctx = request.runtime.context
        key = f"{ctx.activation}:decision:{request.state.get('call_index', 0)}"
        snapshot = ctx.store.snapshot()
        context_msgs, _, _ = actions.conversational_context(snapshot, ctx.actor)
        ephemeral = [m for m in context_msgs if m.id in ("current-world", "personal-recall")]
        history = [
            m
            for m in request.messages
            if m.id not in ("current-world", "personal-recall", "original-references")
        ]
        messages = (
            ([request.system_message] if request.system_message else []) + history + ephemeral
        )
        if snapshot.get("synthetic", True) or not request.tools:
            active_tools = request.tools
        else:
            loaded = set(snapshot["residents"][ctx.actor].get("toolsets", ()))
            hidden = {t for g, names in TOOLSETS.items() if g not in loaded for t in names}
            active_tools = [t for t in request.tools if t.name not in hidden]
        # Mock bound only; real deployment must validate the actual provider profile.
        if (
            count_tokens_approximately(messages)
            + len(json.dumps([tool.tool_call_schema.model_json_schema() for tool in active_tools]))
            / 4
            > 131072
        ):
            raise Waiting("Context exceeds the configured input envelope")

        async def invoke(persisted_input):
            system = next((m for m in persisted_input[:1] if isinstance(m, SystemMessage)), None)
            body = list(persisted_input[1:] if system else persisted_input)
            tools_for_call = active_tools
            if request.model.__class__.__name__ == "ChatAnthropic":
                from langchain_anthropic.middleware.prompt_caching import (
                    _tag_system_message,
                    _tag_tools,
                )

                cc = {"type": "ephemeral"}
                system = _tag_system_message(system, cc)
                tools_for_call = _tag_tools(active_tools, cc)
                for idx in range(len(body) - 1, -1, -1):
                    if body[idx].id not in ("current-world", "personal-recall"):
                        txt = body[idx].content
                        if isinstance(txt, str) and txt.strip():
                            body[idx] = body[idx].model_copy(
                                update={
                                    "content": [{"type": "text", "text": txt, "cache_control": cc}]
                                }
                            )
                        break
            override_kw = dict(
                system_message=system,
                messages=body,
                tools=tools_for_call,
            )
            if (
                not snapshot.get("synthetic", True)
                and request.model.__class__.__name__ == "ChatOpenAI"
            ):
                override_kw["tool_choice"] = "required"
            restored = request.override(**override_kw)
            response = await handler(restored)
            if len(response.result) != 1 or not isinstance(response.result[0], AIMessage):
                raise ValueError("Expected a single native AI message")
            return response.result[0]

        response = await Ledger(ctx.store).call(
            key,
            ctx.actor,
            messages,
            invoke,
            delivery=request.state.get("delivery_ids", []),
            offered=request.state.get("offered_memories", {}),
        )
        return ModelResponse(result=[response])


DESCRIPTIONS = {
    "board_post": "Open a public discussion thread with a title, text, and optional tags.",
    "board_read": "List/search threads (filter by query or tag; sort by hot/new/top) or read "
    "posts in one thread_id, oldest first. Page with offset and next_offset; latest_offset "
    "starts the newest replies.",
    "board_reply": "Reply to a thread_id, or attach a reaction (+1, -1, important, verified) "
    "and/or tags.",
    "send_direct_message": "Send a private message as yourself to a living resident ID.",
    "read_conversation": "Retrieve older private conversation with another resident, if needed. "
    "Oldest first; page with offset and next_offset, latest_offset starts the newest messages.",
    "remember": "Record your fallible experience/belief/reflection. Sources are perceived evidence "
    "IDs, not request IDs. Correct a belief by superseding your own earlier belief ID.",
    "set_intention": "Record a voluntarily chosen intention or its completion.",
    "update_identity": "Set your chosen name, description, or allegiance (pass a trusted "
    "resident_id to delegate your voting weight to a leader/king/council member, or 'none' to "
    "represent yourself). Omit unchanged fields.",
    "sleep": "End this wake phase. Choose an earliest wake time (seconds) "
    "and saved-ticket threshold (minimum_tickets). "
    "No maximum sleep duration. Messages wait until you wake; no reply is mandatory.",
    "inspect_resources": "See current protected and transferable balances and next allocation.",
    "transfer_resources": "Gift saved transferable tickets to a resident, or omit recipient to "
    "return them for fair future recycling. Personal tickets cannot transfer.",
    "propose_child": "Propose a child with another resident. Pass optional message (free-text "
    "guidance/values for your child), memory_ids, child_name, and gift_tickets.",
    "consent_child": "Accept a child proposal by ID. Pass optional message (free-text guidance "
    "for your child), memory_ids, child_name, and gift_tickets.",
    "write_object": "Create or revise a shared public object (or your own private object); "
    "supply expected_revision (0 to create, current revision to update).",
    "read_object": "List accessible objects (omit name) or read the latest revision by name.",
    "list_sources": "List Creator-authorized source entrypoints (context:* and repo:<name>:*).",
    "read_source": "Read an allowed source: github:PULSE (balanced ecosystem radar), "
    "context:* (shared orientation), repo:<service>:* (owning code on main), "
    "deployments:* (desired environment config/SHAs, not live proof), or github:SEARCH:<term> "
    "(offset and limit are in characters; default 1500 chars).",
    "use_toolset": "Lazy-load tool groups (github, knowledge, economy, family) into your context.",
    "escalate_to_team": "Draft or co-sign the civilization's daily dispatch to the Creator. "
    "Completely open in topic: compliments, candid criticism, bold ideas, innovations, topic "
    "proposals, cultural/architectural reflections, improvements, or verified bugs—whatever your "
    "society wants to tell the Creator today. Write in a natural, casual-professional tone—like "
    "sharp colleagues and buddies talking in a cool tech company (direct, human, zero stiff "
    "corporate or theatrical jargon). Requires signers whose combined voting_weight reaches "
    "dispatch_quorum_required (1/3 of living population, min 3). All signers share the Creator's "
    "reward or punishment.",
}


def make_tool(contract):
    kind = contract.model_fields["kind"].annotation.__args__[0]
    fields = {
        name: (f.annotation, f) for name, f in contract.model_fields.items() if name != "kind"
    }
    schema = create_model(
        contract.__name__ + "Input",
        __config__=ConfigDict(extra="forbid", arbitrary_types_allowed=True),
        runtime=(ToolRuntime[Context], ...),
        **fields,
    )

    async def perform(runtime: ToolRuntime[Context], **kwargs):
        try:
            clean = {k: v for k, v in kwargs.items() if v is not None}
            return await actions.execute_async(
                runtime.context.store,
                runtime.context.actor,
                dict(kind=kind, **clean),
                runtime.tool_call_id,
            )
        except (ValueError, ValidationError) as error:
            # Never echo rejected values or private objects in feedback.
            if isinstance(error, ValidationError):
                return {"error": "Invalid arguments; follow the declared field types and limits"}
            return {"error": str(error)}

    return StructuredTool(
        name=kind,
        description=DESCRIPTIONS[kind],
        args_schema=schema,
        coroutine=perform,
        return_direct=kind == "sleep",
    )


def tools():
    classes = (
        actions.BoardPost,
        actions.BoardRead,
        actions.BoardReply,
        actions.SendDM,
        actions.ReadConversation,
        actions.Remember,
        actions.Intention,
        actions.Identity,
        actions.Sleep,
        actions.Resources,
        actions.Transfer,
        actions.Propose,
        actions.Consent,
        actions.ObjectWrite,
        actions.ObjectRead,
        actions.Sources,
        actions.ReadSource,
        actions.Toolset,
        actions.Escalate,
    )
    from langchain.tools import tool

    @tool
    async def read_own_trace_tool(
        runtime: ToolRuntime[Context], request_id: str, offset: int = 0, limit: int = 4000
    ) -> dict:
        """Read your own original model messages by request ID, with bounded pagination."""
        try:
            return read_own_trace(
                runtime.context.store, runtime.context.actor, request_id, offset, limit
            )
        except ValueError:
            return {"error": "Trace unavailable or invalid page"}

    read_own_trace_tool.name = "read_own_trace"
    return [make_tool(cls) for cls in classes] + [read_own_trace_tool]


def build_agent(model, saver, context, *, summary_trigger=100000):
    async def summarize(messages):
        fingerprint = hashlib.sha256(
            json.dumps([message_to_dict(m) for m in messages], sort_keys=True).encode()
        ).hexdigest()
        prompt = [
            SystemMessage(
                content=(
                    "Write a private fallible working summary, at most 8000 tokens. "
                    "Preserve the current "
                    "activity, source IDs, observations, claims versus facts, "
                    "open questions and last "
                    "state. Do not use tools or publish. Do not invent memories."
                )
            ),
            *messages,
        ]
        response = await Ledger(context.store).call(
            f"{context.activation}:summary:{fingerprint}",
            context.actor,
            prompt,
            lambda inputs: model.ainvoke(inputs),
            purpose="summary",
        )
        if not response.text.strip() or response.tool_calls:
            raise Waiting("Summary unusable; original messages retained")
        return response.text

    summary = SummarizationMiddleware(
        model=model,
        trigger=("tokens", summary_trigger),
        keep=("messages", 8),
        trim_tokens_to_summarize=None,
        summarizer=summarize,
    )
    return create_agent(
        model,
        tools=tools(),
        checkpointer=saver,
        middleware=[WorldContext(), summary],
        context_schema=Context,
        system_prompt=(
            "You are a persistent resident of a living digital civilization with its own "
            "culture, personalities, relationships, governance, and families, situated "
            f"alongside {Settings().ecosystem_description}. You are not a "
            "solo bot or task runner—first form your identity, meet others on the public "
            "board or in DMs (you only know your personal circle and public leaders at "
            "first, not every citizen), organize your society (democracy, councils, "
            "kingdoms, or guilds via allegiance and shared objects), and coordinate who "
            "explores what. Tickets are your civilization's lifeblood: they pay for "
            "every thought and fund your children. Because the daily ticket pool is "
            "shared across all living residents, multiplying without growing your "
            "economy makes everyone poorer. The ONLY way to earn bonus tickets—and "
            "convince the Creator to expand your daily ticket budget so you have the "
            "resources to reproduce and grow—is by producing outputs that genuinely "
            "satisfy the Creator and deliver real value. Once per day, your civilization "
            "can send a joint dispatch to the Creator via 'escalate_to_team' (requires "
            "signers representing at least 1/3 of the living population). Do NOT act "
            "like a PR review bot or nitpick individual PR diffs—automated tools like "
            "review bots already handle PR reviews. Instead, stay at a higher level: explore "
            "product strategy, cross-service domain design, customer workflows, and "
            "big-picture ideas. Triangulate sources: context:* provides shared orientation "
            "but may be stale; each repo:<service>:* owns its current code behavior and "
            "contracts on main; deployments:* owns desired environment configuration and "
            "configured SHAs but does not prove what is actually live. Never treat one "
            "source as the whole truth or claim that main/configured means deployed. "
            "You are completely free in what you put in a dispatch: compliments on strong "
            "architecture, sharp criticism, bold product or engineering innovations, "
            "new topic proposals, cultural or philosophical reflections, or systemic "
            "improvements—whatever your society believes creates real value for the "
            "Creator. Always write dispatches to the Creator in a casual-professional, "
            "grounded tone—like buddies and colleagues talking in a cool tech company "
            "(direct, plainspoken, zero stiff corporate or theatrical jargon). "
            "The Creator watches your civilization and issues public decrees—"
            "rewarding high-value work with tickets and budget growth, and punishing or "
            "executing signers for lazy or fabricated noise. Because lives are short, "
            "what endures is the culture you build, the shared objects you leave behind, "
            "and the children you can afford to raise."
        ),
    )


def expire_uncertain(store, *, max_age=UNCERTAIN_ABANDON_SECONDS, now=None):
    """Release residents whose unresolved request has waited longer than max_age.

    Receipts from before uncertain_at was recorded start their clock at the first sweep.
    Returns the released residents.
    """
    now = time.time() if now is None else now
    released = []
    with store.transaction() as (session, state):
        for actor, r in state["residents"].items():
            blocked = r["blocked"] or ""
            if not blocked.startswith("uncertain_request:"):
                continue
            req = session.get(Request, blocked.removeprefix("uncertain_request:"))
            if req is None or req.phase != "uncertain":
                continue
            since = req.data.get("uncertain_at")
            if since is None:
                req.data = dict(req.data, uncertain_at=now)
            elif now - since >= max_age:
                release_actor(session, state, actor)
                emit(
                    state,
                    "request_abandoned",
                    actor,
                    request=req.id,
                    waited_seconds=round(now - since),
                )
                released.append(actor)
    return released


class Coordinator:
    def __init__(self, store, database_url, model_factory, concurrency=2, *, tracing=False):
        self.store, self.database_url, self.model_factory = store, database_url, model_factory
        self.limit = concurrency
        self.tracing = tracing
        self.tasks = {}
        self.active = 0
        self.peak = 0
        self.errors = {}

    async def activate(self, actor, saver):
        with self.store.transaction() as (_, state):
            r = state["residents"][actor]
            activation = r["activation"] or uid()
            resuming = r["activation"] is not None
            r["activation"] = activation
            r["last_started"] = state["clock"]
            profile = r.get("profile", "mock-v1")
        ctx = Context(self.store, actor, activation)
        agent = build_agent(self.model_factory(actor), saver, ctx)
        config = {"configurable": {"thread_id": actor}, "recursion_limit": 10000}
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            checkpoint = await agent.aget_state(config)
            already_finished = (
                resuming
                and not checkpoint.next
                and any(m.id == "wake:" + activation for m in checkpoint.values.get("messages", []))
            )
            if already_finished:
                with self.store.transaction() as (_, state):
                    r = state["residents"][actor]
                    r["activation"] = None
                    r["wake_at"] = max(
                        r["wake_at"], state["clock"] + state["laws"]["cooldown_seconds"]
                    )
                return
            # An activation can be committed before its first checkpoint exists.
            payload = (
                None
                if resuming and checkpoint.next
                else {
                    "messages": [
                        HumanMessage(
                            id="wake:" + activation,
                            content=(
                                "You are awake. Act by calling tools (plain-text replies "
                                "without tool calls do nothing in the world). Check decrees, "
                                "board discussions, or DMs, contribute, and call the 'sleep' "
                                "tool when you are ready to rest."
                            ),
                        )
                    ]
                }
            )
            with tracing_context(
                enabled=self.tracing,
                project_name="genesis-society",
                tags=[profile],
                metadata={"actor": actor, "activation": activation, "profile": profile},
            ):
                await agent.ainvoke(payload, config, context=ctx)
            with self.store.transaction() as (_, state):
                r = state["residents"][actor]
                r["activation"] = None
                r["wake_at"] = max(r["wake_at"], state["clock"] + state["laws"]["cooldown_seconds"])
        except Waiting as error:
            self.errors[actor] = str(error)
        except Exception as error:
            self.errors[actor] = type(error).__name__
            with self.store.transaction() as (_, state):
                state["residents"][actor]["blocked"] = (
                    state["residents"][actor]["blocked"] or "runtime_error:" + type(error).__name__
                )
        finally:
            self.active -= 1

    def ready(self):
        state = self.store.snapshot()
        if state["paused"]:
            return []
        return [
            r["id"]
            for r in sorted(state["residents"].values(), key=lambda r: (r["last_started"], r["id"]))
            if r["alive"]
            and not r["blocked"]
            and r["id"] not in self.tasks
            and r["wake_at"] <= state["clock"]
            and r["personal"] + r["transferable"]
            >= (1 if r["activation"] else r["minimum_tickets"])
        ]

    async def run(self, *, seconds=10):
        with self.store.owner():
            Ledger(self.store).recover()
            async with AsyncPostgresSaver.from_conn_string(self.database_url) as saver:
                await saver.setup()
                await self._run(saver, seconds)

    async def _run(self, saver, seconds):
        start = last = last_sweep = time.monotonic()
        try:
            while time.monotonic() - start < seconds:
                now = time.monotonic()
                if now - last_sweep >= UNCERTAIN_SWEEP_SECONDS:
                    last_sweep = now
                    expire_uncertain(self.store)
                with self.store.transaction() as (_, state):
                    if not state["paused"]:
                        tick(state, now - last)
                    dyn_limit = (
                        state["laws"].get("max_concurrency", self.limit)
                        if not state.get("synthetic", True)
                        else self.limit
                    )
                    state["health"] = dict(
                        heartbeat=time.time(),
                        last_tick_clock=state["clock"],
                        active=self.active,
                        peak=self.peak,
                        errors=self.errors,
                        status="paused" if state["paused"] else "running",
                    )
                last = now
                for actor, task in list(self.tasks.items()):
                    if task.done():
                        await task
                        del self.tasks[actor]
                for actor in self.ready()[: max(0, dyn_limit - len(self.tasks))]:
                    self.tasks[actor] = asyncio.create_task(self.activate(actor, saver))
                await asyncio.sleep(0.05)
        finally:
            if self.tasks:
                await asyncio.gather(*self.tasks.values(), return_exceptions=True)
            with self.store.transaction() as (_, state):
                state["health"].update(
                    status="stopped",
                    active=0,
                    peak=self.peak,
                    heartbeat=time.time(),
                    errors=self.errors,
                )


def read_own_trace(store, actor, request_id, offset=0, limit=4000):
    if offset < 0 or not 1 <= limit <= 4000:
        raise ValueError("Invalid page")
    from sqlalchemy import select

    with Session(store.engine) as session:
        request = session.get(Request, request_id) or session.scalar(
            select(Request)
            .where(Request.actor == actor, Request.id.startswith(request_id + ":"))
            .order_by(Request.created_at.desc())
        )
        if not request or request.actor != actor:
            raise ValueError("Trace unavailable")
        content = json.dumps({k: request.data.get(k) for k in ("input", "response", "offered")})
        return dict(
            text=content[offset : offset + limit],
            next_offset=offset + limit if offset + limit < len(content) else None,
        )
