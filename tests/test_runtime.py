import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.orm import Session

from genesis_society.mock import MockResident
from genesis_society.runtime import (
    Context,
    Coordinator,
    Ledger,
    Uncertain,
    Waiting,
    build_agent,
    expire_uncertain,
    read_own_trace,
    tools,
)
from genesis_society.storage import Request, Store
from genesis_society.world import conserve, new_resident


def unpause(store):
    with store.transaction() as (_, state):
        state["paused"] = False


async def test_native_demo_persistence_sleep_restart_and_delivery(store, actors):
    unpause(store)
    c = Coordinator(store, store.database_url, lambda _: MockResident())
    await c.run(seconds=3)
    assert not c.errors, c.errors
    state = store.snapshot()
    assert len(state["threads"]) == 2 and len(state["messages"]) == 2
    assert all(len(r["memories"]) == 1 for r in state["residents"].values())
    assert state["spent"] == 10
    original_requests = [r["id"] for r in store.requests()]
    # Simulate eligible world time, then use a completely new store/coordinator.
    with store.transaction() as (_, state):
        state["clock"] += 61
    fresh = Store(str(store.engine.url.render_as_string(hide_password=False)))
    c2 = Coordinator(fresh, store.database_url, lambda _: MockResident())
    await c2.run(seconds=2)
    assert not c2.errors, c2.errors
    state = fresh.snapshot()
    assert len(state["messages"]) == 2
    assert all(len(r["memories"]) == 2 for r in state["residents"].values())
    assert all(
        len(r["delivered"]) == len(set(r["delivered"])) == 1 for r in state["residents"].values()
    )
    assert set(original_requests).issubset({r["id"] for r in fresh.requests()})
    assert conserve(state)
    fresh.engine.dispose()


async def test_five_residents_two_slots_and_tick_progress(store, actors):
    unpause(store)
    with store.transaction() as (_, state):
        for _ in range(3):
            new_resident(state, age_days=30, lifespan_days=120)
        # Reallocate existing synthetic holdings without minting.
        for r in state["residents"].values():
            r["personal"], r["transferable"] = 1, 63
    ids = list(store.snapshot()["residents"])
    a, b, c, d, e = ids
    started, ended, release_a, release_b = [], [], asyncio.Event(), asyncio.Event()

    with store.transaction() as (_, state):
        for index, actor in enumerate(ids):
            state["residents"][actor]["last_started"] = index - 100
    active, peak = 0, 0

    class Measured(MockResident):
        actor: str

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            from langchain_core.outputs import ChatGeneration, ChatResult

            from genesis_society.storage import uid

            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            started.append(self.actor)
            try:
                if self.actor == a:
                    await release_a.wait()
                elif self.actor == b:
                    await release_b.wait()
                else:
                    await asyncio.sleep(0.05)
                ended.append(self.actor)
                return ChatResult(
                    generations=[
                        ChatGeneration(
                            message=AIMessage(
                                content="Synthetic voluntary sleep",
                                tool_calls=[
                                    dict(
                                        name="sleep",
                                        args={"seconds": 3600},
                                        id=uid(),
                                        type="tool_call",
                                    )
                                ],
                            )
                        )
                    ]
                )
            finally:
                active -= 1

    runner = Coordinator(store, store.database_url, lambda actor: Measured(actor=actor))
    task = asyncio.create_task(runner.run(seconds=5))
    async with asyncio.timeout(15):
        while len(started) < 2:
            await asyncio.sleep(0.02)
        assert set(started) == {a, b}
        assert store.snapshot()["spent"] == 2  # C/D/E wait for free.
        first_clock = store.snapshot()["clock"]
        release_b.set()
        while c not in started:
            await asyncio.sleep(0.02)
        assert a not in ended and b in ended
        assert store.snapshot()["clock"] > first_clock
        from genesis_society.connectors import receive_mock_council

        receive_mock_council(
            store, event_id="during-a", author="Creator", text="hello", mentions=["Historian"]
        )
        assert store.snapshot()["council_jobs"]
        release_a.set()
        await task
    assert not runner.errors, runner.errors
    assert peak == runner.peak == 2 and set(started) == {a, b, c, d, e}
    assert store.snapshot()["spent"] == 5
    assert conserve(store.snapshot())


