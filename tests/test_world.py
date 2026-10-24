import json

import pytest

from genesis_society.actions import conversational_context, execute, recall
from genesis_society.config import Laws
from genesis_society.storage import uid
from genesis_society.world import DAY, allocate, conserve, new_resident, resident_context, tick


def act(store, actor, kind, **args):
    return execute(store, actor, dict(kind=kind, **args), uid())


def test_daily_savings_transfer_return_death_conservation(store, actors):
    a, b = actors
    before = store.snapshot()
    assert before["residents"][a]["personal"] == 1
    act(store, a, "transfer_resources", recipient_id=b, amount=12)
    act(store, b, "transfer_resources", amount=7)
    with store.transaction() as (_, state):
        tick(state, DAY * 3)
        assert state["residents"][a]["personal"] == 4
        assert state["pool"] == 0
        assert conserve(state)
        r = state["residents"][a]
        r["lifespan"] = state["clock"] - r["born"]
        tick(state, 0)
        assert not r["alive"] and r["personal"] == r["transferable"] == 0
        assert state["pool"] > 0
        tick(state, DAY)
        assert state["pool"] == 0 and conserve(state)
    assert store.snapshot()["issued"] == 320 * 5


def test_private_protected_balance_and_validation(store, actors):
    a, b = actors
    with pytest.raises(ValueError):
        act(store, a, "transfer_resources", recipient_id=b, amount=160)
    with pytest.raises(ValueError):
        act(store, a, "transfer_resources", recipient_id=b, amount=True)
    with pytest.raises(ValueError):
        act(store, a, "send_direct_message", recipient_id=b, text="hi", sender_id=b)
    assert conserve(store.snapshot())


def test_consent_gestation_cap_and_inherited_testimony(store, actors):
    a, b = actors
    post = act(store, a, "board_post", title="Source", text="I experienced this.")
    memory = act(
        store,
        a,
        "remember",
        text="My fallible interpretation",
        sources=[post["post_id"]],
        memory_kind="belief",
    )
    proposal = act(store, a, "propose_child", other_id=b, memory_ids=[memory["memory_id"]])
    with pytest.raises(ValueError):
        act(store, a, "consent_child", proposal_id=proposal["proposal_id"])
    act(store, b, "consent_child", proposal_id=proposal["proposal_id"])
    with store.transaction() as (_, state):
        state["laws"]["population_cap"] = 2
        # Both parents can age beyond reproductive eligibility after consent.
        for r in state["residents"].values():
            r["born"] = -100 * DAY
            r["lifespan"] = 120 * DAY
        tick(state, DAY * 5)
        assert len(state["residents"]) == 2
        state["laws"]["population_cap"] = 3
        tick(state, 0)
        child = next(r for r in state["residents"].values() if r["parents"])
        assert child["personal"] == child["transferable"] == 0
        assert child["memories"][0]["inherited"]
        assert child["memories"][0]["id"] in child["seen"]
        assert not child["memories"][0]["kind"] == "episode"
        tick(state, DAY)
        assert child["personal"] == 1 and child["transferable"] > 0
        assert conserve(state)


def test_eligibility_and_lifespan_secrecy(store, actors):
    a, b = actors
    with store.transaction() as (_, state):
        state["residents"][a]["born"] = -20 * DAY
    with pytest.raises(ValueError):
        act(store, a, "propose_child", other_id=b)
    with store.transaction() as (_, state):
        state["residents"][a]["born"] = -85 * DAY
        state["residents"][a]["lifespan"] = 120 * DAY
    with pytest.raises(ValueError):
        act(store, a, "propose_child", other_id=b)
    context = resident_context(store.snapshot(), a)
    assert "lifespan" not in context and "born" not in context
    assert "10368000" not in json.dumps(context)


def test_dm_recall_old_belief_correction_and_privacy(store, actors):
    a, b = actors
    dm = act(store, a, "send_direct_message", recipient_id=b, text="Original experience")
    m = act(
        store,
        a,
        "remember",
        text="Initial belief",
        memory_kind="belief",
        sources=[dm["message_id"]],
        people=[b],
    )
    correction = act(
        store,
        a,
        "remember",
        text="Corrected belief",
        memory_kind="belief",
        sources=[dm["message_id"]],
        people=[b],
        supersedes=m["memory_id"],
    )
    for i in range(12):
        act(store, a, "remember", text=f"Unrelated {i}", sources=[dm["message_id"]])
    incoming = act(store, b, "send_direct_message", recipient_id=a, text="Remember our discussion?")
    state = store.snapshot()
    messages, pending, offered = conversational_context(state, a)
    assert pending[0]["id"] == incoming["message_id"]
    assert offered["memories"][0]["id"] == correction["memory_id"]
    assert all(x["id"] != m["memory_id"] for x in offered["memories"])
    assert offered["experiences"][0]["id"] == dm["message_id"]
    assert any(b in str(msg.content) for msg in messages)
    assert recall(state, b, [])["memories"] == []
    with pytest.raises(ValueError):
        act(store, b, "remember", text="Not perceived", sources=[m["memory_id"]])
    with store.transaction() as (_, state):
        c = new_resident(state, age_days=30, lifespan_days=150)
    page = act(store, c, "read_conversation", other_id=a)
    assert page["items"] == []


def test_tool_idempotency_and_object_acl(store, actors):
    a, b = actors
    action = dict(kind="write_object", name="private", text="Private content", public=False)
    first = execute(store, a, action, "same-call")
    assert execute(store, a, action, "same-call") == first
    with pytest.raises(ValueError):
        execute(store, a, dict(action, text="different"), "same-call")
    with pytest.raises(ValueError, match="unavailable"):
        act(store, b, "read_object", name="private")
    assert len(store.snapshot()["objects"]["private"]["revisions"]) == 1


def test_sleep_does_not_spend_or_wake_on_dm(store, actors):
    a, b = actors
    act(store, a, "sleep", seconds=3 * DAY, minimum_tickets=9, notify_direct_messages=True)
    act(store, b, "send_direct_message", recipient_id=a, text="No forced wake")
    state = store.snapshot()
    assert state["residents"][a]["wake_at"] == 3 * DAY
    assert state["spent"] == 0
    assert state["residents"][a]["minimum_tickets"] == 9


def test_default_laws_and_zero_population_recycling(store):
    laws = Laws()
    assert (laws.founders, laws.daily_tickets, laws.population_cap) == (16, 320, 64)
    with store.transaction() as (_, state):
        for r in state["residents"].values():
            r["lifespan"] = 0
        tick(state, 0)
        assert state["pool"] == 320
        allocate(state)
        assert state["pool"] == 320 and state["creator"] == 320
        assert conserve(state)


def test_population_change_allocation_and_rotating_recycling(store, actors):
    with store.transaction() as (_, state):
        child = new_resident(state, age_days=0, lifespan_days=200)
        state["pool"] = 2
        state["residents"][actors[0]]["transferable"] -= 2
        tick(state, DAY)
        assert state["residents"][child]["personal"] == 1
        assert state["creator"] == 2  # 320 mod 3
        assert state["pool"] == 0 and conserve(state)
        state["laws"]["daily_tickets"] = 0
        state["pool"] = 1
        state["residents"][actors[0]]["transferable"] -= 1
        previous_rotation = state["rotation"]
        tick(state, DAY)
        assert state["rotation"] != previous_rotation and conserve(state)


def test_initialization_refuses_existing_history(store):
    from genesis_society.world import initialize

    before = store.snapshot()
    with pytest.raises(ValueError, match="already exists"):
        initialize(store, Laws(founders=2))
    assert store.snapshot() == before
