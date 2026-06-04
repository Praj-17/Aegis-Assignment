"""Load `config.yml` + environment variables into a typed Settings object."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class AppCfg(BaseModel):
    name: str = "aegis-discovery"
    environment: str = "local"
    log_level: str = "INFO"


class ServerCfg(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class StorageCfg(BaseModel):
    database_url_env: str = "DATABASE_URL"
    default_sqlite_path: str = "data/aegis.db"


class CorrelationCfg(BaseModel):
    time_window_seconds: int = 300
    duplicate_dedup: bool = True
    source_priority_for_framework: list[str] = Field(
        default_factory=lambda: [
            "CapabilityHint",
            "NHIManifest",
            "RuntimeEvent",
            "SaaSAuditEvent",
        ]
    )


class RiskWeights(BaseModel):
    scope: float = 0.20
    sensitivity: float = 0.35
    autonomy: float = 0.20
    drift: float = 0.25


class RiskTiers(BaseModel):
    low_max: int = 39
    medium_max: int = 69


class RiskCfg(BaseModel):
    weights: RiskWeights = Field(default_factory=RiskWeights)
    tiers: RiskTiers = Field(default_factory=RiskTiers)
    external_llm_destinations: list[str] = Field(default_factory=list)
    sensitive_data_classes: list[str] = Field(default_factory=list)


class PolicyEntry(BaseModel):
    id: str
    description: str = ""


class PoliciesCfg(BaseModel):
    catalog: list[PolicyEntry] = Field(default_factory=list)


class Settings(BaseModel):
    app: AppCfg = Field(default_factory=AppCfg)
    server: ServerCfg = Field(default_factory=ServerCfg)
    storage: StorageCfg = Field(default_factory=StorageCfg)
    correlation: CorrelationCfg = Field(default_factory=CorrelationCfg)
    risk: RiskCfg = Field(default_factory=RiskCfg)
    policies: PoliciesCfg = Field(default_factory=PoliciesCfg)

    @property
    def database_url(self) -> str:
        # Secrets/connection strings come from env; config.yml only names them.
        env_name = self.storage.database_url_env
        env_val = os.getenv(env_name)
        if env_val:
            return env_val
        return f"sqlite:///{self.storage.default_sqlite_path}"


def _project_root() -> Path:
    # src/aegis_discovery/config/settings.py -> project root is 3 levels up.
    return Path(__file__).resolve().parents[3]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache(maxsize=1)
def get_settings(config_path: str | None = None) -> Settings:
    path = Path(config_path) if config_path else _project_root() / "config.yml"
    data = _load_yaml(path)
    return Settings.model_validate(data)


def reset_settings_cache() -> None:
    """Used by tests so they can re-load with a different config."""

    get_settings.cache_clear()