async def test_crash_boundaries_replay_and_recipient_redemption(store, actors):
    a, b = actors
    unpause(store)
    ledger = Ledger(store)
    calls = 0

    async def provider(inputs):
        nonlocal calls
        calls += 1
        return AIMessage(content="saved original response")

    ledger.prepare("prepared", a, [HumanMessage(content="original")])
    ledger.recover()
    assert store.snapshot()["spent"] == 0
    result = await ledger.call("prepared", a, [], provider)
    replay = await ledger.call("prepared", a, [], provider)
    assert result == replay and calls == 1 and store.snapshot()["spent"] == 1
    ledger.prepare("ambiguous", a, [])
    ledger.mark_sent("ambiguous")
    Ledger(store).recover()
    with pytest.raises(Uncertain):
        await ledger.call("ambiguous", a, [], provider)
    assert calls == 1
    # The other resident still spends a ticket normally.
    await ledger.call("independent", b, [], provider)
    assert calls == 2 and conserve(store.snapshot())
    assert read_own_trace(store, a, "prepared")["text"]
    with pytest.raises(ValueError, match="unavailable"):
        read_own_trace(store, b, "prepared")
    with Session(store.engine) as session:
        assert session.get(Request, "ambiguous").data["actual_usd"] is None


async def test_failure_isolates_one_resident(store, actors):
    unpause(store)
    broken = actors[0]

    class Broken(MockResident):
        async def _agenerate(self, *args, **kwargs):
            raise TimeoutError("synthetic transport failure")

    c = Coordinator(
        store, store.database_url, lambda actor: Broken() if actor == broken else MockResident()
    )
    await c.run(seconds=2)
    state = store.snapshot()
    assert not state["paused"]
    assert state["residents"][broken]["blocked"]
    assert not state["residents"][actors[1]]["blocked"]
    assert len(state["threads"]) == 1
    assert len([r for r in store.requests() if r["actor"] == broken]) == 1
    assert conserve(state)


async def test_summary_preserves_pairs_originals_and_uses_one_ticket(store, actors):
    from langchain_core.messages import ToolMessage

    unpause(store)
    ctx = Context(store, actors[0], "summary-test")
    async with AsyncPostgresSaver.from_conn_string(store.database_url) as saver:
        await saver.setup()
        # Exercise the actual configured framework middleware, not a custom compressor.
        from langchain.agents.middleware import SummarizationMiddleware

        invoked = []

        async def summarize(messages):
            invoked.append(messages)
            return "A fallible summary; source: example-1"

        middleware = SummarizationMiddleware(
            model=MockResident(),
            trigger=("messages", 8),
            keep=("messages", 4),
            summarizer=summarize,
            trim_tokens_to_summarize=None,
        )
        messages = [HumanMessage(content="start", id="start")]
        for i in range(6):
            messages.extend(
                [
                    AIMessage(
                        content="",
                        id=f"ai{i}",
                        tool_calls=[
                            dict(name="board_read", args={}, id=f"call{i}", type="tool_call")
                        ],
                    ),
                    ToolMessage(
                        content="original evidence", tool_call_id=f"call{i}", id=f"tool{i}"
                    ),
                ]
            )
        result = await middleware.abefore_model({"messages": messages}, None)
        assert result and invoked
        preserved = result["messages"]
        call_ids = {
            call["id"] for m in preserved if isinstance(m, AIMessage) for call in m.tool_calls
        }
        assert all(m.tool_call_id in call_ids for m in preserved if isinstance(m, ToolMessage))
        agent = build_agent(MockResident(), saver, ctx)
        assert agent is not None
    ledger = Ledger(store)
    await ledger.call(
        "summary",
        actors[0],
        messages,
        lambda inputs: asyncio.sleep(0, result=AIMessage(content="source-linked summary")),
        purpose="summary",
    )
    assert store.snapshot()["spent"] == 1
    assert len(next(r for r in store.requests() if r["id"] == "summary")["input"]) == len(messages)


def test_summary_last_ticket_wait_and_tool_schema_identity(store, actors):
    a = actors[0]
    with store.transaction() as (_, state):
        r = state["residents"][a]
        state["pool"] += r["personal"] + r["transferable"] - 1
        r["personal"], r["transferable"] = 1, 0
    with pytest.raises(Waiting):
        Ledger(store).prepare("summary", a, [], purpose="summary")
    assert store.snapshot()["spent"] == 0
    for tool in tools():
        schema = json.dumps(tool.tool_call_schema.model_json_schema())
        assert "runtime" not in schema and "actor_id" not in schema


