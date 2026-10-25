import json

import pytest

from genesis_society.actions import conversational_context, execute, recall
from genesis_society.config import Laws
from genesis_society.storage import uid
from genesis_society.world import (
    DAY,
    allocate,
    conserve,
    delegation_cycles,
    new_resident,
    represented_by,
    resident_context,
    tick,
    voting_weight,
)


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
        state["synthetic"] = False
        state["laws"]["birth_weights"] = {"retired-v1": 0.0, "claude-sonnet-5-5:medium": 1.0}
        # Both parents can age beyond reproductive eligibility after consent.
        for r in state["residents"].values():
            r["born"] = -100 * DAY
            r["lifespan"] = 120 * DAY
        tick(state, DAY * 5)
        assert len(state["residents"]) == 2
        state["laws"]["population_cap"] = 3
        tick(state, 0)
        child = next(r for r in state["residents"].values() if r["parents"])
        assert child["profile"] == "claude-sonnet-5-5:medium"
        assert resident_context(state, child["id"])["parents"] == [a, b]
        assert child["id"] in resident_context(state, a)["children"]
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


def test_replay_distinguishes_omitted_identity_fields_from_explicit_clear(store, actors):
    actor = actors[0]
    act(store, actor, "update_identity", description="An existing self-description")
    original = dict(kind="update_identity", name="Chosen name")
    execute(store, actor, original, "identity-call")
    assert store.snapshot()["residents"][actor]["description"] == "An existing self-description"
    with pytest.raises(ValueError, match="different arguments"):
        execute(store, actor, dict(original, description=None), "identity-call")
    act(store, actor, "update_identity", description=None)
    assert store.snapshot()["residents"][actor]["description"] == ""
    with pytest.raises(ValueError, match="No identity change"):
        act(store, actor, "update_identity")


def test_daily_team_dispatch_cap_and_visibility(store, actors):
    a, b = actors
    src_a = act(store, a, "read_source", source_id="github:example/widget/README.md")
    draft = act(
        store,
        a,
        "escalate_to_team",
        title="Retry timeout finding",
        text="Widget requests time out after 30s.",
        sources=[src_a["reference"]],
    )
    assert draft["status"] == "pending_cosign"
    with pytest.raises(ValueError, match="Another resident"):
        act(
            store,
            a,
            "escalate_to_team",
            escalation_id=draft["escalation_id"],
            sources=[src_a["reference"]],
        )
    src_b = act(store, b, "read_source", source_id="github:example/widget/README.md")
    sent = act(
        store,
        b,
        "escalate_to_team",
        escalation_id=draft["escalation_id"],
        sources=[src_b["reference"]],
    )
    assert sent["status"] == "sent" and sent["epoch"] == 0
    with pytest.raises(ValueError, match="already sent"):
        act(store, b, "escalate_to_team", title="Second", text="Blocked", sources=[b])
    ctx_b = resident_context(store.snapshot(), b)
    assert not ctx_b["daily_team_dispatch_available"]
    assert ctx_b["team_dispatches"][0]["title"] == "Retry timeout finding"
    with store.transaction() as (_, state):
        tick(state, DAY)
    assert resident_context(store.snapshot(), b)["daily_team_dispatch_available"]
    # Test emergent kingdom/delegation quorum in live society mode
    with store.transaction() as (_, state):
        state["synthetic"] = False
        c = new_resident(state, age_days=3, lifespan_days=10, name="Scout")
        d = new_resident(state, age_days=3, lifespan_days=10, name="Builder")
    act(store, a, "update_identity", name="King")
    act(store, b, "update_identity", name="Vassal", allegiance=a)
    act(store, c, "update_identity", allegiance=a)
    # 4 living residents -> quorum is max(3, (4+2)//3) = 3. King represents a, b, c (3 votes).
    king_send = act(
        store, a, "escalate_to_team", title="Royal decree", text="Verified.", sources=[a]
    )
    assert king_send["status"] == "sent" and king_send["votes"] == 3 and d is not None


def test_allegiance_loop_is_refused_and_existing_loops_are_listed(store, actors):
    a, b = actors
    act(store, b, "update_identity", name="Vassal", allegiance=a)
    with pytest.raises(ValueError, match="already follows you"):
        act(store, a, "update_identity", name="King", allegiance=b)
    assert store.snapshot()["residents"][a]["allegiance"] is None
    assert delegation_cycles(store.snapshot()) == []
    with store.transaction() as (_, state):
        # A loop written before the refusal existed must still be visible to the Creator.
        state["residents"][a]["allegiance"] = b
    cycles = delegation_cycles(store.snapshot())
    assert len(cycles) == 1 and sorted(cycles[0]) == sorted([a, b])


def test_long_delegation_chain_is_followed_without_a_hop_cap(store):
    with store.transaction() as (_, state):
        ids = [new_resident(state, age_days=3, lifespan_days=10) for _ in range(18)]
        for leader, follower in zip(ids, ids[1:], strict=False):
            state["residents"][follower]["allegiance"] = leader
    state = store.snapshot()
    assert voting_weight(state, ids[0]) == 18
    assert ids[-1] in represented_by(state, [ids[0]])


def _walk(read, limit):
    seen, offset = [], 0
    while offset is not None:
        page = read(offset=offset, limit=limit)
        assert len(page["items"]) <= limit
        seen.extend(item["text"] for item in page["items"])
        offset = page["next_offset"]
    return seen


def test_thread_pages_are_contiguous_bounded_and_expose_newest(store, actors):
    a, b = actors
    thread_id = act(store, a, "board_post", title="Ten posts", text="post 0", tags=[])["thread_id"]
    for i in range(1, 10):
        act(store, b if i % 2 else a, "board_reply", thread_id=thread_id, text=f"post {i}")

    def read(**kwargs):
        return act(store, a, "board_read", thread_id=thread_id, **kwargs)

    everything = [f"post {i}" for i in range(10)]
    for limit in (1, 3, 10):
        assert _walk(read, limit) == everything, limit
    assert read(limit=1)["items"][0]["text"] == "post 0"
    newest = read(limit=3)
    assert newest["latest_offset"] == 7
    assert [i["text"] for i in read(offset=newest["latest_offset"], limit=3)["items"]] == [
        "post 7",
        "post 8",
        "post 9",
    ]
    past_end = read(offset=10, limit=3)
    assert past_end["items"] == [] and past_end["next_offset"] is None


def test_direct_message_pages_are_contiguous_and_expose_newest(store, actors):
    a, b = actors
    for i in range(10):
        sender, recipient = (a, b) if i % 2 == 0 else (b, a)
        act(store, sender, "send_direct_message", recipient_id=recipient, text=f"dm {i}")

    def read(**kwargs):
        return act(store, a, "read_conversation", other_id=b, **kwargs)

    everything = [f"dm {i}" for i in range(10)]
    for limit in (1, 3, 10):
        assert _walk(read, limit) == everything, limit
    newest = read(limit=3)
    assert newest["latest_offset"] == 7
    assert [m["text"] for m in read(offset=7, limit=3)["items"]] == ["dm 7", "dm 8", "dm 9"]
