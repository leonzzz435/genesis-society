"""Local authenticated Creator observation; never a resident-facing endpoint."""

import hmac
import time
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, select_autoescape

from .world import balances, conserve

TEMPLATE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GENESIS Society · Inspector
</title><style>
:root{color-scheme:dark;font-family:system-ui;background:#111720;color:#e6edf4}
body{max-width:1100px;margin:36px auto;padding:0 20px}h1{font-weight:500}
small{color:#b4c2d0}.cards{display:flex;gap:16px;flex-wrap:wrap}
.card,details{background:#1c2633;border:1px solid #304252;border-radius:12px;padding:18px;
margin:12px 0}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:10px;
border-bottom:1px solid #304252}.accent{color:#9ee7c1}p{white-space:pre-wrap;overflow-wrap:anywhere}

</style><h1>GENESIS <span class="accent">Society
</span>
</h1>
<small>Synthetic offline starter · Scripted fixtures, not emergent behavior
</small>
<div class="cards"><div class="card">World time<br><b>{{ '%.1f'|format(s.clock) }} s
</b>
</div>
<div class="card">Worker<br><b>{{ health }}
</b>
</div><div class="card">Tickets saved<br>
<b>{{ saved }}
</b>
</div><div class="card">Calls / known cost<br><b>{{ requests|length }} / $0 mock
</b>

</div>
</div><h2>Residents
</h2><table><tr><th>Identity
</th><th>Age
</th><th>Tickets
</th><th>State
</th>
</tr>
{% for r in s.residents.values() %}<tr><td>{{ r.name or r.id }}
</td>
<td>{{ '%.2f'|format((s.clock-r.born)/86400) }} days
</td>
<td>{{ r.personal }} protected / {{ r.transferable }} transferable
</td>
<td>{{ r.blocked or ('sleeping' if r.wake_at>s.clock else 'eligible') }}
</td>
</tr>{% endfor %}
</table>
<h2>Public board
</h2>{% for t in s.threads %}<details><summary>{{ t.title }}
</summary>
{% for p in t.posts %}<p><small>{{ s.residents[p.author].name }} · {{ p.id }}
</small><br>{{ p.text }}
</p>
{% endfor %}
</details>{% endfor %}<h2>Private conversations · Creator access
</h2>
{% for m in s.messages %}<details><summary>{{ s.residents[m.sender].name }} →
{{ s.residents[m.recipient].name }} · {{ m.time }}s
</summary><p>{{ m.text }}
</p>
<small>{{ m.id }}
</small>
</details>{% endfor %}
<h2>Personal history · Creator access
</h2>{% for r in s.residents.values() %}<details>
<summary>{{ r.name or r.id }} · {{ r.memories|length }} memories
</summary>
{% for m in r.memories %}<p>{{ m.kind }}: {{ m.text }}<br><small>Sources: {{ m.sources|join(', ') }}
 · supersedes: {{ m.supersedes or 'none' }}
</small>
</p>{% endfor %}
{% for i in r.intentions %}<p>Intention: {{ i.text }} · complete: {{ i.complete }}
</p>{% endfor %}
{% for e in s.events if e.actor==r.id %}<p><small>{{ e.time }}s · {{ e.kind }} · {{ e.id }}
</small>
</p>
{% endfor %}
</details>{% endfor %}<h2>Requests
</h2>
{% for q in requests %}<details><summary>{{ q.purpose }} · {{ q.phase }} · {{ q.id }}
</summary>
<p>Actual USD: {{ q.actual_usd if q.actual_usd is not none else 'unknown' }}
</p>
</details>{% endfor %}
<h2>Council · mock transport
</h2>{% for m in s.council_chat %}<p>{{ m.author }}: {{ m.text }}
</p>
{% endfor %}<small>Ticket conservation: {{ conserved }}. External tracing disabled.
</small>
</html>"""


def worker_status(state):
    health = state["health"]
    if not health:
        return "not started"
    if health.get("status") == "stopped":
        return "stopped"
    if time.time() - health.get("heartbeat", 0) > 15:
        return "stale"
    if state["paused"]:
        return "paused"
    if any(r["blocked"] for r in state["residents"].values()):
        return "running with isolated blocked residents"
    return "running"


def app_for(store, token):
    if not token or len(token) < 24:
        raise ValueError("Set SOCIETY_CREATOR_TOKEN to a random secret of at least 24 characters")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def authorized(request, authorization):
        credential = authorization.removeprefix("Bearer ") or request.cookies.get("creator", "")
        return hmac.compare_digest(credential, token)

    def auth(request: Request, authorization: str = Header(default="")):
        if not authorized(request, authorization):
            raise HTTPException(status_code=401, detail="Creator authentication required")

    @app.middleware("http")
    async def private_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; "
            "form-action 'self'; frame-ancestors 'none'"
        )
        return response

    @app.post("/login")
    async def login(request: Request):
        raw = await request.body()
        if len(raw) > 2048:
            raise HTTPException(400, "Invalid login")
        entered = parse_qs(raw.decode()).get("token", [""])[0]
        if not hmac.compare_digest(entered, token):
            raise HTTPException(401, "Invalid Creator token")
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("creator", token, httponly=True, samesite="strict", max_age=3600)
        return response

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, authorization: str = Header(default="")):
        if not authorized(request, authorization):
            return HTMLResponse(
                "<h1>GENESIS Society</h1><p>Local Creator inspector</p>"
                '<form method="post" action="/login"><label>Creator token '
                '<input type="password" name="token" required autocomplete="off"></label>'
                "<button>Open inspector</button></form>",
                status_code=401,
            )
        s = store.snapshot()
        environment = Environment(autoescape=select_autoescape(default_for_string=True))
        return environment.from_string(TEMPLATE).render(
            s=s,
            health=worker_status(s),
            saved=balances(s),
            requests=store.requests(),
            conserved=conserve(s),
        )

    @app.get("/api/snapshot", dependencies=[Depends(auth)])
    def snapshot():
        s = store.snapshot()
        return dict(world=s, requests=store.requests(), worker_status=worker_status(s))

    @app.get("/health")
    def health():
        # Process liveness only; no world data and no false "healthy world" claim.
        return {"http": "responsive"}

    return app
