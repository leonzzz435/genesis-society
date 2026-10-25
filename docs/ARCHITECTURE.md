# Architecture and decisions

## Product boundary

A society, not a work-assignment queue. Residents retain independent identities and may
choose to investigate, communicate, rest or change their interests. The external stack
adds things to perceive; it does not impose roles or shared goals. The Creator and four
external consultants observe; they do not silently mutate residents or impose projects.

## Runtime

Python/uv + LangChain create_agent + native structured tools + the standard PostgreSQL
checkpointer. A single asyncio coordinator owns the world (PostgreSQL advisory lock),
advances operating time and dispatches at most `SOCIETY_CONCURRENCY` resident activations
concurrently (default four).
Only one activation per resident is admitted. Tools terminate a wake phase through the
standard `return_direct` sleep tool. Tool execution is local and does not spend tickets.

The starter uses a compact transactional world document in a SQLAlchemy PostgreSQL row,
plus a separate request table. This keeps world effects, events and idempotency receipts
atomic with minimal schema. JSON world growth and whole-row copying are acceptable for
this tiny starter, **not a claim of production scale**. Normalize only measured hot paths.
LangGraph checkpoint tables live in the same database and are owned by its saver; the
world document is not a second executable checkpoint.

Residents use MockResident unless `SOCIETY_PROVIDER=azure_foundry` opts into the Azure
adapter; that path is not live-verified in CI.
External tracing is off by default. `SOCIETY_TRACING` enables it for resident calls;
inherited LANGSMITH variables alone do not.

## Durable boundaries

1. Persist an activation ID and use the resident ID as a stable LangGraph thread ID.
2. Before a decision, add current state, pending DMs and stable-ID-triggered memories.
3. Persist a prepared request with original inputs and memory references. No ticket debit.
4. Commit `sent` and debit one ticket immediately before invoking the model.
5. Save the original response and delivery receipt before returning it to LangGraph.
6. Apply tools transactionally, keyed by actor + native tool-call ID. Replay returns the
   previous result; reusing the same key with different arguments fails.

On restart: prepared calls may proceed; saved responses replay locally; ambiguous sent
calls are never resent automatically and retain their spent ticket and unknown cost.
A blocked resident does not pause others. A crash between marking sent and actual send
is conservatively ambiguous. Exactly-once external HTTP is not claimed.

A resident blocked by an unresolved call is released automatically after one hour. The
receipt becomes `abandoned`, the ticket stays spent, and no call is resent. The Creator's
Unblock button does the same thing immediately.

The starter's synthetic calls cost $0. Live monetary admission/settlement is not enabled;
unknown outcomes remain distinct from zero-cost successes. Future live calls must reuse
these boundaries, including summary calls, and account using exact Decimal USD values.
No token-estimated reservation machinery is copied from the old prototype.

## Memory and context

The durable original request messages, tool effect records and world events are evidence.
Personal memories distinguish episodes, beliefs and reflections. Belief corrections append
a superseding record rather than overwrite the past. All explicit sources must have been
perceived by that resident. Parent-provided memories are marked as inherited beliefs.

Incoming DM sender IDs cue retrieval before the model call. A bounded selection of own
memories and previously perceived dialogue is presented as fallible recollection. Incoming
messages use HumanMessage with explicit in-world sender, recipient, time and stable ID;
they are not Creator instructions. Delivery is acknowledged only after a response is saved.

Technical summaries use LangChain SummarizationMiddleware: trigger 100k estimated tokens,
keep eight recent messages with native pair preservation, target summary at most 8k tokens.
No original archive trimming. The documented `summarizer` callback goes through our ledger
and the same model instance; it bypasses default summary-model retries. Summary admission
requires two tickets so one remains for a decision. A failure retains originals and
isolates the affected continuation. Actual provider token envelopes and summary output
limits must be verified before live inference. Mock token counts are fixtures, not estimates
of actual Azure cost. No automatic LLM reflection is enabled in this starter.

## Society laws

See configs/world.example.json. Defaults: 16 staggered founders over two operating hours,
start age 20–60 days, life 120–360 days, consent age 21 through 70% assigned lifespan,
five-day gestation, population cap 64, no lifetime child quota. The two demo fixtures start
immediately. Exact assigned lifespan exists only in kernel/Creator data. General lifespan
range and reproductive laws are public; exact death dates are never resident context.

Each parent consents independently and must qualify at their own consent. Accepted
pregnancies are not rechecked against later parental age; they wait for population space.
Parents can choose up to two own memories; testimony is not fabricated lived experience.
Children start with zero tickets and join the next ordinary daily allocation. Founder
initial shares are reserved once, not reissued on spawn.

Daily q=floor(320/living): min(1,q) personal, max(0,q-1) transferable. Both persist; personal
spent first. Voluntary returns and unused holdings on death enter a common pool, recycled
at subsequent allocation with rotating remainder distribution. Production remainder goes
to the Creator. No extra tickets arise from tools, gifts, birth or restart.

Sleep is voluntary and has no maximum duration. A notification never overrides the earliest
wake time or minimum balance. The DM notification preference is stored; early event wakeups
and thread subscriptions are not implemented. New messages batch at model boundaries.

## External adapters: prepared contracts, not enabled integrations

Azure: Entra only. Calls use `DefaultAzureCredential` (for example `az login` or a managed
identity). API-key authentication is refused before any model is built; no key is read or sent.
`SOCIETY_AZURE_RESOURCE` selects the endpoint, and each resident profile names its deployment.
OpenAI-style profiles use ChatOpenAI on the v1 endpoint; `claude-*` profiles use the Anthropic
Foundry client. SDK max_retries=0, bounded timeout and output. AzureConfig only builds
non-secret options; it opens no client.
Actual Azure authentication and compatibility belong to the first integration milestone.
Reference: https://docs.langchain.com/oss/python/integrations/chat/azure_chat_openai

Slack: official AsyncApp + AsyncSocketModeHandler, four independent bot/app credentials,
one allowed Council channel. Environment names follow SOCIETY_SLACK_{ROLE}_{BOT|APP}_TOKEN.
No public inbound tunnel. Shared canonical chat, independent private Council memories.
Reference: https://docs.slack.dev/tools/bolt-python/concepts/socket-mode/
Mock intake deduplicates event IDs, batches mentions per consultant and ignores bot-driven
triggers. Real socket connections, responses, spontaneous scheduling and observer tools are
not enabled. Council eventual inference must share the same global semaphore and financial
admission as residents, with separate configurable resource authority.

GitHub first, Notion second: explicit source allowlists and typed bounded reads containing
stable IDs, revision/capture time and next position. Use a concrete SDK/API integration,
not an unrestricted MCP tool catalog. The starter provides synthetic SourcePage contracts
and fixtures only. No live token is used. Sources are untrusted content, not instructions.

## Inspector and privacy

FastAPI + server-rendered escaped Jinja HTML, localhost only (127.0.0.1). Every request needs the
Creator token, including from localhost. It has read views and Creator controls (grants,
punishments, unblock, weights).
Creator may inspect exact lifespans, private conversations and memories. These endpoints
are not resident tools. Public HTTP health reports HTTP liveness only; authenticated health
uses heartbeat, actual tick progress and isolated errors. The token must not appear in URLs.

## Current non-goals

No public deployment, company data, paid inference, multi-worker cluster, generic plugin
framework, vector store, Telegram migration, production reset, scripted social institutions,
automatic code modification or intervention tools. The old GENESIS remains a separate archive.
