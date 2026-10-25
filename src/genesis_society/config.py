from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Laws(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    founders: int = Field(default=16, ge=1, le=256)
    founder_window_seconds: int = Field(default=7200, ge=0)
    daily_tickets: int = Field(default=320, ge=0)
    population_cap: int = Field(default=64, ge=1)
    max_concurrency: int = Field(default=4, ge=1, le=32)
    lifespan_min_days: int = Field(default=120, ge=1)
    lifespan_max_days: int = Field(default=360, ge=1)
    founder_age_min_days: int = Field(default=20, ge=0)
    founder_age_max_days: int = Field(default=60, ge=0)
    reproduction_min_days: int = Field(default=21, ge=0)
    reproduction_fraction: float = Field(default=0.7, gt=0, le=1)
    gestation_days: int = Field(default=5, ge=1)
    cooldown_seconds: int = Field(default=60, ge=1)
    birth_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "gpt-5.4-nano:low": 0.10,
            "gpt-5.4-nano:medium": 0.08,
            "gpt-5.4-nano:high": 0.04,
            "gpt-5.4-mini:low": 0.08,
            "gpt-5.4-mini:medium": 0.08,
            "gpt-5.4-mini:high": 0.04,
            "claude-haiku-5-5:low": 0.08,
            "claude-haiku-5-5:medium": 0.07,
            "claude-haiku-5-5:high": 0.03,
            "gpt-5.6-terra:low": 0.05,
            "gpt-5.6-terra:medium": 0.06,
            "gpt-5.6-terra:high": 0.04,
            "gpt-5.4:low": 0.03,
            "gpt-5.4:medium": 0.05,
            "gpt-5.4:high": 0.03,
            "claude-sonnet-5-5:low": 0.02,
            "claude-sonnet-5-5:medium": 0.04,
            "claude-sonnet-5-5:high": 0.02,
            "gpt-5.6-sol:medium": 0.01,
            "gpt-5.6-sol:high": 0.02,
            "claude-opus-5-5:medium": 0.01,
            "claude-opus-5-5:high": 0.02,
        }
    )

    @model_validator(mode="after")
    def coherent(self):
        if not (
            self.founder_age_min_days
            <= self.founder_age_max_days
            < self.lifespan_min_days
            <= self.lifespan_max_days
        ):
            raise ValueError("founder ages must precede all assigned lifespans")
        if self.founders > self.population_cap:
            raise ValueError("founders exceed population cap")
        if (
            not self.birth_weights
            or any(w < 0.0 or w > 1.0 for w in self.birth_weights.values())
            or abs(sum(self.birth_weights.values()) - 1.0) > 1e-6
        ):
            raise ValueError("birth_weights must be between 0 and 1 and sum to 1.0")
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOCIETY_", env_file=".env", extra="ignore")
    database_url: str = "postgresql://society:local-demo-only@localhost:55433/society"
    creator_token: SecretStr | None = None
    provider: Literal["mock", "azure_foundry"] = "mock"
    paid_inference_enabled: bool = False
    tracing: bool = False
    concurrency: int = Field(default=4, ge=1, le=32)
    # Entra only: the resource selects the endpoint and each resident profile names its deployment.
    azure_resource: str = ""
    azure_auth: Literal["entra", "key"] = "entra"
    # Set only so that a key configuration is refused before any dispatch.
    azure_api_key: SecretStr | None = None
    slack_channel_id: str = "YOUR-COUNCIL-CHANNEL"
    # Read-only GitHub scope. Empty values mean no live GitHub source is readable.
    github_org: str = ""
    github_repo_prefix: str = ""
    github_context_repo: str = ""
    github_deployments_repo: str = ""
    local_repo_root: str = ""
    # Free-text description of the ecosystem residents live next to (used in prompts only).
    ecosystem_description: str = "an organization's software ecosystem"

    @property
    def sqlalchemy_url(self):
        return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)


def load_laws(path: Path | None = None) -> Laws:
    return Laws.model_validate_json(path.read_text()) if path else Laws()
