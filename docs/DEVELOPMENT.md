# Development guide

GENESIS Society is an offline research starter for persistent autonomous residents.
The runnable demo uses scripted models and synthetic sources. Live integrations are
separate implementation milestones, not enabled features.

## Development environment

1. Clone using the HTTPS URL in the README; no GitHub login is needed.
2. Follow the Linux quick start with Python 3.12, uv and PostgreSQL 16.
3. Run the mock demo, restart it and inspect its persisted state.
4. Run Ruff and the offline tests against an isolated development database.
5. Read [architecture](ARCHITECTURE.md), [verification](VERIFICATION.md) and the
   [implementation plan](../PLAN.md) before changing behavior.

Use any editor. [AGENTS.md](../AGENTS.md) documents the engineering boundaries for
contributors and coding assistants. No previous project or conversation is required.

## One integration at a time

Start with milestone 1 in PLAN.md: Azure model integration. Reuse the existing LangChain
agent loop, PostgreSQL checkpointer and durable request ledger. Preserve resident
autonomy, original evidence, private memory and ticket conservation.

Then implement Slack Council connectivity, allowlisted GitHub/Notion reads and the
long-running launch workflow, in that order. Each milestone defines its starting point,
constraints and acceptance criteria. Keep mock execution available throughout.

Credentials, deployments and source permissions belong to each installation. Copy the
placeholder environment template locally; never commit secrets or private source data.
Live inference and external messaging require installation-specific approval. Editor
subscriptions do not provide model API access.

## Verification

Use focused offline regression tests for changed behavior, plus Ruff. State separately
what is implemented, tested and unverified. Scripted demos prove infrastructure behavior;
they do not establish emergent cooperation or real-model reliability.
