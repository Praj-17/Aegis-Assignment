"""Shared FastAPI dependencies: settings + repository singletons."""

from __future__ import annotations

from functools import lru_cache

from aegis_discovery.config.settings import Settings, get_settings
from aegis_discovery.storage.database import Repository, SQLiteRepository


@lru_cache(maxsize=1)
def get_repository() -> Repository:
    settings = get_settings()
    return SQLiteRepository(settings.database_url)


def get_app_settings() -> Settings:
    return get_settings()
