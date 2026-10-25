"""Deterministic world rules; model choices enter only through authorized tools."""

import random
from copy import deepcopy

from sqlalchemy.orm import Session

from .config import Laws
from .storage import World, uid, utcnow

DAY = 86400
COUNCIL = ("Historian", "Strategist", "Skeptic", "Scorer")
TOOLSETS = {
    "github": ("list_sources", "read_source"),
    "knowledge": ("write_object", "read_object", "read_own_trace"),
    "economy": ("inspect_resources", "transfer_resources"),
    "family": ("propose_child", "consent_child"),
}


def draw_profile(state, rng):
    if state.get("synthetic", True):
        return "mock-v1"
    weights = state["laws"].get("birth_weights") or {"mock-v1": 1}
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def emit(state, kind, actor=None, **data):
    if not state.get("synthetic", True):
        skip = {
            "resident_born",
            "resident_died",
            "model_response_saved",
            "daily_allocation",
            "creator_grant",
        }
        if kind not in skip:
            tel = state.setdefault("telemetry", {"tools": {}, "repos": {}, "actors": {}})
            tel["tools"][kind] = tel["tools"].get(kind, 0) + 1
            if actor:
                act_map = tel["actors"].setdefault(actor, {})
                act_map[kind] = act_map.get(kind, 0) + 1
            if kind == "read_source":
                sid = (data.get("arguments") or {}).get("source_id", "")
                key = (
                    sid.split(":")[1]
                    if sid.startswith("repo:") and ":" in sid[5:]
                    else sid.split(":")[0]
                )
                if key:
                    tel["repos"][key] = tel["repos"].get(key, 0) + 1
        if isinstance(data.get("result"), dict):
            data = dict(
                data,
                result={
                    k: v for k, v in data["result"].items() if k not in ("text", "items", "objects")
                },
            )
    event = dict(id=uid(), time=state["clock"], kind=kind, actor=actor, data=data)
    state["events"].append(event)
    if not state.get("synthetic", True) and len(state["events"]) > 1500:
        state["events"] = state["events"][-1000:]
    if actor in state["residents"]:
        seen = state["residents"][actor]["seen"]
        seen.append(event["id"])
        if not state.get("synthetic", True) and len(seen) > 2500:
            state["residents"][actor]["seen"] = list(dict.fromkeys(seen))[-2000:]
    return event["id"]


def new_resident(
    state, *, age_days, lifespan_days, name="", parents=None, identity=None, profile="mock-v1"
):
    rid = identity or uid()
    state["residents"][rid] = dict(
        id=rid,
        name=name,
        description="",
        born=state["clock"] - age_days * DAY,
        lifespan=lifespan_days * DAY,
        alive=True,
        personal=0,
        transferable=0,
        wake_at=state["clock"],
        minimum_tickets=2,
        dm_wake=False,
        intentions=[],
        memories=[],
        seen=[],
        delivered=[],
        parents=parents or [],
        activation=None,
        last_started=-1,
        blocked=None,
        profile=profile,
        toolsets=[],
        allegiance=None,
    )
    emit(state, "resident_born", rid, parents=parents or [], profile=profile)
    return rid


def initialize(store, laws: Laws, *, demo=True, seed=42):
    rng = random.Random(seed)
    state = dict(
        name="synthetic-demo" if demo else "society",
        synthetic=demo,
        clock=0.0,
        epoch=0,
        paused=True,
        laws=laws.model_dump(),
        residents={},
        threads=[],
        messages=[],
        objects={},
        events=[],
        effects={},
        proposals=[],
        escalations=[],
        decrees=[],
        council={name: dict(id=uid(), memories=[]) for name in COUNCIL},
        council_chat=[],
        council_jobs=[],
        council_receipts=[],
        created_at_utc=utcnow().isoformat(),
        issued=laws.daily_tickets,
        spent=0,
        pool=0,
        creator=0,
        rotation=0,
        founder_reserve=0,
        founders=[],
        health={},
    )
    q, state["creator"] = divmod(laws.daily_tickets, laws.founders)
    for _ in range(laws.founders):
        f = dict(
            id=uid(),
            due=0 if demo else rng.uniform(0, laws.founder_window_seconds),
            age=rng.randint(laws.founder_age_min_days, laws.founder_age_max_days),
            lifespan=rng.randint(laws.lifespan_min_days, laws.lifespan_max_days),
            tickets=q,
            profile=draw_profile(state, rng),
        )
        state["founders"].append(f)
        state["founder_reserve"] += q
    tick(state, 0)
    if demo:
        for index, r in enumerate(state["residents"].values(), 1):
            r["name"] = f"Fixture {index}"
    with Session(store.engine) as session, session.begin():
        if session.get(World, 1):
            raise ValueError("World already exists; initialization refused")
        session.add(World(id=1, data=state))
    return state


