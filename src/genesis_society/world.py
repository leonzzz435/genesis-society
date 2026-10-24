"""Deterministic world rules; model choices enter only through authorized tools."""

import random
from copy import deepcopy

from sqlalchemy.orm import Session

from .config import Laws
from .storage import World, uid

DAY = 86400
COUNCIL = ("Historian", "Strategist", "Skeptic", "Scorer")


def emit(state, kind, actor=None, **data):
    event = dict(id=uid(), time=state["clock"], kind=kind, actor=actor, data=data)
    state["events"].append(event)
    if actor in state["residents"]:
        state["residents"][actor]["seen"].append(event["id"])
    return event["id"]


def new_resident(state, *, age_days, lifespan_days, name="", parents=None, identity=None):
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
        profile="mock-v1",
    )
    emit(state, "resident_born", rid, parents=parents or [])
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
        council={name: dict(id=uid(), memories=[]) for name in COUNCIL},
        council_chat=[],
        council_jobs=[],
        council_receipts=[],
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
    q, remainder = divmod(production, len(residents))
    state["creator"] += remainder
    for r in residents:
        r["personal"] += min(1, q)
        r["transferable"] += max(0, q - 1)
    share, remainder = divmod(state["pool"], len(residents))
    for r in residents:
        r["transferable"] += share
    for index in range(remainder):
        residents[(state["rotation"] + index) % len(residents)]["transferable"] += 1
    state["rotation"] = (state["rotation"] + remainder) % len(residents)
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
                state, age_days=f["age"], lifespan_days=f["lifespan"], identity=f["id"]
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
            child = new_resident(
                state,
                age_days=0,
                lifespan_days=rng.randint(
                    state["laws"]["lifespan_min_days"], state["laws"]["lifespan_max_days"]
                ),
                parents=proposal["parents"],
            )
            proposal["child"] = child
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


def resident_context(state, rid):
    r = state["residents"][rid]
    return dict(
        id=rid,
        name=r["name"],
        description=r["description"],
        world_time_seconds=state["clock"],
        age_days=(state["clock"] - r["born"]) / DAY,
        day_seconds=DAY,
        intentions=deepcopy(r["intentions"]),
        people=[dict(id=p["id"], name=p["name"]) for p in living(state)],
        resources=dict(
            personal=r["personal"],
            transferable=r["transferable"],
            daily_production=state["laws"]["daily_tickets"],
            current_daily_share=state["laws"]["daily_tickets"] // max(1, len(living(state))),
            next_allocation=(state["epoch"] + 1) * DAY,
        ),
        laws={k: v for k, v in state["laws"].items() if not k.startswith("founder")},
        proposals=[deepcopy(p) for p in state["proposals"] if rid in p["parents"]],
        explanation=(
            "One ticket pays for one model call, including technical summaries. "
            "Local tools and scheduling are free. Both balances accumulate indefinitely. "
            "Personal tickets are spent first and cannot be gifted. Transferable tickets "
            "can be saved, gifted or returned. Daily allocations repeat; this is not a "
            "lifetime allowance. You may choose your own interests, change your mind, "
            "or sleep. Your exact lifespan is unknown. A child reduces future equal "
            "shares and joins ordinary allocations the next day."
        ),
    )
