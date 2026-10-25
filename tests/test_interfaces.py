import time

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from sqlalchemy.orm import Session

from genesis_society.connectors import (
    AzureConfig,
    SlackBot,
    SlackConfig,
    deliver_mock_council,
    receive_mock_council,
)
from genesis_society.inspector import app_for, worker_status
from genesis_society.runtime import Ledger
from genesis_society.sources import (
    SourceRead,
    _discover_github_repos,
    _scope,
    list_source_entrypoints,
    read_source,
)
from genesis_society.storage import Request
from genesis_society.world import COUNCIL, conserve


def test_creator_inspector_auth_escape_and_truthful_health(store):
    token = "synthetic-local-inspector-token-only"
    with store.transaction() as (_, state):
        state["threads"].append(dict(title="<script>alert(1)</script>", posts=[]))
    with TestClient(app_for(store, token)) as client:
        assert client.get("/").status_code == 401
        assert client.get("/api/snapshot").status_code == 401
        assert client.get("/health").json() == {"http": "responsive"}
        headers = {"Authorization": "Bearer " + token}
        response = client.get("/", headers=headers)
        assert response.status_code == 200
        assert "&lt;script&gt;" in response.text and "<script>" not in response.text
        assert "not started" in response.text
        assert client.get("/api/snapshot", headers=headers).json()["world"]["synthetic"]
        login = client.post("/login", data={"token": token})
        assert login.status_code == 200 and "Residents" in login.text
        assert client.get("/").headers["cache-control"] == "no-store"
        client.post(
            "/control",
            data={"action": "weights", "w:gpt-5.6-sol": "0.75", "w:claude-sonnet-5-5": "0.25"},
        )
        client.post(
            "/control",
            data={
                "action": "grant",
                "kind": "reward",
                "amount": "15",
                "recipient_id": "",
                "reason": "Strong teamplay",
            },
        )
        snap = store.snapshot()
        assert snap["laws"]["birth_weights"] == {"gpt-5.6-sol": 0.75, "claude-sonnet-5-5": 0.25}
        assert snap["pool"] == 15
        assert "REWARDED" in snap["decrees"][0]["text"]
    state = store.snapshot()
    state["health"] = dict(status="running", heartbeat=time.time() - 100)
    assert worker_status(state) == "stale"
    state["health"] = dict(status="stopped", heartbeat=time.time())
    assert worker_status(state) == "stopped"