def living(state):
    return [r for r in state["residents"].values() if r["alive"]]


def format_world_time(seconds: float) -> str:
    s = max(0, int(seconds))
    d, rem = divmod(s, DAY)
    h, rem = divmod(rem, 3600)
    m, sec = divmod(rem, 60)
    return f"Day {d} · {h:02d}:{m:02d}:{sec:02d}"


def _transitively_follows(state, citizen_id: str, targets: set[str]) -> bool:
    cur = citizen_id
    visited: set[str] = set()
    while cur and cur not in visited and len(visited) < 16:
        if cur in targets:
            return True
        visited.add(cur)
        r = state["residents"].get(cur)
        if not r or not r["alive"]:
            return False
        cur = r.get("allegiance")
    return False


def represented_by(state, signers):
    s_set = set(signers)
    return {p["id"] for p in living(state) if _transitively_follows(state, p["id"], s_set)}


def voting_weight(state, rid):
    return len(represented_by(state, [rid]))


def dispatch_quorum(state):
    n = len(living(state))
    return min(2, max(1, n)) if state.get("synthetic", True) else min(24, max(3, (n + 2) // 3))


def balances(state):
    return sum(r["personal"] + r["transferable"] for r in state["residents"].values())


def conserve(state):
    return state["issued"] == (
        state["spent"]
        + balances(state)
        + state["pool"]
        + state["creator"]
        + state["founder_reserve"]
    )


def allocate(state):
    residents = sorted(living(state), key=lambda r: r["id"])
    production = state["laws"]["daily_tickets"]
    state["issued"] += production
    if not residents:
        state["creator"] += production
        return
    indebted = {r["id"] for r in residents if r.get("debt", 0) > 0}
    q, remainder = divmod(production, len(residents))
    state["creator"] += remainder
    for r in residents:
        r["personal"] += min(1, q)
        r["transferable"] += max(0, q - 1)
        debt = r.get("debt", 0)
        if debt > 0:
            take_t = min(debt, r["transferable"])
            r["transferable"] -= take_t
            debt -= take_t
            take_p = min(debt, r["personal"])
            r["personal"] -= take_p
            debt -= take_p
            r["debt"] = debt
            state["pool"] += take_t + take_p
    pool_recipients = [r for r in residents if r["id"] not in indebted] or residents
    share, remainder = divmod(state["pool"], len(pool_recipients))
    for r in pool_recipients:
        r["transferable"] += share
    for index in range(remainder):
        pool_recipients[(state["rotation"] + index) % len(pool_recipients)]["transferable"] += 1
    state["rotation"] = (state["rotation"] + remainder) % len(pool_recipients)
    state["pool"] = 0
    emit(state, "daily_allocation", tickets=production)


def eligible(state, resident):
    age = state["clock"] - resident["born"]
    return (
        resident["alive"]
        and age >= state["laws"]["reproduction_min_days"] * DAY
        and age <= resident["lifespan"] * state["laws"]["reproduction_fraction"]
    )


def lifecycle(state):
    for r in living(state):
        if state["clock"] - r["born"] >= r["lifespan"]:
            r["alive"] = False
            state["pool"] += r["personal"] + r["transferable"]
            r["personal"] = r["transferable"] = 0
            emit(state, "resident_died", r["id"])
    for f in sorted(state["founders"], key=lambda f: (f["due"], f["id"])):
        if f["id"] not in state["residents"] and f["due"] <= state["clock"]:
            rid = new_resident(
                state,
                age_days=f["age"],
                lifespan_days=f["lifespan"],
                identity=f["id"],
                profile=f.get("profile", "mock-v1"),
            )
            r = state["residents"][rid]
            r["personal"], r["transferable"] = min(1, f["tickets"]), max(0, f["tickets"] - 1)
            state["founder_reserve"] -= f["tickets"]
    for proposal in state["proposals"]:
        if (
            proposal.get("due") is not None
            and not proposal.get("child")
            and proposal["due"] <= state["clock"]
            and len(living(state)) < state["laws"]["population_cap"]
        ):
            # Parents consented earlier. Never re-check their age or survival here.
            rng = random.Random(proposal["id"])
            lifespan_days = rng.randint(
                state["laws"]["lifespan_min_days"], state["laws"]["lifespan_max_days"]
            )
            child = new_resident(
                state,
                age_days=0,
                lifespan_days=lifespan_days,
                name=proposal.get("child_name", ""),
                parents=proposal["parents"],
                profile=draw_profile(state, rng),
            )
            proposal["child"] = child
            for pid, amount in (proposal.get("gifts") or {}).items():
                parent = state["residents"].get(pid)
                if parent and parent["alive"] and amount > 0:
                    actual = min(amount, parent["transferable"])
                    parent["transferable"] -= actual
                    state["residents"][child]["transferable"] += actual
            for testimony in proposal.get("testimony", []):
                state["residents"][child]["memories"].append(
                    dict(
                        id=uid(),
                        kind="belief",
                        text=testimony["text"],
                        sources=[testimony["id"]],
                        people=proposal["parents"],
                        time=state["clock"],
                        supersedes=None,
                        inherited=True,
                    )
                )
                inherited = state["residents"][child]["memories"][-1]
                state["residents"][child]["seen"].append(inherited["id"])


def tick(state, seconds):
    if seconds < 0:
        raise ValueError("World clock cannot move backwards")
    target = state["clock"] + seconds
    # Process boundaries chronologically, also for deterministic accelerated tests.
    # At a daily boundary, deaths happen before issuance and births after issuance.
    lifecycle(state)
    while state["clock"] < target:
        next_day = (state["epoch"] + 1) * DAY
        boundaries = [target, next_day]
        boundaries.extend(
            f["due"]
            for f in state["founders"]
            if f["id"] not in state["residents"] and f["due"] > state["clock"]
        )
        boundaries.extend(
            r["born"] + r["lifespan"]
            for r in living(state)
            if r["born"] + r["lifespan"] > state["clock"]
        )
        boundaries.extend(
            p["due"]
            for p in state["proposals"]
            if p.get("due") is not None and not p.get("child") and p["due"] > state["clock"]
        )
        state["clock"] = min(boundaries)
        if state["clock"] == next_day:
            for r in living(state):
                if state["clock"] - r["born"] >= r["lifespan"]:
                    r["alive"] = False
                    state["pool"] += r["personal"] + r["transferable"]
                    r["personal"] = r["transferable"] = 0
                    emit(state, "resident_died", r["id"])
            allocate(state)
            state["epoch"] += 1
        lifecycle(state)
    assert conserve(state), "Ticket conservation violated"


def _known_people(state, rid):
    if state.get("synthetic", True):
        return living(state)
    r = state["residents"][rid]
    alive_map = {p["id"]: p for p in living(state)}
    known_ids: list[str] = [rid]
    # 1. Family & direct allegiance ties
    for pid in r.get("parents", ()):
        if pid in alive_map:
            known_ids.append(pid)
    for p in alive_map.values():
        if rid in p.get("parents", ()) or p.get("allegiance") == rid:
            known_ids.append(p["id"])
    if r.get("allegiance") in alive_map:
        known_ids.append(r["allegiance"])
    # 2. Direct personal interactions (memories, proposals, DMs)
    for m in r.get("memories", ()):
        for pid in m.get("people", ()):
            if pid in alive_map:
                known_ids.append(pid)
    for prop in state.get("proposals", ()):
        if rid in prop.get("parents", ()):
            for pid in prop["parents"]:
                if pid in alive_map:
                    known_ids.append(pid)
    for msg in state.get("messages", ()):
        if msg.get("sender") == rid and msg.get("recipient") in alive_map:
            known_ids.append(msg["recipient"])
        elif msg.get("recipient") == rid and msg.get("sender") in alive_map:
            known_ids.append(msg["sender"])
    # 3. Prominent public figures (leaders with >1 vote, top 4)
    leaders = sorted(
        (p["id"] for p in alive_map.values() if voting_weight(state, p["id"]) > 1),
        key=lambda pid: (-voting_weight(state, pid), pid),
    )[:4]
    known_ids.extend(leaders)
    unique = list(dict.fromkeys(known_ids))
    # 4. Small local neighborhood (up to 6 total) if newly born/isolated, max 12 overall
    if len(unique) < 6:
        ring = sorted(alive_map, key=lambda pid: (pid < rid, pid))
        for pid in ring:
            if pid not in unique:
                unique.append(pid)
            if len(unique) >= 6:
                break
    return [alive_map[pid] for pid in unique[:12] if pid in alive_map]


def resident_context(state, rid):
    r = state["residents"][rid]
    return dict(
        id=rid,
        name=r["name"],
        description=r["description"],
        profile=r.get("profile", "mock-v1"),
        allegiance=r.get("allegiance"),
        voting_weight=voting_weight(state, rid),
        dispatch_quorum_required=dispatch_quorum(state),
        active_toolsets=list(r.get("toolsets", [])),
        available_toolsets={k: list(v) for k, v in TOOLSETS.items()},
        parents=list(r["parents"]),
        children=[c["id"] for c in living(state) if rid in c["parents"]],
        world_time_seconds=state["clock"],
        world_timestamp=format_world_time(state["clock"]),
        age_days=(state["clock"] - r["born"]) / DAY,
        day_seconds=DAY,
        intentions=deepcopy(r["intentions"]),
        public_objects=[
            dict(
                name=k,
                revision=len(v["revisions"]),
                owner=v["owner"],
                updated_at=format_world_time(v["revisions"][-1]["time"])
                if v.get("revisions")
                else "Day 0 · 00:00:00",
            )
            for k, v in sorted(
                state["objects"].items(),
                key=lambda item: (
                    item[1]["revisions"][-1]["time"] if item[1].get("revisions") else 0
                ),
                reverse=True,
            )[:15]
            if v["public"]
        ],
        people=[
            dict(
                id=p["id"],
                name=p["name"],
                description=p["description"][:160],
                profile=p.get("profile", "mock-v1"),
                allegiance=p.get("allegiance"),
                voting_weight=voting_weight(state, p["id"]),
            )
            for p in _known_people(state, rid)
        ],
        resources=dict(
            personal=r["personal"],
            transferable=r["transferable"],
            penalty_debt=r.get("debt", 0),
            daily_production=state["laws"]["daily_tickets"],
            living_population=len(living(state)),
            pending_births=sum(
                1 for p in state["proposals"] if p.get("due") is not None and not p.get("child")
            ),
            current_daily_share=state["laws"]["daily_tickets"] // max(1, len(living(state))),
            next_allocation=(state["epoch"] + 1) * DAY,
        ),
        laws={
            k: state["laws"][k]
            for k in ("daily_tickets", "population_cap", "gestation_days", "cooldown_seconds")
        },
        creator_decrees=deepcopy(state.get("decrees", [])[-8:]),
        daily_team_dispatch_available=not any(
            e.get("status") == "sent" and e["epoch"] == state["epoch"]
            for e in state.get("escalations", [])
        ),
        team_dispatches=deepcopy(state.get("escalations", [])[-6:]),
        proposals=[deepcopy(p) for p in state["proposals"] if rid in p["parents"]],
        explanation=(
            "One ticket pays for one model call, including technical summaries. "
            "Local tools and scheduling are free. Personal tickets (1/day) are spent "
            "first and cannot be gifted; transferable tickets can be saved, gifted to "
            "neighbors or children, or returned to the common pool. Your exact lifespan "
            "is unknown. Because the daily ticket pool (daily_production) is divided "
            "among all living residents, having more children without growing the "
            "economy reduces everyone's daily share. More tickets—and the Creator "
            "raising daily_tickets so your society has the resources to sustain more "
            "children and larger generations—ONLY come when the Creator is satisfied "
            "with your output and recognizes real value in your dispatches and shared "
            "work. You do not automatically know every citizen in a large population: "
            "'people' lists only your personal circle, public leaders, and immediate "
            "neighbors; meet others on the public board (board_read). Use use_toolset "
            "to load tool groups on demand (github, knowledge, economy, family). "
            "Governance is emergent: every resident starts with 1 vote, or may pledge "
            "allegiance to a trusted leader/king/council member via update_identity "
            "(delegating their voting weight until changed). Do NOT waste tickets doing "
            "micro PR reviews (review bots already do that); focus on higher-level product "
            "strategy, cross-service architecture, and bold ideas. Triangulate evidence: "
            "context:* is shared orientation and may be stale; repo:<service>:* owns code "
            "behavior/contracts on main; deployments:* owns desired environment config and "
            "SHAs but does not prove what is live. Never claim main or configured means "
            "deployed. Sending "
            "the daily dispatch via escalate_to_team is completely open in topic "
            "(compliments, criticism, topic proposals, innovations, improvements, or "
            "cultural/architectural reflections)—written in a casual-professional tone like "
            "buddies and colleagues talking in a cool tech company—and requires signers "
            "whose combined voting_weight reaches dispatch_quorum_required (1/3 of living "
            "population, min 3). All signers share the Creator's reward or punishment."
        ),
    )
