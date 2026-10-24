import time

import pytest
from fastapi.testclient import TestClient

from genesis_society.connectors import (
    AzureConfig,
    SlackBot,
    SlackConfig,
    deliver_mock_council,
    receive_mock_council,
)
from genesis_society.inspector import app_for, worker_status
from genesis_society.sources import SourceRead, read_source
from genesis_society.world import COUNCIL


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
    state = store.snapshot()
    state["health"] = dict(status="running", heartbeat=time.time() - 100)
    assert worker_status(state) == "stale"
    state["health"] = dict(status="stopped", heartbeat=time.time())
    assert worker_status(state) == "stopped"


def test_azure_contract_no_client_no_network():
    config = AzureConfig(
        endpoint="https://fixture.openai.azure.com", deployment="private-deployment"
    )
    options = config.client_options()
    assert options["max_retries"] == 0
    assert options["base_url"].endswith("/openai/v1/")
    assert options["model"] == "private-deployment"
    assert config.auth == "entra"
    with pytest.raises(ValueError):
        AzureConfig(endpoint="http://fixture", deployment="x")
    with pytest.raises(ValueError):
        AzureConfig(endpoint="https://fixture", deployment="x", auth="key")


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


def test_source_allowlist_version_and_pagination():
    first = read_source(SourceRead(source_id="github:example/widget/README.md", limit=20))
    second = read_source(SourceRead(source_id=first.source_id, offset=first.next_offset, limit=20))
    assert first.revision == second.revision
    assert first.offset == 0 and second.offset == 20
    with pytest.raises(ValueError):
        read_source(SourceRead(source_id="/etc/passwd"))