def test_inspector_lists_existing_allegiance_loops(store, actors):
    token = "synthetic-local-inspector-token-only"
    a, b = actors
    with store.transaction() as (_, state):
        state["residents"][a]["allegiance"] = b
        state["residents"][b]["allegiance"] = a
    with TestClient(app_for(store, token)) as client:
        response = client.get("/", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 200
    assert "Allegiance loops (1)" in response.text


def test_azure_contract_no_client_no_network():
    config = AzureConfig(
        endpoint="https://fixture.openai.azure.com", deployment="private-deployment"
    )
    options = config.client_options()
    assert options["max_retries"] == 0
    assert options["base_url"].endswith("/openai/v1/")
    assert options["model"] == "private-deployment"
    with pytest.raises(ValueError):
        AzureConfig(endpoint="http://fixture", deployment="x")
    with pytest.raises(ValueError):
        AzureConfig(endpoint="https://fixture", deployment="x", auth="key")


@pytest.mark.parametrize(
    "overrides",
    [dict(azure_auth="key"), dict(azure_api_key="fixture-key-not-a-secret")],
)
def test_azure_key_authentication_is_refused_before_any_model_is_built(store, overrides):
    from genesis_society.cli import _model_factory_for
    from genesis_society.config import Settings

    settings = Settings(
        provider="azure_foundry",
        paid_inference_enabled=True,
        azure_resource="fixture-resource",
        **overrides,
    )
    with pytest.raises(ValueError, match="API-key authentication is not supported"):
        _model_factory_for(store, settings)


def test_mock_council_dedupe_mentions_and_no_reply_storm(store):
    bots = [
        SlackBot(role=role, bot_token=f"fixture-bot-{i}", app_token=f"fixture-app-{i}")
        for i, role in enumerate(COUNCIL)
    ]
    SlackConfig(channel_id="fixture-channel", bots=bots)
    for _ in range(2):
        receive_mock_council(
            store,
            event_id="one",
            author="Creator",
            text="Please investigate",
            mentions=["Historian"],
        )
    receive_mock_council(
        store, event_id="two", author="Creator", text="And this", mentions=["Historian"]
    )
    receive_mock_council(
        store,
        event_id="bot",
        author="Historian",
        text="No recursive activation",
        mentions=["Scorer"],
        is_bot=True,
    )
    assert len(store.snapshot()["council_jobs"]) == 1
    deliver_mock_council(store)
    deliver_mock_council(store)
    state = store.snapshot()
    assert len(state["council_chat"]) == 4
    assert state["council_jobs"][0]["events"] == ["one", "two"]
    assert state["spent"] == 0


@pytest.fixture
def github_scope_unset(monkeypatch):
    for name in (
        "SOCIETY_GITHUB_ORG",
        "SOCIETY_GITHUB_REPO_PREFIX",
        "SOCIETY_GITHUB_CONTEXT_REPO",
        "SOCIETY_GITHUB_DEPLOYMENTS_REPO",
        "SOCIETY_LOCAL_REPO_ROOT",
    ):
        monkeypatch.setenv(name, "")
    _scope.cache_clear()
    yield
    _scope.cache_clear()


def test_loopback_clients_need_creator_credentials(store):
    token = "synthetic-local-inspector-token-only"
    with TestClient(app_for(store, token), client=("127.0.0.1", 50000)) as client:
        assert client.get("/health").json() == {"http": "responsive"}
        assert client.get("/").status_code == 401
        assert client.get("/api/snapshot").status_code == 401
        denied = client.post("/control", data={"action": "weights", "w:gpt-5.6-sol": "1.0"})
        assert denied.status_code == 401
        assert store.snapshot()["laws"]["birth_weights"] != {"gpt-5.6-sol": 1.0}
        headers = {"Authorization": "Bearer " + token}
        assert client.get("/api/snapshot", headers=headers).status_code == 200


def test_source_allowlist_version_and_pagination(github_scope_unset):
    first = read_source(SourceRead(source_id="github:example/widget/README.md", limit=20))
    second = read_source(SourceRead(source_id=first.source_id, offset=first.next_offset, limit=20))
    assert first.revision == second.revision
    assert first.offset == 0 and second.offset == 20
    for denied in ("/etc/passwd", "repo:example-service:.env", "repo:unknown:README.md"):
        with pytest.raises(ValueError):
            read_source(SourceRead(source_id=denied))


def test_github_sources_fail_closed_without_configured_scope(github_scope_unset):
    assert list_source_entrypoints() == []
    for denied in (
        "github:PULSE",
        "github:SEARCH:retry",
        "context:INDEX",
        "deployments:INDEX",
        "repo:example-service:INDEX",
    ):
        with pytest.raises(ValueError):
            read_source(SourceRead(source_id=denied))


def test_live_github_sources_when_configured():
    if not _scope().repos_enabled:
        pytest.skip("Set SOCIETY_GITHUB_ORG and SOCIETY_GITHUB_REPO_PREFIX for live reads")
    repos = _discover_github_repos()
    assert repos, "the configured scope should expose at least one canonical repo"
    index = read_source(SourceRead(source_id=f"repo:{repos[0]}:INDEX", limit=100))
    assert not index.synthetic and len(index.revision) == 12 and index.text
    with pytest.raises(ValueError):
        read_source(SourceRead(source_id=f"repo:{repos[0]}:.env"))


def test_creator_unblock_releases_resident_like_the_timer(store, actors):
    token = "synthetic-local-inspector-token-only"
    actor = actors[0]
    with store.transaction() as (_, state):
        state["paused"] = False
    ledger = Ledger(store)
    ledger.prepare("ui-timeout", actor, [HumanMessage(content="original")])
    ledger.mark_sent("ui-timeout")
    ledger.uncertain("ui-timeout", TimeoutError("timed out"))
    spent = store.snapshot()["spent"]
    assert store.snapshot()["residents"][actor]["blocked"] == "uncertain_request:ui-timeout"
    with TestClient(app_for(store, token)) as client:
        assert client.post("/login", data={"token": token}).status_code == 200
        client.post("/control", data={"action": "unblock", "actor": actor})
    state = store.snapshot()
    assert state["residents"][actor]["blocked"] is None
    assert state["spent"] == spent
    assert conserve(state)
    with Session(store.engine) as session:
        assert session.get(Request, "ui-timeout").phase == "abandoned"


def test_cost_panel_reports_unknown_when_langsmith_is_unreachable(monkeypatch):
    import langsmith

    from genesis_society import inspector

    monkeypatch.setattr(inspector, "_COST_CACHE", {"at": 0.0, "world": None, "data": None})

    def unreachable(*args, **kwargs):
        raise RuntimeError("langsmith down")

    monkeypatch.setattr(langsmith, "Client", unreachable)
    state = {"laws": {"daily_tickets": 320}, "spent": 5, "epoch": 0, "synthetic": False}
    stats = inspector._compute_cost_stats(state, [])
    assert stats["known"] is False
    assert stats["by_model"] == []
    # A failed lookup is remembered, so the next poll does not query LangSmith again.
    calls = []
    monkeypatch.setattr(langsmith, "Client", lambda *a, **k: calls.append(1) or unreachable())
    inspector._compute_cost_stats(state, [])
    assert calls == []


def test_cost_panel_is_known_for_synthetic_worlds():
    from genesis_society import inspector

    state = {"laws": {"daily_tickets": 320}, "spent": 5, "epoch": 0, "synthetic": True}
    stats = inspector._compute_cost_stats(state, [])
    assert stats["known"] is True
    assert stats["total_usd"] == "0.00"


def test_pulse_is_refetched_each_interval_and_keeps_its_fetch_time(monkeypatch):
    from genesis_society import sources

    sources._org_pulse_snapshot.cache_clear()
    monkeypatch.setattr(
        sources, "_scope", lambda: sources.GitHubScope(org="acme", name_prefix="svc-")
    )
    fetches = []
    monkeypatch.setattr(
        sources, "_org_pulse_text", lambda: fetches.append(1) or f"pulse {len(fetches)}"
    )
    interval = {"bucket": 1_000_001}
    monkeypatch.setattr(sources, "_ttl_bucket", lambda: interval["bucket"])

    first = read_source(SourceRead(source_id="github:PULSE"))
    again = read_source(SourceRead(source_id="github:PULSE"))
    assert len(fetches) == 1
    assert again.text == first.text
    assert again.revision == first.revision and again.captured_at == first.captured_at

    interval["bucket"] += 1
    later = read_source(SourceRead(source_id="github:PULSE"))
    assert len(fetches) == 2 and later.text == "pulse 2"
    sources._org_pulse_snapshot.cache_clear()


def test_org_search_without_local_clones_is_unavailable_not_a_no_match(monkeypatch):
    from genesis_society import sources

    monkeypatch.setattr(
        sources, "_scope", lambda: sources.GitHubScope(org="acme", name_prefix="svc-")
    )
    text = sources._org_search("retry")
    assert text.startswith("Search unavailable")
    assert "No matches" not in text


def test_remote_repo_search_failure_is_unavailable_and_results_are_unpinned(monkeypatch):
    from genesis_society import sources

    monkeypatch.setattr(
        sources, "_scope", lambda: sources.GitHubScope(org="acme", name_prefix="svc-")
    )

    def failing(cmd, **kwargs):
        raise ValueError(sources.DENIED)

    monkeypatch.setattr(sources, "_run", failing)
    text = sources._repo_search("repo:svc-x", "svc-x", "abc123abc123", "retry")
    assert text.startswith("Search unavailable")

    monkeypatch.setattr(sources, "_run", lambda cmd, **kwargs: "[]")
    text = sources._repo_search("repo:svc-x", "svc-x", "abc123abc123", "retry")
    assert text.startswith("No matches") and "not pinned to abc123abc123" in text