def test_owner_exclusion(store):
    with store.owner():
        with pytest.raises(RuntimeError, match="Another"):
            with store.owner():
                pytest.fail("Second owner admitted")


async def test_saved_response_crash_replays_without_duplicate_send(store, actors, monkeypatch):
    unpause(store)
    original_save = Ledger.save
    crashed = False

    def crash_after_save(self, key, response):
        nonlocal crashed
        original_save(self, key, response)
        if not crashed:
            crashed = True
            raise RuntimeError("synthetic crash after durable response before graph checkpoint")

    monkeypatch.setattr(Ledger, "save", crash_after_save)
    runner = Coordinator(store, store.database_url, lambda _: MockResident())
    await runner.run(seconds=1.5)
    before = store.requests()
    assert crashed and runner.errors
    monkeypatch.setattr(Ledger, "save", original_save)
    restarted = Coordinator(store, store.database_url, lambda _: MockResident())
    await restarted.run(seconds=2)
    assert not restarted.errors, restarted.errors
    assert len(store.snapshot()["threads"]) == 2
    assert len(store.requests()) == 10
    assert all(r["phase"] == "saved" for r in store.requests())
    assert store.snapshot()["spent"] == 10
    assert set(r["id"] for r in before) <= set(r["id"] for r in store.requests())


async def test_effect_crash_replays_without_duplicate_world_mutation(store, monkeypatch):
    from genesis_society import actions

    unpause(store)
    original_execute = actions.execute
    crashed = False

    def crash_after_effect(*args, **kwargs):
        nonlocal crashed
        result = original_execute(*args, **kwargs)
        if not crashed:
            crashed = True
            raise RuntimeError("synthetic crash after committed world effect")
        return result

    monkeypatch.setattr(actions, "execute", crash_after_effect)
    runner = Coordinator(store, store.database_url, lambda _: MockResident())
    await runner.run(seconds=1.5)
    assert crashed
    monkeypatch.setattr(actions, "execute", original_execute)
    restarted = Coordinator(store, store.database_url, lambda _: MockResident())
    await restarted.run(seconds=2)
    assert not restarted.errors, restarted.errors
    assert len(store.snapshot()["threads"]) == 2
    assert len(store.snapshot()["messages"]) == 2
    assert store.snapshot()["spent"] == 10


async def test_summary_failure_not_retried_and_original_input_retained(store, actors):
    unpause(store)
    count = 0

    async def failed(inputs):
        nonlocal count
        count += 1
        raise TimeoutError("synthetic")

    ledger = Ledger(store)
    with pytest.raises(TimeoutError):
        await ledger.call(
            "failed-summary",
            actors[0],
            [HumanMessage(content="original")],
            failed,
            purpose="summary",
        )
    with pytest.raises(Uncertain):
        await ledger.call("failed-summary", actors[0], [], failed, purpose="summary")
    assert count == 1 and store.snapshot()["spent"] == 1
    assert "original" in read_own_trace(store, actors[0], "failed-summary")["text"]
    assert store.snapshot()["residents"][actors[1]]["blocked"] is None


async def test_prepared_input_survives_restart_unchanged(store, actors):
    unpause(store)
    ledger = Ledger(store)
    ledger.prepare("prepared-original", actors[0], [HumanMessage(content="original context")])
    actual = []

    async def model(inputs):
        actual.extend(inputs)
        return AIMessage(content="response")

    await ledger.call(
        "prepared-original", actors[0], [HumanMessage(content="changed world")], model
    )
    assert actual[0].content == "original context"
    assert store.snapshot()["spent"] == 1
    with pytest.raises(ValueError):
        await ledger.call("prepared-original", actors[1], [], model)


async def test_finished_graph_crash_does_not_start_extra_call(store, actors):
    unpause(store)
    coordinator = Coordinator(store, store.database_url, lambda _: MockResident())
    await coordinator.run(seconds=2)
    assert not coordinator.errors
    requests = store.requests()
    actor = actors[0]
    activation = next(r["id"].split(":")[0] for r in requests if r["actor"] == actor)
    with store.transaction() as (_, state):
        # Crash after final graph checkpoint, before activation cleanup.
        state["residents"][actor]["activation"] = activation
        state["residents"][actor]["wake_at"] = state["clock"]
    restarted = Coordinator(store, store.database_url, lambda _: MockResident())
    await restarted.run(seconds=0.4)
    assert not restarted.errors
    # Recovery itself must not infer. The other resident remains voluntarily asleep.
    assert len(store.requests()) == len(requests)


