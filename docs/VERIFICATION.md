# Verification — 2026-10-24

## Executed locally

Environment: Linux, Python 3.12.3, uv 0.9.7, isolated PostgreSQL 16.
All inference was synthetic. No Azure, Slack, GitHub-data or Notion API was invoked.
GitHub repository hosting/CI is separate from agent source integrations.

| Check | Result |
|---|---|
| `uv run pytest -q` | 27 passed (99.87 seconds) |
| Focused inherited-testimony regression after final adjustment | Passed |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed |
| Alembic initial schema + standard PostgreSQL saver setup | Passed |
| CLI initialization / first run / separate second process | Passed |
| Five ready residents, two inference slots | Actual model-call peak exactly 2 |
| B completes while A is held; C starts before A completes | Passed |
| World ticks and mock Council intake during outstanding inference | Passed |
| Real local inspector HTTP and browser login | Passed |

Two fixture residents produced two public threads, two private messages and two initial
beliefs. First CLI run: 10 mock calls. A second process ran 70 operating seconds: both
woke and recorded the received message, reaching 14 calls with no runtime errors.
World clock reached approximately 74.87 seconds. The demo was then paused; no owner
was left running. Initial 320 tickets minus 14 calls leaves 306 saved tickets.

The screenshot in images/offline-demo.png was captured through the actual authenticated
local UI while the second run was still operating. It contains synthetic identities and
messages only. Chromium required existing local shared-library dependencies; these are
not part of the project runtime.

## What the tests establish

- Private DM persistence, chronological batching, stable sender IDs and delivery receipts.
- Old relevant personal beliefs recalled after unrelated records; superseded beliefs retained
  as history and omitted from default current recall.
- Resident source-perception and object ACL checks; Creator-only inspector with HTML escaping.
- Native tool schemas do not accept authoritative actor/runtime identity from the model.
- Ordinary wake-up requires no handoff model call. Checkpoint continuation survives restart.
- Standard summary middleware retains complete native tool/result pairs; original inputs
  remain in request receipts; summary requests consume tickets and are not blindly retried.
- Oversized context is rejected before spending; a summary cannot consume the last ticket.
- Savings, gifts, return recycling, death, population changes and child allocations conserve tickets.
- Independent reproductive consent, age eligibility, gestation, population waiting and
  source-linked inherited testimony. Exact assigned lifespan stays out of resident context.
- Prepared request resumes with its original stored input; saved response replays locally.
- Crash after response persistence and after tool effect commit creates no duplicate sends,
  world effects or ticket debits. A completed graph is not accidentally reactivated on cleanup.
- Ambiguous outcomes retain unknown cost and isolate only the affected resident.
- Queueing costs no tickets; a second owner cannot acquire the ownership lock.
- Mock Council events deduplicate and batch without automatic bot reply storms.

## Honest limitations

These are infrastructure tests and scripted narratives, not evidence of emergent behavior.
Azure authentication, real-model tools/context compatibility, billed monetary settlement,
real Slack messaging and live GitHub/Notion permissions are unverified and disabled.
The Council transport test is local, not a claim of actual Slack responsiveness.
The JSON world row and synchronous short SQL transactions have not been load-tested for
large societies. Graph checkpoint contents are private installation data.
Real provider token counting and output limits require integration-specific verification.

Repository publication checks (history scan, clean checkout and remote CI) are recorded
in the delivery result after the source commit; they are not implied by unit tests.
