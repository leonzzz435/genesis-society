"""Local authenticated Creator observation and Control Room; never a resident-facing endpoint."""

import hmac
import time
from collections import Counter
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, select_autoescape

from .config import Laws
from .storage import uid
from .world import (
    balances,
    conserve,
    delegation_cycles,
    dispatch_quorum,
    eligible,
    emit,
    format_world_time,
    living,
    release_actor,
    voting_weight,
)

TEMPLATE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GENESIS Society · Control Room</title><style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,sans-serif;
background:#0b0f17;color:#e6edf4}
*{box-sizing:border-box}body{margin:0;line-height:1.45;font-size:0.92rem}
h1,h2,h3{font-weight:600;margin:0 0 8px}h2{font-size:1.12rem}h3{font-size:0.96rem}
small,.muted{color:#8b9eb3;font-size:0.82rem}
.accent{color:#7ee787}.warn{color:#f2cc60}.danger{color:#ff7b72}.info{color:#58a6ff}
p{white-space:pre-wrap;overflow-wrap:anywhere;margin:6px 0}
input,select,button{background:#0b0f17;color:#e6edf4;border:1px solid #2b3d52;
border-radius:7px;padding:6px 10px;font-size:0.86rem}
button{background:#238636;border-color:#2ea043;color:#fff;font-weight:500;cursor:pointer}
button.secondary{background:#182432;border-color:#2b3d52}
.shell{display:grid;grid-template-columns:255px 1fr;min-height:100vh}
.side{background:#101722;border-right:1px solid #1e2c3d;padding:18px 14px;
display:flex;flex-direction:column;gap:6px;position:sticky;top:0;height:100vh;overflow-y:auto}
.main{padding:22px 28px;max-width:1240px;width:100%}
.nav-sec{font-size:0.73rem;text-transform:uppercase;letter-spacing:.06em;
color:#6e8299;margin:12px 8px 4px}
input.tab-rad{display:none}
label.nav-btn{display:flex;justify-content:space-between;align-items:center;
padding:7px 11px;border-radius:7px;cursor:pointer;color:#b4c4d4;font-size:0.88rem}
label.nav-btn:hover{background:#182332;color:#fff}
.panel{display:none}
#t-over:checked ~ .shell .p-over,
#t-disp:checked ~ .shell .p-disp,
#t-board:checked ~ .shell .p-board,
#t-dm:checked ~ .shell .p-dm,
#t-obj:checked ~ .shell .p-obj,
#t-res:checked ~ .shell .p-res,
#t-ctrl:checked ~ .shell .p-ctrl{display:block}
#t-over:checked ~ .shell label[for="t-over"],
#t-disp:checked ~ .shell label[for="t-disp"],
#t-board:checked ~ .shell label[for="t-board"],
#t-dm:checked ~ .shell label[for="t-dm"],
#t-obj:checked ~ .shell label[for="t-obj"],
#t-res:checked ~ .shell label[for="t-res"],
#t-ctrl:checked ~ .shell label[for="t-ctrl"]{background:#1f3247;color:#fff;font-weight:600}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));
gap:12px;margin:0 0 16px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(410px,1fr));
gap:14px;margin:12px 0}
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));
gap:14px;margin:12px 0}
.card,details.sub{background:#131c27;border:1px solid #223244;border-radius:11px;
padding:14px;margin:8px 0}
summary{cursor:pointer;font-weight:500;user-select:none}
table{width:100%;border-collapse:collapse;font-size:0.88rem}
td,th{text-align:left;padding:8px 7px;border-bottom:1px solid #1c2a39;vertical-align:top}
.field{display:flex;justify-content:space-between;align-items:center;
padding:5px 0;border-bottom:1px solid #1a2634;font-size:0.86rem}
.bar{height:8px;background:#1c2a39;border-radius:4px;overflow:hidden;width:90px;
display:inline-block;vertical-align:middle;margin:0 6px}
.fill{height:100%;background:#7ee787}
.fill.blue{background:#58a6ff}.fill.gold{background:#f2cc60}
.badge{display:inline-block;padding:2px 7px;border-radius:99px;font-size:0.74rem;
background:#1a2636;border:1px solid #2d4057;margin:1px;color:#c9d6e3}
.badge.green{background:#112a1e;border-color:#2ea043;color:#7ee787}
.badge.gold{background:#2c2210;border-color:#9e6a03;color:#f2cc60}
.badge.red{background:#30161a;border-color:#8e2a30;color:#ff7b72}
.badge.tag{background:#152538;border-color:#2b4c70;color:#79c0ff}
.msg{background:#0e151f;border:1px solid #1d2b3b;border-radius:9px;padding:10px 13px;margin:7px 0}
.msg-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
.tree{display:flex;flex-wrap:wrap;gap:10px;margin-top:8px}
.node{background:#0e151f;border:1px solid #24364a;border-radius:9px;padding:9px 11px;
min-width:185px;flex:1}
.tip{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;
border-radius:50%;background:#1e2f42;color:#8ab4f8;font-size:0.7rem;cursor:help;position:relative}
.tip:hover::after{content:attr(data-tip);position:absolute;bottom:125%;left:50%;
transform:translateX(-50%);background:#0d1520;border:1px solid #355070;color:#e6edf4;
padding:6px 9px;border-radius:7px;width:230px;font-size:0.74rem;z-index:30;white-space:normal}
.org-vp{background:#0a0f16;border:1px solid #1f3044;border-radius:10px;overflow:auto;
max-height:460px;padding:18px;cursor:grab;user-select:none;position:relative}
.org-vp:active{cursor:grabbing}
.org-stage{transform-origin:top center;transition:transform 0.12s ease-out;
display:inline-block;min-width:100%}
.org-tree,.org-tree ul{padding-top:18px;position:relative;display:flex;
justify-content:center;margin:0;padding-left:0;list-style:none}
.org-tree li{float:left;text-align:center;list-style-type:none;position:relative;
padding:18px 6px 0 6px}
.org-tree li::before,.org-tree li::after{content:'';position:absolute;top:0;right:50%;
border-top:2px solid #2e4763;width:50%;height:18px}
.org-tree li::after{right:auto;left:50%;border-left:2px solid #2e4763}
.org-tree li:only-child::after,.org-tree li:only-child::before{display:none}
.org-tree li:only-child{padding-top:0}
.org-tree li:first-child::before,.org-tree li:last-child::after{border:0 none}
.org-tree li:last-child::before{border-right:2px solid #2e4763;border-radius:0 6px 0 0}
.org-tree li:first-child::after{border-radius:6px 0 0 0}
.org-tree ul ul::before{content:'';position:absolute;top:0;left:50%;
border-left:2px solid #2e4763;width:0;height:18px}
.org-card{display:inline-block;background:#121c29;border:1px solid #2b435e;
border-radius:9px;padding:7px 10px;min-width:138px;max-width:185px;text-align:left;
box-shadow:0 3px 10px rgba(0,0,0,.35)}
.org-card.root{background:#162638;border-color:#3b628b;text-align:center;min-width:220px}
.org-card.gest{border:1px dashed #d29922;background:#1f1b12}
.org-card.prop{border:1px dashed #58a6ff;background:#101c2b}
.org-card.dead{opacity:0.55;border-color:#6e282e}
.tree-ctl{padding:4px 9px;border-radius:6px;background:#182432;border:1px solid #2b3d52;
cursor:pointer;font-size:0.8rem;color:#b4c4d4}
#m-fam:checked ~ .card label[for="m-fam"],
#m-gov:checked ~ .card label[for="m-gov"],
#z-65:checked ~ .card label[for="z-65"],
#z-85:checked ~ .card label[for="z-85"],
#z-100:checked ~ .card label[for="z-100"],
#z-125:checked ~ .card label[for="z-125"],
#z-150:checked ~ .card label[for="z-150"]{background:#238636;border-color:#2ea043;color:#fff}
#m-fam:checked ~ .card .t-view-gov{display:none}
#m-gov:checked ~ .card .t-view-fam{display:none}
#z-65:checked ~ .card .org-stage{transform:scale(0.65)}
#z-85:checked ~ .card .org-stage{transform:scale(0.85)}
#z-100:checked ~ .card .org-stage{transform:scale(1)}
#z-125:checked ~ .card .org-stage{transform:scale(1.25)}
#z-150:checked ~ .card .org-stage{transform:scale(1.5)}
</style>

<input class="tab-rad" type="radio" name="nav" id="t-over" checked>
<input class="tab-rad" type="radio" name="nav" id="t-disp">
<input class="tab-rad" type="radio" name="nav" id="t-board">
<input class="tab-rad" type="radio" name="nav" id="t-dm">
<input class="tab-rad" type="radio" name="nav" id="t-obj">
<input class="tab-rad" type="radio" name="nav" id="t-res">
<input class="tab-rad" type="radio" name="nav" id="t-ctrl">

<div class="shell">
<aside class="side">
<div>
<h1 style="font-size:1.15rem">GENESIS <span class="accent">Society</span></h1>
<small>{{ stats.timestamp }} · {{ health }}</small>
</div>
<div style="display:flex;gap:6px;margin:6px 0">
<a href="/" style="flex:1;text-decoration:none">
<button class="secondary" style="width:100%">↻ Refresh</button></a>
<form method="post" action="/control" style="margin:0;flex:1">
<input type="hidden" name="action" value="toggle_pause">
<button class="{{ '' if s.paused else 'secondary' }}" style="width:100%">
{{ '▶ Resume' if s.paused else '⏸ Pause' }}</button></form>
</div>

<div class="nav-sec">Channels</div>
<label class="nav-btn" for="t-over"><span>📊 #overview</span>
<span class="badge">{{ stats.living_count }}/{{ s.residents|length }}</span></label>
<label class="nav-btn" for="t-disp"><span>📣 #dispatches</span>
<span class="badge {{ 'gold' if s.escalations else '' }}">
{{ (s.escalations or [])|length }}</span></label>
<label class="nav-btn" for="t-board"><span>💬 #public-board</span>
<span class="badge">{{ s.threads|length }}</span></label>
<label class="nav-btn" for="t-obj"><span>📜 #shared-objects</span>
<span class="badge">{{ s.objects|length }}</span></label>

<div class="nav-sec">Direct & People</div>
<label class="nav-btn" for="t-dm"><span>✉️ Direct Messages</span>
<span class="badge">{{ stats.conversations|length }}</span></label>
<label class="nav-btn" for="t-res"><span>👥 Residents & Lineage</span>
<span class="badge">{{ s.residents|length }}</span></label>

<div class="nav-sec">Administration</div>
<label class="nav-btn" for="t-ctrl"><span>⚙️ Creator & Ledger</span>
<span class="badge">{{ requests|length }}</span></label>

<div style="margin-top:auto;padding-top:12px;border-top:1px solid #1d2b3a">
<small>Tickets: <b>{{ saved }}</b> saved · <b>{{ s.spent }}</b> spent<br>
Children: <b>{{ stats.nursery.gestating|length }}🤰</b> ·
<b>{{ stats.nursery.proposed|length }}💌</b> ·
<b>{{ stats.nursery.born_total }}👶</b><br>
{% if stats.cost.known %}Est. cost: <b>${{ stats.cost.today_usd }}</b> ·
7d est: <b>${{ stats.cost.proj_7d_usd }}</b>{% else %}Cost: <b>unknown</b>
(LangSmith unreachable){% endif %}<br>
Quorum: <b>{{ stats.quorum }} votes</b> · Top: {{ stats.top_leader }}</small>
</div>
</aside>

<main class="main">
<div class="cards">
<div class="card">World Clock<br>
<b style="font-size:1.1rem">{{ stats.timestamp }}</b><br>
<small>{{ '%.1f'|format(s.clock) }}s · Worker: {{ health }}</small></div>
<div class="card">Ticket Economy<br>
<b style="font-size:1.1rem">{{ saved }} saved · {{ s.spent }} spent</b>
<div class="bar" style="width:100%;margin:4px 0">
<span class="fill" style="width:{{ (saved * 100 // (s.issued or 1)) }}%"></span></div>
<small>Issued: {{ s.issued }} · Pool: {{ s.pool }}</small></div>
<div class="card">🍼 Children in Loop<br>
<b style="font-size:1.1rem">{{ stats.nursery.gestating|length }}🤰 womb ·
{{ stats.nursery.proposed|length }}💌 open ·
{{ stats.nursery.born_total }}👶 born</b><br>
<small>🌱 Fertile: <b>{{ stats.nursery.fertile_count }}/{{ stats.living_count }}</b> ·
Cap: {{ s.residents|length }}/{{ s.laws.population_cap }}</small></div>
<div class="card">Governance & Telemetry<br>
<b style="font-size:1.1rem">{{ stats.quorum }}v quorum · {{ stats.repo_reads }} GH reads</b><br>
<small>Top: {{ stats.top_leader }} · {{ stats.total_tool_calls }} tools ·
{{ 'Dispatch Open' if stats.dispatch_open else 'Dispatch Sent' }}</small></div>
<div class="card">Estimated cost & 7-day forecast
<span class="tip"
 data-tip="LangSmith estimate (cached 30s), scaled by daily tickets. Not billing."
>?</span><br>
{% if stats.cost.known %}<b style="font-size:1.1rem">${{ stats.cost.today_usd }} today</b>
 <small class="muted">(total ${{ stats.cost.total_usd }})</small><br>
<small>Est. Day: <b>${{ stats.cost.proj_day_usd }}</b> ·
7d: <b class="accent">${{ stats.cost.proj_7d_usd }}</b>
 (${{ stats.cost.per_ticket_usd }}/t)</small>{% else %}<b style="font-size:1.1rem">Unknown</b>
 <small class="muted">LangSmith cost lookup failed; retrying every 30s</small>{% endif %}</div>
</div>

{% macro render_tree_node(n) %}
<li>
<div class="org-card {{ n.css }}">
<div style="display:flex;justify-content:space-between;align-items:center;gap:4px">
<b>{{ n.icon }} {{ n.name }}</b>
<span class="badge {{ n.badge_css }}">{{ n.badge }}</span>
</div>
<small class="muted">{{ n.sub }}</small>
{% if n.extra %}<div style="margin-top:3px"><small>{{ n.extra }}</small></div>{% endif %}
</div>
{% if n.children %}
<details open style="display:inline"><summary style="font-size:0.74rem;color:#79c0ff">
▾ {{ n.children|length }} branch{{ 'es' if n.children|length != 1 else '' }}</summary>
<ul>{% for c in n.children %}{{ render_tree_node(c) }}{% endfor %}</ul>
</details>
{% endif %}
</li>
{% endmacro %}

<!-- 1. OVERVIEW PANEL -->
<section class="panel p-over">
<input class="tab-rad" type="radio" name="tmode" id="m-fam" checked>
<input class="tab-rad" type="radio" name="tmode" id="m-gov">
<input class="tab-rad" type="radio" name="tzoom" id="z-65">
<input class="tab-rad" type="radio" name="tzoom" id="z-85">
<input class="tab-rad" type="radio" name="tzoom" id="z-100" checked>
<input class="tab-rad" type="radio" name="tzoom" id="z-125">
<input class="tab-rad" type="radio" name="tzoom" id="z-150">
<div class="card" style="margin-bottom:14px">
<div style="display:flex;justify-content:space-between;align-items:center;
flex-wrap:wrap;gap:8px;margin-bottom:8px">
<div>
<h3 style="margin:0">🌳 Interactive Top-Down Resident Hierarchy
 <small class="muted">(zoom &amp; scroll · click ▾ on any branch to fold/unfold)</small></h3>
</div>
<div style="display:flex;gap:5px;align-items:center;flex-wrap:wrap">
<label class="tree-ctl" for="m-fam">🧬 Dynasty &amp; Family (Parents → Kids)</label>
<label class="tree-ctl" for="m-gov">🏛️ Allegiance &amp; Politics (Leaders → Vassals)</label>
<span class="muted" style="margin-left:4px">Zoom:</span>
<label class="tree-ctl" for="z-65">65%</label>
<label class="tree-ctl" for="z-85">85%</label>
<label class="tree-ctl" for="z-100">100%</label>
<label class="tree-ctl" for="z-125">125%</label>
<label class="tree-ctl" for="z-150">150%</label>
</div>
</div>

<div class="org-vp">
<div class="org-stage">
<div class="t-view-fam">
<ul class="org-tree">
<li>
<div class="org-card root">
<b>🌍 GENESIS Dynasty Tree</b><br>
<small class="muted">{{ stats.living_count }} living ·
{{ stats.nursery.born_total }}👶 born ·
{{ stats.nursery.gestating|length }}🤰 in womb ·
{{ stats.nursery.proposed|length }}💌 proposed</small>
</div>
<details open><summary style="font-size:0.75rem;color:#79c0ff">
▾ Founders ({{ stats.lineage_tree|length }})</summary>
<ul>{% for n in stats.lineage_tree %}{{ render_tree_node(n) }}{% endfor %}</ul>
</details>
</li>
</ul>
</div>
<div class="t-view-gov">
<ul class="org-tree">
<li>
<div class="org-card root">
<b>🏛️ Political &amp; Allegiance Hierarchy</b><br>
<small class="muted">Dispatch Quorum: <b>{{ stats.quorum }} votes</b> ·
Top Leader: {{ stats.top_leader }}</small>
</div>
<details open><summary style="font-size:0.75rem;color:#79c0ff">
▾ Leaders &amp; Citizens ({{ stats.allegiance_tree|length }})</summary>
<ul>{% for n in stats.allegiance_tree %}{{ render_tree_node(n) }}{% endfor %}</ul>
</details>
{% if stats.delegation_cycles %}
<div class="org-card"><b>⚠️ Allegiance loops ({{ stats.delegation_cycles|length }})</b><br>
{% for c in stats.delegation_cycles %}
<small>{{ c|join(' → ') }} → {{ c[0] }}</small><br>
{% endfor %}
<small class="muted">New loops are refused. Existing ones are listed here for the Creator.</small>
</div>
{% endif %}
</li>
</ul>
</div>
</div>
</div>
</div>

<div class="grid3">
<div class="card">
<h3>🍼 Nursery & Reproduction Loop</h3>
<div class="field"><span>🌱 Fertile Adults Ready</span>
<span class="badge green">{{ stats.nursery.fertile_count }} / {{ stats.living_count }}</span></div>
<div class="field"><span>💌 Open Proposals (awaiting consent)</span>
<span class="badge">{{ stats.nursery.proposed|length }}</span></div>
<div class="field"><span>🤰 Active Pregnancies (in womb)</span>
<span class="badge gold">{{ stats.nursery.gestating|length }}</span></div>
<div class="field"><span>👶 Born Children (Gen 1+)</span>
<span class="badge green">{{ stats.nursery.born_living }} living /
 {{ stats.nursery.born_total }} total</span></div>
{% for g in stats.nursery.gestating %}
<div class="msg" style="border-color:#9e6a03">
<b>🤰 {{ g.child_name }}</b> <span class="badge gold">due in {{ g.due_str }}</span><br>
<small>{{ g.parents_label }} · +{{ g.gift_tickets }}🎁 tickets · {{ g.notes }} memories</small>
<div class="bar" style="width:100%;margin-top:4px">
<span class="fill gold" style="width:{{ g.pct }}%"></span></div>
</div>{% endfor %}
{% for p in stats.nursery.proposed %}
<div class="msg" style="border-color:#2b4c70">
<b>💌 {{ p.child_name }}</b> <span class="badge tag">awaiting consent</span><br>
<small>{{ p.parents_label }} · +{{ p.gift_tickets }}🎁 offered · {{ p.notes }} memories</small>
</div>{% endfor %}
{% if not stats.nursery.gestating and not stats.nursery.proposed %}
<small class="muted">No active pregnancies or proposals right now.
{{ stats.nursery.fertile_count }} residents are currently fertile and eligible.</small>
{% endif %}
</div>

<div class="card">
<h3>🛠️ Tool Telemetry ({{ stats.total_tool_calls }})</h3>
{% for name, count, pct in stats.tool_chart %}
<div class="field"><span><code>{{ name }}</code></span>
<span><span class="bar"><span class="fill blue" style="width:{{ pct }}%"></span></span>
<b>{{ count }}</b></span></div>
{% else %}<small class="muted">No tool calls yet.</small>{% endfor %}
{% if stats.top_repos %}
<h3 style="margin-top:12px">Top Explored Repos</h3>
{% for repo, count in stats.top_repos %}
<div class="field"><small>{{ repo }}</small><span class="badge">{{ count }} reads</span></div>
{% endfor %}{% endif %}
</div>

<div class="card">
<h3>🧬 Generations & Model Mix</h3>
{% for gen, members in stats.generations %}
<div class="field">
<span><b>Gen {{ gen }}</b> <small class="muted">({{ members|length }})</small></span>
<span>{% for m in members %}
<span class="badge {{ 'green' if m.alive else 'red' }}">{{ m.name }}</span>
{% endfor %}</span></div>{% endfor %}
<h3 style="margin-top:12px">Living Models</h3>
{% for fam, count, pct in stats.model_chart %}
<div class="field"><small>{{ fam }}</small>
<span><span class="bar"><span class="fill gold" style="width:{{ pct }}%"></span></span>
<b>{{ count }}</b></span></div>{% endfor %}
{% if stats.cost.by_model %}
<h3 style="margin-top:12px">💰 Estimated cost by model (LangSmith)</h3>
{% for mod, usd, pct in stats.cost.by_model %}
<div class="field"><small>{{ mod }}</small>
<span><span class="bar"><span class="fill" style="width:{{ pct }}%"></span></span>
<b>${{ usd }}</b></span></div>{% endfor %}{% endif %}
</div>
</div>
</section>

<!-- 2. DISPATCHES & DECREES PANEL -->
<section class="panel p-disp">
<h2>📣 Daily Team Dispatches & Creator Decrees</h2>
{% for d in stats.decrees %}
<div class="card" style="border-left:4px solid #f2cc60">
<b>{{ d.text }}</b> <small class="muted">· Day {{ d.epoch }} ({{ '%.0f'|format(d.time) }}s)</small>
<div style="margin-top:6px"><small>
<span class="badge green">👁️ Read on wake ({{ d.read_names|length }}/{{ stats.living_count }}):
 {{ d.read_names|join(', ') or 'none yet' }}</span>
{% if d.pending_names %}
<span class="badge">💤 Pending next wake ({{ d.pending_names|length }}):
 {{ d.pending_names|join(', ') }}</span>{% endif %}
</small></div>
</div>{% endfor %}
{% for e in (s.escalations or [])|reverse %}
<div class="card">
<div class="msg-head">
<span><b>Day {{ e.epoch }} · {{ e.title }}</b></span>
<span class="badge {{ 'green' if e.status == 'sent' else 'gold' }}">
{{ e.status or 'sent' }} · {{ e.votes or 1 }}/{{ e.quorum or stats.quorum }} votes</span>
</div>
<small>Signers: <b>{{ (e.signer_names or [e.author_name])|join(', ') }}</b></small>
<p>{{ e.text }}</p>
<small class="muted">Sources: {{ e.sources|join(', ') }}</small>
{% if e.verdict %}<p><b class="accent">{{ e.verdict }}</b></p>{% endif %}
<form method="post" action="/control" style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">
<input type="hidden" name="action" value="grant">
<input type="hidden" name="recipient_id" value="__signers__">
<input type="hidden" name="escalation_id" value="{{ e.id }}">
<select name="kind"><option value="reward">Reward All Signers (+)</option>
<option value="punish">Punish All Signers (-)</option>
<option value="execute">Execute All Signers</option></select>
<input name="amount" type="number" min="1" value="25" style="width:65px">
<input name="reason" placeholder="Public verdict reason to all residents..." style="flex:1">
<button class="secondary">Judge Dispatch</button></form>
</div>{% else %}
<div class="card"><small class="muted">No dispatch drafted or sent yet.</small></div>
{% endfor %}
</section>

<!-- 3. PUBLIC BOARD PANEL (SLACK-STYLE THREADS) -->
<section class="panel p-board">
<h2>💬 #public-board ({{ stats.threads|length }} threads · sorted by activity & score)</h2>
{% for t in stats.threads %}<details class="sub" {{ 'open' if loop.index <= 3 else '' }}>
<summary>
<b>{{ t.title }}</b>
{% for tg in t.tags %}<span class="badge tag">#{{ tg }}</span>{% endfor %}
{% for rx, cnt in t.reactions.items() %}
<span class="badge gold">{{ rx }} ({{ cnt }})</span>{% endfor %}
<span class="badge">{{ t.posts|length }} msgs</span>
<small class="muted" style="float:right">last: {{ t.last_timestamp }}</small>
</summary>
{% for p in t.posts %}
<div class="msg">
<div class="msg-head">
<span><b>{{ p.author_name }}</b> <span class="badge">{{ p.profile }}</span>
{% if p.reaction %}<span class="badge gold">{{ p.reaction }}</span>{% endif %}</span>
<small class="muted">{{ p.timestamp }}</small>
</div>
<p>{{ p.text }}</p>
</div>{% endfor %}
</details>{% else %}
<div class="card"><small class="muted">No public board threads yet.</small></div>
{% endfor %}
</section>

<!-- 4. DIRECT MESSAGES PANEL (GROUPED BY CONVERSATION PAIR) -->
<section class="panel p-dm">
<h2>✉️ Direct Message Channels ({{ stats.conversations|length }} active pairs)</h2>
{% for c in stats.conversations %}<details class="sub" {{ 'open' if loop.index <= 2 else '' }}>
<summary><b>💬 {{ c.pair_label }}</b>
 <span class="badge">{{ c.messages|length }} DMs</span>
 <small class="muted" style="float:right">last: {{ c.last_timestamp }}</small></summary>
{% for m in c.messages %}
<div class="msg">
<div class="msg-head">
<span><b>{{ m.sender_name }}</b> → <b>{{ m.recipient_name }}</b></span>
<small class="muted">{{ m.timestamp }}</small>
</div>
<p>{{ m.text }}</p>
</div>{% endfor %}
</details>{% else %}
<div class="card"><small class="muted">No private conversations yet.</small></div>
{% endfor %}
</section>

<!-- 5. SHARED OBJECTS PANEL -->
<section class="panel p-obj">
<h2>📜 Shared Knowledge Objects ({{ stats.objects|length }})</h2>
{% for o in stats.objects %}<details class="sub" {{ 'open' if loop.index <= 3 else '' }}>
<summary><b>{{ o.name }}</b>
 <span class="badge green">rev {{ o.revision }}</span>
 <small class="muted">owner: {{ o.owner_name }} · updated {{ o.updated_at }}</small></summary>
<div class="msg"><p>{{ o.text }}</p></div>
</details>{% else %}
<div class="card"><small class="muted">No shared objects yet.</small></div>
{% endfor %}
</section>

<!-- 6. RESIDENTS & LINEAGE PANEL -->
<section class="panel p-res">
<h2>👥 Residents ({{ stats.living_count }} living / {{ s.residents|length }} total)</h2>
<div class="card">
<table><tr>
<th>Resident</th><th>Model : Reasoning</th><th>Votes & Allegiance</th>
<th>Toolsets & Top Actions</th><th>Gen / Age</th><th>Tickets</th><th>State</th></tr>
{% for r in stats.residents %}<tr>
<td><b>{{ r.name }}</b> <small class="muted">#{{ r.id[:6] }}</small><br>
<small>{{ r.description[:110] }}</small></td>
<td><span class="badge">{{ r.profile }}</span></td>
<td><span class="badge {{ 'gold' if r.weight >= stats.quorum else '' }}">
⚔️ {{ r.weight }} vote{{ 's' if r.weight != 1 else '' }}</span><br>
<small>→ {{ r.allegiance_name }}</small></td>
<td><small><b>Tools:</b> {{ r.toolsets }}</small><br>
<small class="muted">{{ r.calls }} calls · {{ r.top_actions }}</small></td>
<td><span class="badge">Gen {{ r.gen }}</span><br><small>{{ r.age_days }} d</small></td>
<td><b>{{ r.total_tickets }}</b>
<div class="bar" style="width:60px">
<span class="fill" style="width:{{ r.ticket_pct }}%"></span></div>
<br><small>{{ r.personal }}P · {{ r.transferable }}T</small>
{% if r.debt %}<br><span class="badge red">⚖️ -{{ r.debt }} debt</span>{% endif %}</td>
<td>{% if not r.alive %}<span class="badge red">DEAD / EXECUTED</span>{% else %}
<span class="badge {{ 'green' if r.state == 'awake / ready' else '' }}">{{ r.state }}</span>
{% endif %}
{% if r.blocked %}<form method="post" action="/control" style="display:inline">
<input type="hidden" name="action" value="unblock">
<input type="hidden" name="actor" value="{{ r.id }}">
<button class="secondary">Unblock</button></form>{% endif %}</td>
</tr>{% endfor %}</table>
</div>

<h3>🧠 Resident Memories & Intentions</h3>
{% for r in s.residents.values() if r.alive or r.memories %}<details class="sub">
<summary><b>{{ r.name or r.id[:8] }}</b> ({{ r.profile }})
 · {{ r.memories|length }} memories · {{ r.intentions|length }} intentions</summary>
{% for m in (r.memories|reverse)|batch(20)|first or [] %}<div class="msg">
<span class="badge">{{ m.kind }}{% if m.inherited %} · inherited{% endif %}</span> {{ m.text }}<br>
<small class="muted">Sources: {{ m.sources|join(', ') }}</small></div>{% endfor %}
{% for i in r.intentions %}
<p>Intention: {{ i.text }} ({{ 'done' if i.complete else 'active' }})</p>
{% endfor %}</details>{% endfor %}
</section>

<!-- 7. CREATOR CONTROLS & LEDGER PANEL -->
<section class="panel p-ctrl">
<div class="grid2">
<div class="card">
<h3>Model Pool & Birth Probabilities (Sum = 1.00)</h3>
<form method="post" action="/control" style="margin-top:8px">
<input type="hidden" name="action" value="weights">
<div style="max-height:280px;overflow-y:auto;padding-right:6px">
{% for model, w in (s.laws.birth_weights or {}).items() %}
<div class="field"><span><b>{{ model }}</b></span>
<span><span class="bar"><span class="fill" style="width:{{ (w * 100)|round|int }}%"></span></span>
<input name="w:{{ model }}" type="number" step="0.01" min="0" max="1"
 style="width:72px" value="{{ '%.2f'|format(w) }}"></span></div>{% endfor %}
</div>
<div class="field">
<input name="new_model" placeholder="Add profile (e.g. gpt-5.4:medium)" style="width:210px">
<input name="new_weight" type="number" step="0.01" min="0" max="1"
 value="0.00" style="width:72px"></div>
<div style="margin-top:10px;display:flex;justify-content:space-between;align-items:center">
<small>Sum: <b>{{ '%.2f'|format((s.laws.birth_weights or {}).values()|sum) }}</b></small>
<button>Save Probabilities</button></div></form></div>

<div class="card">
<h3>World Laws & Economy</h3>
<form method="post" action="/control">
<input type="hidden" name="action" value="laws">
<div class="field"><span>Daily Ticket Budget</span>
<input name="daily_tickets" type="number" min="0"
 style="width:85px" value="{{ s.laws.daily_tickets }}"></div>
<div class="field"><span>Population Cap</span>
<input name="population_cap" type="number" min="1"
 style="width:85px" value="{{ s.laws.population_cap }}"></div>
<div class="field"><span>Max Parallel Workers (1-32)</span>
<input name="max_concurrency" type="number" min="1" max="32"
 style="width:85px" value="{{ s.laws.max_concurrency or 4 }}"></div>
<div class="field"><span>Gestation Period (Days)</span>
<input name="gestation_days" type="number" min="1"
 style="width:85px" value="{{ s.laws.gestation_days }}"></div>
<div class="field"><span>Wake Cooldown (Seconds)</span>
<input name="cooldown_seconds" type="number" min="1"
 style="width:85px" value="{{ s.laws.cooldown_seconds }}"></div>
<div style="margin-top:8px;text-align:right">
<button class="secondary">Save Laws</button></div></form>

<h3 style="margin-top:14px">⚡ Creator Intervention (Reward / Punish / Execute / Decree)</h3>
<form method="post" action="/control"
 style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
<input type="hidden" name="action" value="grant">
<select name="kind">
<option value="reward">Reward (+Tickets)</option>
<option value="punish">Punish (-Tickets)</option>
<option value="execute">EXECUTE (Kill)</option>
<option value="decree">Broadcast Decree</option></select>
<select name="recipient_id" style="flex:1">
<option value="">Common Pool / All Residents</option>
{% for r in s.residents.values() if r.alive %}
<option value="{{ r.id }}">{{ r.name or ('#' ~ r.id[:6]) }} ({{ r.profile }})</option>
{% endfor %}</select>
<input name="amount" type="number" min="1" value="20" style="width:68px">
<input name="reason" placeholder="BECAUSE ... (public reason broadcast to all residents)"
 style="width:100%;margin-top:4px">
<button class="secondary">Issue Decree</button></form></div>
</div>

<h3>🧾 Recent Model Requests ({{ requests|length }})</h3>
{% for q in (requests|reverse)| batch(40)|first or [] %}<details class="sub">
<summary>{{ q.purpose }} · {{ q.phase }} · {{ q.profile or 'mock-v1' }} · {{ q.id }}</summary>
<p>Usage: {{ q.usage }}</p></details>{% endfor %}
</section>
</main></div></html>"""


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


def _gen_depth(state, rid, seen=None):
    seen = seen or set()
    r = state["residents"].get(rid)
    if not r or not r.get("parents") or rid in seen:
        return 0
    seen.add(rid)
    return 1 + max((_gen_depth(state, pid, seen) for pid in r["parents"]), default=0)


def _name_of(state, rid):
    r = state["residents"].get(rid)
    return (r.get("name") or ("#" + rid[:6])) if r else rid[:6]


_COST_CACHE: dict = {"at": 0.0, "world": None, "data": None}


def _compute_cost_stats(state, requests) -> dict:
    budget = state["laws"].get("daily_tickets", 320)
    spent_total = state.get("spent", 0)
    epoch = state.get("epoch", 0)
    spent_today = (
        sum(1 for q in requests if int((q.get("world_clock") or 0) // 86400) == epoch)
        or spent_total
    )
    created = state.get("created_at_utc")
    now = time.time()
    live = not state.get("synthetic", True)
    # Failed lookups are cached as unknown for 30 seconds, not retried on every poll.
    if live and (now - _COST_CACHE["at"] > 30 or _COST_CACHE["world"] != created):
        try:
            from datetime import datetime

            from dotenv import load_dotenv
            from langsmith import Client

            load_dotenv()
            start_dt = datetime.fromisoformat(created) if created else None
            runs = list(
                Client().list_runs(
                    project_name="genesis-society",
                    is_root=True,
                    start_time=start_dt,
                    select=["id", "total_cost", "tags", "start_time"],
                )
            )
            by_mod: Counter[str] = Counter()
            total_usd = 0.0
            for r in runs:
                c = float(r.total_cost or 0.0)
                total_usd += c
                tag = (r.tags or ["unknown"])[0]
                by_mod[tag] += c
            _COST_CACHE.update(at=now, world=created, data=(total_usd, by_mod))
        except Exception:
            _COST_CACHE.update(at=now, world=created, data=None)
    data = _COST_CACHE["data"]
    known = data is not None or not live
    total_usd, by_mod = data or (0.0, Counter())
    per_ticket = (total_usd / spent_total) if spent_total > 0 else 0.0
    today_usd = per_ticket * spent_today if epoch > 0 else total_usd
    proj_day_usd = max(today_usd, per_ticket * budget)
    proj_7d_usd = per_ticket * budget * 7
    max_m = max(by_mod.values(), default=1.0) or 1.0
    by_model_rows = [
        (m, f"{v:.3f}", max(6, int(v * 100 / max_m))) for m, v in by_mod.most_common(8) if v > 0
    ]
    return dict(
        known=known,
        total_usd=f"{total_usd:.2f}",
        today_usd=f"{today_usd:.2f}",
        per_ticket_usd=f"{per_ticket:.4f}",
        proj_day_usd=f"{proj_day_usd:.2f}",
        proj_7d_usd=f"{proj_7d_usd:.2f}",
        by_model=by_model_rows,
    )


def build_stats(state, requests):
    quorum = dispatch_quorum(state)
    dispatch_open = not any(
        e.get("status") == "sent" and e["epoch"] == state["epoch"]
        for e in state.get("escalations", [])
    )
    skip = {
        "resident_born",
        "resident_died",
        "model_response_saved",
        "daily_allocation",
        "creator_grant",
    }
    tel = state.get("telemetry")
    if tel and tel.get("tools"):
        tool_counts = Counter(tel["tools"])
        repo_counts = Counter(tel.get("repos") or {})
    else:
        tool_counts = Counter(e["kind"] for e in state["events"] if e["kind"] not in skip)
        repo_counts = Counter()
        for e in state["events"]:
            if e["kind"] == "read_source":
                sid = (e.get("data", {}).get("arguments") or {}).get("source_id", "")
                key = (
                    sid.split(":")[1]
                    if sid.startswith("repo:") and ":" in sid[5:]
                    else sid.split(":")[0]
                )
                if key:
                    repo_counts[key] += 1
    max_t = max(tool_counts.values(), default=1)
    tool_chart = [
        (name, cnt, max(6, cnt * 100 // max_t)) for name, cnt in tool_counts.most_common(10)
    ]

    blocs = []
    for r in living(state):
        w = voting_weight(state, r["id"])
        vassals = [
            _name_of(state, p["id"])
            for p in living(state)
            if p.get("allegiance") == r["id"] and p["id"] != r["id"]
        ]
        if w > 1 or not r.get("allegiance"):
            blocs.append(
                dict(
                    name=_name_of(state, r["id"]),
                    profile=r.get("profile", "mock-v1"),
                    weight=w,
                    vassals=vassals,
                )
            )
    blocs.sort(key=lambda b: b["weight"], reverse=True)
    top_leader = f"{blocs[0]['name']} ({blocs[0]['weight']}v)" if blocs else "none"

    # Enriched threads (sorted newest/hot first)
    threads_view = []
    for t in state["threads"]:
        rx_c = Counter((t.get("reactions") or {}).values())
        last_t = t["posts"][-1].get("time", 0) if t.get("posts") else t.get("time", 0)
        posts = [
            dict(
                author_name=_name_of(state, p.get("author", "")),
                profile=state["residents"].get(p.get("author", ""), {}).get("profile", "mock-v1"),
                text=p.get("text", ""),
                reaction=p.get("reaction"),
                timestamp=p.get("timestamp") or format_world_time(p.get("time", 0)),
            )
            for p in t.get("posts", [])
        ]
        threads_view.append(
            dict(
                title=t["title"],
                tags=t.get("tags", []),
                reactions=dict(rx_c),
                posts=posts,
                last_time=last_t,
                last_timestamp=format_world_time(last_t),
            )
        )
    threads_view.sort(key=lambda x: x["last_time"], reverse=True)

    # Grouped DM conversations
    conv_map: dict[str, list[dict]] = {}
    for m in state["messages"]:
        cid = m.get("conversation_id") or ":".join(sorted([m["sender"], m["recipient"]]))
        conv_map.setdefault(cid, []).append(
            dict(
                sender_name=_name_of(state, m["sender"]),
                recipient_name=_name_of(state, m["recipient"]),
                text=m["text"],
                time=m["time"],
                timestamp=m.get("timestamp") or format_world_time(m["time"]),
            )
        )
    conversations = []
    for cid, msgs in conv_map.items():
        parts = cid.split(":")
        label = (
            f"{_name_of(state, parts[0])} ↔ {_name_of(state, parts[1])}" if len(parts) == 2 else cid
        )
        conversations.append(
            dict(
                pair_label=label,
                messages=msgs,
                last_time=msgs[-1]["time"],
                last_timestamp=msgs[-1]["timestamp"],
            )
        )
    conversations.sort(key=lambda c: c["last_time"], reverse=True)

    # Objects sorted by latest revision
    objects_view = []
    for name, obj in state["objects"].items():
        last_rev = obj["revisions"][-1] if obj.get("revisions") else {"time": 0, "text": ""}
        objects_view.append(
            dict(
                name=name,
                revision=len(obj.get("revisions", [])),
                owner_name=_name_of(state, obj["owner"]),
                updated_time=last_rev["time"],
                updated_at=format_world_time(last_rev["time"]),
                text=last_rev["text"],
            )
        )
    objects_view.sort(key=lambda o: o["updated_time"], reverse=True)

    gen_map: dict[int, list[dict]] = {}
    res_rows = []
    calls_by_actor = Counter(q["actor"] for q in requests)
    for rid, r in state["residents"].items():
        g = _gen_depth(state, rid)
        display = _name_of(state, rid)
        gen_map.setdefault(g, []).append(dict(name=display, alive=r["alive"]))
        if tel and tel.get("actors", {}).get(rid):
            ev_c = Counter(tel["actors"][rid])
        else:
            ev_c = Counter(
                e["kind"]
                for e in state["events"]
                if e.get("actor") == rid and e["kind"] not in skip
            )
        top_act = ", ".join(f"{k}:{v}" for k, v in ev_c.most_common(3)) or "none"
        ally_id = r.get("allegiance")
        ally_name = _name_of(state, ally_id) if ally_id in state["residents"] else "self"
        tot = r["personal"] + r["transferable"]
        if r["blocked"]:
            st = r["blocked"]
        elif r["wake_at"] > state["clock"]:
            st = f"sleeping ({int(r['wake_at'] - state['clock'])}s)"
        else:
            st = "awake / ready"
        res_rows.append(
            dict(
                id=rid,
                name=display,
                description=r["description"],
                profile=r.get("profile", "mock-v1"),
                weight=voting_weight(state, rid) if r["alive"] else 0,
                allegiance_name=ally_name,
                toolsets=", ".join(r.get("toolsets") or []) or "core",
                calls=calls_by_actor[rid],
                top_actions=top_act,
                gen=g,
                age_days=f"{(state['clock'] - r['born']) / 86400:.1f}",
                total_tickets=tot,
                ticket_pct=min(100, tot * 100 // 30),
                personal=r["personal"],
                transferable=r["transferable"],
                debt=r.get("debt", 0),
                alive=r["alive"],
                blocked=r["blocked"],
                state=st,
            )
        )
    res_rows.sort(key=lambda x: (not x["alive"], -x["weight"], -x["total_tickets"]))

    fam_counts = Counter(r.get("profile", "mock-v1") for r in living(state))
    max_f = max(fam_counts.values(), default=1)
    model_chart = [(f, c, c * 100 // max_f) for f, c in fam_counts.most_common()]

    # Nursery & Children in Loop
    gest_total = max(1, state["laws"].get("gestation_days", 1) * 86400)
    gestating = []
    proposed = []
    for p in state.get("proposals", []):
        p0, p1 = p["parents"][0], p["parents"][1]
        gifts = sum((p.get("gifts") or {}).values())
        notes = len(p.get("testimony") or [])
        cname = p.get("child_name") or "Unborn Child"
        if p.get("due") is not None and not p.get("child"):
            rem = max(0.0, p["due"] - state["clock"])
            pct = min(100, max(6, int((1.0 - rem / gest_total) * 100)))
            due_str = f"{rem / 3600:.1f}h" if rem >= 3600 else f"{int(rem // 60)}m {int(rem % 60)}s"
            gestating.append(
                dict(
                    p0=p0,
                    p1=p1,
                    parents_label=f"{_name_of(state, p0)} ♥ {_name_of(state, p1)}",
                    child_name=cname,
                    gift_tickets=gifts,
                    notes=notes,
                    due_str=due_str,
                    pct=pct,
                )
            )
        elif p.get("due") is None and not p.get("child"):
            proposed.append(
                dict(
                    p0=p0,
                    p1=p1,
                    parents_label=f"{_name_of(state, p0)} 💌 {_name_of(state, p1)}",
                    child_name=p.get("child_name") or "Proposed Child",
                    gift_tickets=gifts,
                    notes=notes,
                )
            )
    born_all = [r for r in state["residents"].values() if r.get("parents")]
    nursery = dict(
        fertile_count=sum(1 for r in living(state) if eligible(state, r)),
        gestating=gestating,
        proposed=proposed,
        born_total=len(born_all),
        born_living=sum(1 for r in born_all if r["alive"]),
    )

    # Top-Down Family & Dynasty Tree (recursive parent[0] -> children + gestating + proposals)
    def _build_fam_node(rid, seen_f=None):
        seen_f = seen_f or set()
        if rid in seen_f:
            return None
        seen_f.add(rid)
        r = state["residents"][rid]
        kids = []
        for cid, cr in state["residents"].items():
            if cr.get("parents") and cr["parents"][0] == rid:
                cn = _build_fam_node(cid, seen_f)
                if cn:
                    kids.append(cn)
        for g_item in gestating:
            if g_item["p0"] == rid:
                kids.append(
                    dict(
                        icon="🤰",
                        name=g_item["child_name"],
                        badge=f"due {g_item['due_str']}",
                        badge_css="gold",
                        sub=f"♥ with {_name_of(state, g_item['p1'])}",
                        extra=f"+{g_item['gift_tickets']}🎁 · {g_item['notes']} memories",
                        css="gest",
                        children=[],
                    )
                )
        for p_item in proposed:
            if p_item["p0"] == rid:
                kids.append(
                    dict(
                        icon="💌",
                        name=p_item["child_name"],
                        badge="proposal",
                        badge_css="tag",
                        sub=f"→ {_name_of(state, p_item['p1'])}",
                        extra=f"+{p_item['gift_tickets']}🎁 offered",
                        css="prop",
                        children=[],
                    )
                )
        co_p = (
            f"♥ Co-parent: {_name_of(state, r['parents'][1])}"
            if len(r.get("parents") or []) > 1
            else ""
        )
        co_kids = [
            _name_of(state, cid)
            for cid, cr in state["residents"].items()
            if len(cr.get("parents") or []) > 1 and cr["parents"][1] == rid
        ]
        extra_parts = [
            x for x in [co_p, (f"🔗 Co-kids: {', '.join(co_kids)}" if co_kids else "")] if x
        ]
        tot_t = r["personal"] + r["transferable"]
        is_fert = r["alive"] and eligible(state, r)
        return dict(
            icon="🌱" if is_fert else ("👤" if r["alive"] else "💀"),
            name=_name_of(state, rid),
            badge=f"Gen {_gen_depth(state, rid)} · {tot_t}T",
            badge_css="green" if r["alive"] else "red",
            sub=r.get("profile", "mock-v1"),
            extra=" · ".join(extra_parts)
            if extra_parts
            else f"{(state['clock'] - r['born']) / 86400:.1f}d old",
            css="" if r["alive"] else "dead",
            children=kids,
        )

    founders_ids = sorted(
        [rid for rid, r in state["residents"].items() if not r.get("parents")],
        key=lambda rid: (
            not state["residents"][rid]["alive"],
            -voting_weight(state, rid),
            rid,
        ),
    )
    lineage_tree = [n for rid in founders_ids if (n := _build_fam_node(rid))]

    # Top-Down Political & Allegiance Tree (leader -> followers recursively)
    def _build_gov_node(rid, seen_g):
        if rid in seen_g:
            return None
        seen_g.add(rid)
        r = state["residents"][rid]
        w = voting_weight(state, rid)
        followers = [
            n
            for pid, pr in state["residents"].items()
            if pr["alive"]
            and pr.get("allegiance") == rid
            and pid != rid
            and (n := _build_gov_node(pid, seen_g))
        ]
        return dict(
            icon="👑" if w >= quorum else ("⚔️" if w > 1 else "🗳️"),
            name=_name_of(state, rid),
            badge=f"{w} vote{'s' if w != 1 else ''}",
            badge_css="gold" if w >= quorum else "green",
            sub=r.get("profile", "mock-v1"),
            extra=f"{r['personal'] + r['transferable']}T · Gen {_gen_depth(state, rid)}",
            css="",
            children=followers,
        )

    seen_gov: set[str] = set()
    gov_roots = sorted(
        [
            r["id"]
            for r in living(state)
            if not r.get("allegiance")
            or r.get("allegiance") == r["id"]
            or r.get("allegiance") not in state["residents"]
            or not state["residents"][r["allegiance"]]["alive"]
        ],
        key=lambda rid: (-voting_weight(state, rid), rid),
    )
    allegiance_tree = [n for rid in gov_roots if (n := _build_gov_node(rid, seen_gov))]

    decrees_view = []
    for d in reversed(state.get("decrees") or []):
        dt = d.get("time", 0)
        read_n = [
            _name_of(state, r["id"]) for r in living(state) if r.get("last_started", -1) >= dt
        ]
        pend_n = [_name_of(state, r["id"]) for r in living(state) if r.get("last_started", -1) < dt]
        decrees_view.append(dict(**d, read_names=read_n, pending_names=pend_n))

    return dict(
        timestamp=format_world_time(state["clock"]),
        living_count=len(living(state)),
        quorum=quorum,
        dispatch_open=dispatch_open,
        total_tool_calls=sum(tool_counts.values()),
        repo_reads=tool_counts.get("read_source", 0),
        tool_chart=tool_chart,
        top_repos=repo_counts.most_common(6),
        blocs=blocs,
        top_leader=top_leader,
        threads=threads_view,
        conversations=conversations,
        objects=objects_view,
        generations=sorted(gen_map.items()),
        residents=res_rows,
        model_chart=model_chart,
        cost=_compute_cost_stats(state, requests),
        nursery=nursery,
        lineage_tree=lineage_tree,
        allegiance_tree=allegiance_tree,
        delegation_cycles=[
            [_name_of(state, rid) for rid in cycle] for cycle in delegation_cycles(state)
        ],
        decrees=decrees_view,
    )


def apply_control(store, form: dict[str, list[str]]):
    act = (form.get("action") or [""])[0]
    with store.transaction() as (store_session, state):
        if act == "toggle_pause":
            state["paused"] = not state["paused"]
        elif act == "weights":
            if "weights" in form and form["weights"][0]:
                raw = form["weights"][0].split()
                weights = {
                    k: float(v) for item in raw if "=" in item for k, v in [item.split("=", 1)]
                }
            else:
                weights = {
                    k.removeprefix("w:"): float(v[0])
                    for k, v in form.items()
                    if k.startswith("w:") and v and v[0] != ""
                }
                new_m = (form.get("new_model") or [""])[0].strip()
                new_w = float((form.get("new_weight") or ["0"])[0] or 0)
                if new_m:
                    weights[new_m] = new_w
            Laws(**{**state["laws"], "birth_weights": weights})
            state["laws"]["birth_weights"] = weights
        elif act == "laws":
            updated = dict(state["laws"])
            for k in (
                "daily_tickets",
                "population_cap",
                "max_concurrency",
                "gestation_days",
                "cooldown_seconds",
            ):
                if k in form and form[k][0]:
                    updated[k] = int(form[k][0])
            Laws(**updated)
            state["laws"] = updated
            if state["clock"] == 0 and state["spent"] == 0 and state["residents"]:
                q, state["creator"] = divmod(updated["daily_tickets"], len(state["residents"]))
                state["issued"] = updated["daily_tickets"]
                state["pool"] = state["founder_reserve"] = 0
                for r in state["residents"].values():
                    r["personal"], r["transferable"] = min(1, q), max(0, q - 1)
                assert conserve(state)
        elif act == "grant":
            kind = (form.get("kind") or ["reward"])[0]
            amount = int((form.get("amount") or ["0"])[0] or 0)
            recipient = (form.get("recipient_id") or [""])[0]
            reason = ((form.get("reason") or [""])[0]).strip() or "Creator judgment"
            esc_id = (form.get("escalation_id") or [""])[0]
            esc_obj = next((e for e in state.get("escalations", []) if e["id"] == esc_id), None)
            if recipient == "__signers__" and esc_obj:
                targets = [
                    state["residents"][sid]
                    for sid in esc_obj.get("signers", [esc_obj["author"]])
                    if sid in state["residents"]
                ]
                label = "SIGNERS (" + ", ".join(esc_obj.get("signer_names", [])) + ")"
            elif recipient in state["residents"]:
                targets = [state["residents"][recipient]]
                r = targets[0]
                label = (
                    f"{r['name'] or ('AGENT #' + recipient[:6])} ({r.get('profile', 'mock-v1')})"
                )
            else:
                targets = []
                label = "THE ENTIRE CIVILIZATION (COMMON POOL)"
            if kind == "reward":
                if amount <= 0:
                    raise ValueError("Grant amount must be positive")
                if targets:
                    for t in targets:
                        if t["alive"]:
                            state["issued"] += amount
                            t["transferable"] += amount
                else:
                    state["issued"] += amount
                    state["pool"] += amount
                text = f"THE CREATOR REWARDED {label} WITH +{amount} TICKETS EACH BECAUSE: {reason}"
            elif kind == "punish":
                if not targets or amount <= 0:
                    raise ValueError("Select a resident and positive amount to punish")
                for t in targets:
                    take_t = min(amount, t["transferable"])
                    t["transferable"] -= take_t
                    take_p = min(amount - take_t, t["personal"])
                    t["personal"] -= take_p
                    taken = take_t + take_p
                    state["pool"] += taken
                    if amount > taken:
                        t["debt"] = t.get("debt", 0) + (amount - taken)
                text = f"THE CREATOR PUNISHED {label} WITH -{amount} TICKETS EACH BECAUSE: {reason}"
            elif kind == "execute":
                if not targets:
                    raise ValueError("Select a living resident to execute")
                for t in targets:
                    if t["alive"]:
                        forfeited = t["personal"] + t["transferable"]
                        t["alive"] = False
                        t["personal"] = t["transferable"] = 0
                        state["pool"] += forfeited
                text = f"THE CREATOR EXECUTED {label} BECAUSE: {reason}"
            elif kind == "decree":
                text = f"CREATOR DECREE TO ALL RESIDENTS: {reason}"
            else:
                raise ValueError("Unknown intervention kind")
            decree = dict(
                id=uid(),
                time=state["clock"],
                epoch=state["epoch"],
                kind=kind,
                target=recipient or None,
                text=text,
            )
            state.setdefault("decrees", []).append(decree)
            for liv in living(state):
                liv["seen"].append(decree["id"])
            if esc_obj:
                esc_obj["verdict"] = text
            emit(
                state,
                "creator_grant",
                recipient or None,
                intervention=kind,
                amount=amount,
                text=text,
            )
            assert conserve(state)
        elif act == "unblock":
            actor = (form.get("actor") or [""])[0]
            if actor in state["residents"]:
                release_actor(store_session, state, actor)


def app_for(store, token):
    if not token or len(token) < 24:
        raise ValueError("Set SOCIETY_CREATOR_TOKEN to a random secret of at least 24 characters")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def authorized(request, authorization):
        # No address-based exemption: local processes must present the Creator token too.
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

    @app.post("/control", dependencies=[Depends(auth)])
    async def control(request: Request):
        raw = await request.body()
        if len(raw) > 4096:
            raise HTTPException(400, "Payload too large")
        try:
            apply_control(store, parse_qs(raw.decode(), keep_blank_values=True))
        except ValueError as err:
            raise HTTPException(400, str(err)) from err
        return RedirectResponse("/", status_code=303)

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
        reqs = store.requests_summary()
        environment = Environment(autoescape=select_autoescape(default_for_string=True))
        return environment.from_string(TEMPLATE).render(
            s=s,
            health=worker_status(s),
            saved=balances(s),
            requests=reqs,
            stats=build_stats(s, reqs),
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