async def test_context_limit_blocks_before_spending(store, actors):
    from types import SimpleNamespace

    from langchain.agents.middleware.types import ModelRequest

    from genesis_society.runtime import WorldContext

    invoked = False

    async def handler(request):
        nonlocal invoked
        invoked = True
        raise AssertionError("Oversized input must not reach inference")

    request = ModelRequest(
        model=MockResident(),
        messages=[HumanMessage(content="x" * 600000)],
        tools=[],
        state={"call_index": 0},
        runtime=SimpleNamespace(context=Context(store, actors[0], "oversized")),
    )
    with pytest.raises(Waiting, match="Context exceeds"):
        await WorldContext().awrap_model_call(request, handler)
    assert not invoked and store.snapshot()["spent"] == 0


async def test_dynamic_toolset_lazy_loading(store, actors):
    from types import SimpleNamespace

    from langchain.agents.middleware.types import ModelRequest, ModelResponse

    from genesis_society.actions import execute
    from genesis_society.runtime import WorldContext
    from genesis_society.storage import uid

    unpause(store)
    with store.transaction() as (_, state):
        state["synthetic"] = False
    seen_tools = []

    async def handler(req):
        seen_tools.append({t.name for t in req.tools})
        return ModelResponse(result=[AIMessage(content="ok")])

    req0 = ModelRequest(
        model=MockResident(),
        messages=[HumanMessage(content="turn 0")],
        tools=tools(),
        state={"call_index": 0},
        runtime=SimpleNamespace(context=Context(store, actors[0], "lazy-test")),
    )
    await WorldContext().awrap_model_call(req0, handler)
    assert "use_toolset" in seen_tools[0]
    assert "read_source" not in seen_tools[0] and "write_object" not in seen_tools[0]

    execute(store, actors[0], {"kind": "use_toolset", "groups": ["github"]}, uid())
    req1 = req0.override(state={"call_index": 1})
    await WorldContext().awrap_model_call(req1, handler)
    assert "read_source" in seen_tools[1] and "write_object" not in seen_tools[1]


class RateLimitError(Exception):
    """Stands in for a provider 429; the ledger recognizes it by type name."""


def test_rate_limit_refunds_only_the_account_that_was_debited(store, actors):
    a, _ = actors
    unpause(store)
    ledger = Ledger(store)

    def set_balances(personal, transferable):
        with store.transaction() as (_, state):
            r = state["residents"][a]
            before = r["personal"] + r["transferable"]
            r["personal"], r["transferable"] = personal, transferable
            state["issued"] += personal + transferable - before
            assert conserve(state)

    def balances():
        r = store.snapshot()["residents"][a]
        return r["personal"], r["transferable"]

    for key, start, after_debit in (
        ("rl-personal", (1, 1), (0, 1)),
        ("rl-transferable", (0, 1), (0, 0)),
    ):
        set_balances(*start)
        spent_before = store.snapshot()["spent"]
        ledger.prepare(key, a, [HumanMessage(content="original")])
        ledger.mark_sent(key)
        assert balances() == after_debit
        with pytest.raises(Waiting):
            ledger.uncertain(key, RateLimitError("429"))
        assert balances() == start
        assert store.snapshot()["spent"] == spent_before
        with Session(store.engine) as session:
            assert session.get(Request, key).phase == "prepared"
        assert conserve(store.snapshot())


def test_rate_limit_without_debit_record_stays_ambiguous(store, actors):
    a, _ = actors
    unpause(store)
    ledger = Ledger(store)
    ledger.prepare("rl-legacy", a, [HumanMessage(content="original")])
    ledger.mark_sent("rl-legacy")
    with Session(store.engine) as session:
        req = session.get(Request, "rl-legacy")
        req.data = {k: v for k, v in req.data.items() if k != "debited"}
        session.commit()
    ledger.uncertain("rl-legacy", RateLimitError("429"))
    state = store.snapshot()
    assert state["residents"][a]["blocked"] == "uncertain_request:rl-legacy"
    with Session(store.engine) as session:
        assert session.get(Request, "rl-legacy").phase == "uncertain"
    assert conserve(state)


