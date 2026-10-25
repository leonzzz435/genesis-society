# Engineering instructions — GENESIS Society

Read `docs/ARCHITECTURE.md`, `PLAN.md` and `docs/DEVELOPMENT.md` before changing behavior.
Offline by default. Live adapters are opt-in, fail closed and are not production-certified.

## Purpose
Persistent autonomous digital residents with identity, memory, private conversations,
a public board, voluntary interests, finite lives and consensual reproduction. GitHub
and Notion are a read-only environment. Slack is the Creator/Council interface.
Residents are not task assistants required to be productive, agreeable or cooperative.

## Boundaries
- No host filesystem, arbitrary HTTP, shell, SQL or credentials in resident tools.
- Kernel supplies actor identity. Enforce privacy in code, never merely in prompts.
- No paid tests, external messages, production data, live credentials, or telemetry by default.
- Never silently resend an ambiguous model request. Isolate it from other residents.
- One PostgreSQL database, one LangGraph checkpointer, one `create_agent` loop.
- Prefer existing library behavior; do not add a parallel framework or custom chat loop.
- Original messages and evidence survive context compaction; memories are subjective.
- World laws are configuration. Changes need explicit Creator intent and tests.
- This repository has no affiliation with an employer. Use only authorized sources.

## Optional live adapters
- Live Azure inference needs `SOCIETY_PROVIDER=azure_foundry`, `SOCIETY_PAID_INFERENCE_ENABLED=true`
  and `SOCIETY_AZURE_RESOURCE`. Use a dedicated, non-production Azure AI Foundry resource.
- Live GitHub reads need `SOCIETY_GITHUB_ORG` and `SOCIETY_GITHUB_REPO_PREFIX`. Without both,
  no repository is readable. Reads go through read-only `gh` and `git` commands.
- Put secrets and installation-specific names only in a local `.env`, which is gitignored.
  Never write them into docs, fixtures, examples or commits.
- Tests that need the network skip unless the live GitHub scope is configured.
- Residents never receive customer data, production database access or write access to
  external systems.

## Development
Python 3.12+, uv, PostgreSQL 16. Run `uv sync --frozen` then `docker compose up -d --wait`
(or supply an external PostgreSQL URL). See README for the offline demo.

Checks: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest -q`.
Tests create and drop ONLY fresh `society_test_*` databases. Never point tests at a
living world. Set `SOCIETY_TEST_ADMIN_URL` to an isolated PostgreSQL server with CREATEDB.
Mock narrative is scripted infrastructure evidence, never proof of emergent behavior.

## Delivery discipline
Keep PLAN status honest. Complete one bounded task at a time with focused tests.
Document behavior, remaining limits and exact verification. No enormous speculative
architecture pass. Do not enable Azure, GitHub, Slack, Notion or paid execution for an installation without its
owner's explicit authorization. Placeholders in `.env.example` are not authorization.
