"""Azure AI Foundry connector and Council transport contracts."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, SecretStr, model_validator

from .world import COUNCIL


class AzureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str
    deployment: str
    auth: Literal["entra", "key"] = "entra"
    api_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_endpoint(self):
        parsed = urlsplit(self.endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use an HTTPS Azure resource endpoint without embedded credentials")
        if parsed.query or parsed.fragment or parsed.path.rstrip("/") not in ("", "/openai/v1"):
            raise ValueError("Use the resource root or /openai/v1 endpoint")
        if not self.deployment.strip():
            raise ValueError("An installation-specific deployment name is required")
        if self.auth == "key" and self.api_key is None:
            raise ValueError("API key is required for key authentication")
        return self

    def client_options(self):
        root = self.endpoint.rstrip("/")
        return dict(
            base_url=root if root.endswith("/openai/v1") else root + "/openai/v1/",
            model=self.deployment,
            max_retries=0,
            timeout=60,
            max_tokens=8192,
        )


def build_foundry_model(resource: str, profile: str, token_provider=None):
    deployment, _, effort = profile.partition(":")
    if token_provider is None:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
    if deployment.startswith("claude-"):
        from anthropic import AnthropicFoundry, AsyncAnthropicFoundry
        from langchain_anthropic import ChatAnthropic

        extra = (
            dict(thinking={"type": "adaptive"}, output_config={"effort": effort}) if effort else {}
        )
        model = ChatAnthropic(
            model=deployment, api_key="entra", max_tokens=8192, max_retries=0, **extra
        )
        kw = dict(
            resource=resource, azure_ad_token_provider=token_provider, max_retries=0, timeout=60
        )
        model._client = AnthropicFoundry(**kw)
        model._async_client = AsyncAnthropicFoundry(**kw)
        return model
    from langchain_openai import ChatOpenAI

    opts = AzureConfig(
        endpoint=f"https://{resource}.openai.azure.com", deployment=deployment
    ).client_options()
    extra = dict(reasoning_effort=effort) if effort else {}
    return ChatOpenAI(api_key=token_provider, use_responses_api=True, **extra, **opts)


class SlackBot(BaseModel):
    role: Literal["Historian", "Strategist", "Skeptic", "Scorer"]
    bot_token: SecretStr
    app_token: SecretStr


class SlackConfig(BaseModel):
    channel_id: str
    bots: list[SlackBot]

    @model_validator(mode="after")
    def independent_bots(self):
        if sorted(b.role for b in self.bots) != sorted(COUNCIL):
            raise ValueError("Exactly one separate bot per Council identity is required")
        if len({b.bot_token.get_secret_value() for b in self.bots}) != 4:
            raise ValueError("Council bots need independent bot identities")
        return self


def receive_mock_council(store, *, event_id, author, text, mentions=(), is_bot=False):
    """Persistent idempotent intake; mentions enqueue jobs, never invoke a model."""
    if any(role not in COUNCIL for role in mentions):
        raise ValueError("Unknown consultant")
    with store.transaction() as (_, state):
        if event_id in state["council_receipts"]:
            return
        state["council_receipts"].append(event_id)
        state["council_chat"].append(
            dict(id=event_id, author=author, text=text, time=state["clock"], synthetic=True)
        )
        # No bot-to-bot auto-trigger storms. Spontaneous activation is deferred.
        if not is_bot:
            for role in set(mentions):
                pending = next(
                    (
                        j
                        for j in state["council_jobs"]
                        if j["role"] == role and j["status"] == "pending"
                    ),
                    None,
                )
                if pending:
                    pending["events"].append(event_id)
                else:
                    state["council_jobs"].append(
                        dict(role=role, status="pending", events=[event_id])
                    )


def deliver_mock_council(store):
    with store.transaction() as (_, state):
        for job in state["council_jobs"]:
            if job["status"] == "pending":
                state["council_chat"].append(
                    dict(
                        id="reply:" + job["events"][0] + job["role"],
                        author=job["role"],
                        time=state["clock"],
                        synthetic=True,
                        text="Scripted transport fixture: observation request received.",
                        reply_to=job["events"],
                    )
                )
                job["status"] = "done"
