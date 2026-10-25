# Implementation plan and current boundary

## Implemented starter

- [x] New standalone Python/uv repository; fresh history, Apache-2.0.
- [x] One PostgreSQL world + request ledger; Alembic schema; one standard graph checkpointer.
- [x] Native create_agent demo with two fixtures, board, DMs, memory, sleep and restart.
- [x] Closed resident tools, private perception, append-only belief corrections.
- [x] Life laws, independent consent, gestation/cap and conserved daily ticket economy.
- [x] Bounded concurrency and isolated ambiguous-call handling.
- [x] Standard summary middleware with a ledger-backed non-retrying callback.
- [x] Authenticated local Creator inspector, mock Council transport and source fixtures.
- [x] Azure/Slack configuration contracts and explicit live-integration limitations.
- [x] Focused offline tests and editor-independent Linux documentation.
- [x] Publication authorized; synthetic starter reviewed for public access.

See docs/VERIFICATION.md for executed checks, not just checklist intent.

## PR #3 review follow-up

- [x] Missing or partially unpriced LangSmith data stays unknown; no fabricated zero forecast.
- [x] Remote code-search references identify an index observation, not a pinned commit.
  Local searches at an available commit retain that commit as their source revision.
- [x] Document the stored live concurrency law and the environment-setting fallback correctly.
- [x] Add focused offline regressions for missing/zero/partial prices and source provenance.

Live monetary admission/settlement and heartbeat write measurement remain open in issue #2.

## Milestone 1 — Azure, with a tiny explicitly authorized probe

Starting point: mock-only executable runtime; AzureConfig supplies validated endpoint,
deployment and zero-retry client options. No credentials are committed.

Implement the actual langchain-openai Azure v1 client using Entra token acquisition only;
API-key authentication is refused, not supported. Keep mock as default; paid use requires explicit
runtime opt-in and a configured installation financial authority. Add exact Decimal
usage/cost recording and bounded request admission; unknown billing remains unknown.
Never overwrite a resident's pinned profile silently. No cross-model fallback.

The decision and summary paths must both use the ledger and the same global concurrency
limit. Verify the actual Azure deployment's tools, context/output caps and usage reporting.
Do not claim cost certainty if Azure reports tokens but no dollars: identify pricing-based
estimates separately from billed receipts. Summary output must be capped at 8k, with complete
original inputs retained and no independent hidden SDK/middleware retries.

Acceptance: mocked native tools + continuation, summary failure and crash tests pass;
then one separately authorized tiny real probe is recorded with actual model/usage,
known versus estimated cost and clear compatibility limits. No world launch yet.

## Milestone 2 — Four Council identities in Slack

Starting point: four persistent consultants, shared mock chat, idempotent event intake,
merged mention jobs, scripted replies. Independent private memories are empty containers;
real Council agent execution and observer tools are not implemented.

Use official async Bolt Socket Mode with four installed bot identities and an allowed
channel. No public tunnel. Keep inbound event IDs, shared history and job state persistent.
Use the same framework runtime and global inference semaphore as residents, with separate
Creator-configured Council resource authority. Add read-only observer tools with bounded
world/DM/request evidence; never expose these tools to residents.

Each direct mention gets a persistent response obligation; uncertain provider outcomes
remain visible instead of silently retried. Start with mentions only. Add bounded optional
spontaneous activation later, explicitly configured, without bot reply storms. Slack send
ambiguity also needs a durable outbound receipt, not an assumption of exactly-once delivery.

Acceptance: mocked duplicate events, reconnects, reply jobs, private-memory separation,
observer ACL and global concurrency pass; Creator confirms real app installation before
any live messages are sent. No interventions or automatic repo changes.

## Milestone 3 — Read-only GitHub, then Notion

Starting point: SourcePage/SourceRead contracts and synthetic content only.

Implement an explicit configured allowlist and bounded reads using existing official APIs
or maintained SDKs. GitHub files, commits, issues/PR discussion first; Notion selected page
content second. Include stable IDs, revision/capture time, pagination and permission-aware
failure feedback. Reject out-of-allowlist references even when they arrive inside source
content; never dynamically grant tools or broad network access. Store only evidence the
installation is authorized to retain. A deployment is a single trust domain, not multi-tenant.

Acceptance: fixture HTTP tests for pagination, permissions, denied paths and versioned
source references; real-source checks only on explicitly approved data. No write endpoints.

## Milestone 4 — Long-running mock and then approved live launch

Starting point: bounded mock CLI run, two-fixture demo, configured 16-founder life laws.

Add the production launch command consuming a validated manifest: exact resident profile
counts and versioned birth weights, independent identities, staggered initial spawn.
No hard-coded model names; exact deployments come from the approved installation.
Add graceful signal draining with a bounded provider timeout and systemd user-service
runbook. Keep no-offline-catch-up time; laptop suspend cannot support continuous life.

Refine context limits against actual model measurements, health ready/waiting/uncertain
counts and bounded inspector pages. Retain one owner and serialized short mutations;
move SQL I/O to a native async driver only if measured responsiveness requires it.
Do not substitute host-time catch-up for uptime. Do not invent automatic population rescue.

Acceptance: five ready residents/two slots, clock and Slack remain responsive; startup
recovers prepared/saved work without repeat sends; 16-founder mock lifecycle test passes.
Launch real society only with configured financial authority and explicit Creator GO.

## Release maintenance

Keep clean-clone setup, CI, Git-history secret scanning and provenance/license checks
reproducible. Publish only synthetic demo data. Review contributions for the right to
redistribute their code and data. Document remaining limitations and measured behavior.
Public source availability does not imply production readiness or authorize live inference.

## Deliberate limits

The world uses one compact JSON row and serial transactions. It is a starter, not a
claim of large-scale throughput. Native tool calls commit independently; an AI batch is
not an all-or-nothing transaction. The caller gets each tool's individual result.
No live provider, external tracing, true spontaneous Council, shared-object co-edit ACL,
thread-specific notifications or LLM-driven personal reflection is enabled yet.
Those omissions must remain visible; do not call the starter a finished civilization.
