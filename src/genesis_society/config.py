from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Laws(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    founders: int = Field(default=16, ge=1, le=64)
    founder_window_seconds: int = Field(default=7200, ge=0)
    daily_tickets: int = Field(default=320, ge=0)
    population_cap: int = Field(default=64, ge=1)
    lifespan_min_days: int = Field(default=120, ge=1)
    lifespan_max_days: int = Field(default=360, ge=1)
    founder_age_min_days: int = Field(default=20, ge=0)
    founder_age_max_days: int = Field(default=60, ge=0)
    reproduction_min_days: int = Field(default=21, ge=0)
    reproduction_fraction: float = Field(default=0.7, gt=0, le=1)
    gestation_days: int = Field(default=5, ge=1)
    cooldown_seconds: int = Field(default=60, ge=1)

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
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOCIETY_", env_file=".env", extra="ignore")
    database_url: str = "postgresql://society:local-demo-only@localhost:55433/society"
    creator_token: SecretStr | None = None
    provider: Literal["mock"] = "mock"
    concurrency: int = Field(default=2, ge=1, le=8)
    azure_endpoint: str = "https://YOUR-RESOURCE.openai.azure.com"
    azure_deployment: str = "YOUR-DEPLOYMENT"
    azure_auth: Literal["entra", "key"] = "entra"
    azure_api_key: SecretStr | None = None
    slack_channel_id: str = "YOUR-COUNCIL-CHANNEL"

    @property
    def sqlalchemy_url(self):
        return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)


def load_laws(path: Path | None = None) -> Laws:
    return Laws.model_validate_json(path.read_text()) if path else Laws()