def test_unresolved_request_releases_resident_after_one_hour_and_keeps_ticket_spent(store, actors):
    a, _ = actors
    unpause(store)
    ledger = Ledger(store)
    ledger.prepare("ua-timeout", a, [HumanMessage(content="original")])
    ledger.mark_sent("ua-timeout")
    spent = store.snapshot()["spent"]
    ledger.uncertain("ua-timeout", TimeoutError("timed out"))
    with Session(store.engine) as session:
        stamped = session.get(Request, "ua-timeout").data["uncertain_at"]

    assert expire_uncertain(store, now=stamped + 3599) == []
    assert store.snapshot()["residents"][a]["blocked"] == "uncertain_request:ua-timeout"
    assert expire_uncertain(store, now=stamped + 3600) == [a]

    state = store.snapshot()
    assert state["residents"][a]["blocked"] is None
    assert state["spent"] == spent
    assert conserve(state)
    assert any(e["kind"] == "request_abandoned" and e["actor"] == a for e in state["events"])
    with Session(store.engine) as session:
        assert session.get(Request, "ua-timeout").phase == "abandoned"


def test_receipt_without_timestamp_starts_its_clock_at_first_sweep(store, actors):
    a, _ = actors
    unpause(store)
    ledger = Ledger(store)
    ledger.prepare("ua-legacy", a, [HumanMessage(content="original")])
    ledger.mark_sent("ua-legacy")
    ledger.uncertain("ua-legacy", TimeoutError("timed out"))
    with Session(store.engine) as session:
        req = session.get(Request, "ua-legacy")
        req.data = {k: v for k, v in req.data.items() if k != "uncertain_at"}
        session.commit()

    assert expire_uncertain(store, now=1_000.0) == []
    with Session(store.engine) as session:
        assert session.get(Request, "ua-legacy").data["uncertain_at"] == 1_000.0
    assert expire_uncertain(store, now=1_000.0 + 3599) == []
    assert expire_uncertain(store, now=1_000.0 + 3600) == [a]


def _fake_source_page(query):
    from genesis_society.sources import SourcePage

    return SourcePage(
        source_id=query.source_id,
        revision="rev1",
        captured_at="2026-01-01T00:00:00Z",
        text="hello",
        offset=0,
        next_offset=None,
        synthetic=False,
    )


async def test_source_io_runs_outside_the_world_lock(store, actors, monkeypatch):
    from sqlalchemy import text

    from genesis_society import actions
    from genesis_society.storage import uid

    actor = actors[0]
    with store.transaction() as (_, state):
        state["synthetic"] = False
    calls = []

    def fake_read(query):
        # NOWAIT raises if any other transaction holds the world row lock.
        with store.engine.connect() as connection, connection.begin():
            connection.execute(text("SELECT id FROM society_world WHERE id = 1 FOR UPDATE NOWAIT"))
        calls.append(query.source_id)
        return _fake_source_page(query)

    monkeypatch.setattr(actions, "read_source", fake_read)
    result = await actions.execute_async(
        store, actor, {"kind": "read_source", "source_id": "context:INDEX"}, uid()
    )
    assert calls == ["context:INDEX"]
    assert result["reference"] == "context:INDEX@rev1"


async def test_replayed_source_read_does_no_io_and_commits_once(store, actors, monkeypatch):
    from genesis_society import actions
    from genesis_society.storage import uid

    actor = actors[0]
    with store.transaction() as (_, state):
        state["synthetic"] = False
    calls = []

    def fake_read(query):
        calls.append(query.source_id)
        return _fake_source_page(query)

    monkeypatch.setattr(actions, "read_source", fake_read)
    action = {"kind": "read_source", "source_id": "context:INDEX"}
    key = uid()
    first = await actions.execute_async(store, actor, action, key)
    second = await actions.execute_async(store, actor, action, key)

    assert second == first
    assert calls == ["context:INDEX"]
    events = [e for e in store.snapshot()["events"] if e["kind"] == "read_source"]
    assert len(events) == 1


async def test_source_timeout_is_a_refusal_and_leaves_no_receipt(store, actors, monkeypatch):
    import subprocess

    from genesis_society import actions
    from genesis_society.storage import uid

    actor = actors[0]
    with store.transaction() as (_, state):
        state["synthetic"] = False

    def slow_read(query):
        raise subprocess.TimeoutExpired(cmd="gh", timeout=15)

    monkeypatch.setattr(actions, "read_source", slow_read)
    key = uid()
    with pytest.raises(ValueError, match="temporarily unavailable"):
        await actions.execute_async(
            store, actor, {"kind": "read_source", "source_id": "context:INDEX"}, key
        )
    assert f"{actor}:{key}" not in store.snapshot()["effects"]
