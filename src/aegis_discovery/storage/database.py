"""SQLite-backed repository for events and agents.

Both tables are simple: we store the canonical Pydantic models as JSON. This
keeps the schema flexible during development and the queries trivial.

The repository class is small and intentionally protocol-shaped so an
in-memory implementation can be substituted in tests.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Protocol

from aegis_discovery.schemas import Agent, CanonicalEvent


class Repository(Protocol):
    def add_events(self, events: Iterable[CanonicalEvent]) -> int: ...
    def list_events(self) -> list[CanonicalEvent]: ...
    def upsert_agent(self, agent: Agent) -> None: ...
    def list_agents(self) -> list[Agent]: ...
    def get_agent(self, agent_id: str) -> Agent | None: ...
    def replace_all_agents(self, agents: Iterable[Agent]) -> None: ...
    def clear(self) -> None: ...


def _sqlite_path_from_url(database_url: str) -> str:
    # Expected forms: sqlite:///relative/path.db OR sqlite:////absolute/path.db
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        return database_url[len(prefix):]
    if database_url.startswith("sqlite:"):
        return database_url.split(":", 1)[1]
    return database_url


class SQLiteRepository:
    """Tiny SQLite repo. Thread-safe via a lock; ample for an MVP."""

    def __init__(self, database_url: str) -> None:
        path = _sqlite_path_from_url(database_url)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    fingerprint_hash TEXT,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agents (
                    agent_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    last_seen TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_events_fingerprint
                    ON events(source, fingerprint_hash);
                """
            )

    def add_events(self, events: Iterable[CanonicalEvent]) -> int:
        rows = []
        for e in events:
            rows.append(
                (
                    e.event_id,
                    e.source.value,
                    e.fingerprint_hash,
                    e.model_dump_json(),
                )
            )
        if not rows:
            return 0
        with self._lock, self._conn:
            cur = self._conn.executemany(
                "INSERT OR IGNORE INTO events (event_id, source, fingerprint_hash, payload) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )
            return cur.rowcount or 0

    def list_events(self) -> list[CanonicalEvent]:
        with self._lock:
            cur = self._conn.execute("SELECT payload FROM events")
            rows = cur.fetchall()
        return [CanonicalEvent.model_validate_json(r["payload"]) for r in rows]

    def upsert_agent(self, agent: Agent) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO agents (agent_id, payload, last_seen) VALUES (?, ?, ?)",
                (
                    agent.agent_id,
                    agent.model_dump_json(),
                    agent.last_seen.isoformat() if agent.last_seen else None,
                ),
            )

    def replace_all_agents(self, agents: Iterable[Agent]) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM agents")
            self._conn.executemany(
                "INSERT INTO agents (agent_id, payload, last_seen) VALUES (?, ?, ?)",
                [
                    (
                        a.agent_id,
                        a.model_dump_json(),
                        a.last_seen.isoformat() if a.last_seen else None,
                    )
                    for a in agents
                ],
            )

    def list_agents(self) -> list[Agent]:
        with self._lock:
            cur = self._conn.execute("SELECT payload FROM agents ORDER BY agent_id")
            rows = cur.fetchall()
        return [Agent.model_validate_json(r["payload"]) for r in rows]

    def get_agent(self, agent_id: str) -> Agent | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT payload FROM agents WHERE agent_id = ?", (agent_id,)
            )
            row = cur.fetchone()
        if row is None:
            return None
        return Agent.model_validate_json(row["payload"])

    def clear(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript("DELETE FROM events; DELETE FROM agents;")


class InMemoryRepository:
    """Used by tests; mirrors SQLiteRepository's interface."""

    def __init__(self) -> None:
        self._events: dict[str, CanonicalEvent] = {}
        self._agents: dict[str, Agent] = {}
        self._seen_fp: set[tuple[str, str]] = set()

    def add_events(self, events: Iterable[CanonicalEvent]) -> int:
        added = 0
        for e in events:
            key = (e.source.value, e.fingerprint_hash)
            if e.fingerprint_hash and key in self._seen_fp:
                continue
            if e.event_id in self._events:
                continue
            self._events[e.event_id] = e
            if e.fingerprint_hash:
                self._seen_fp.add(key)
            added += 1
        return added

    def list_events(self) -> list[CanonicalEvent]:
        return list(self._events.values())

    def upsert_agent(self, agent: Agent) -> None:
        self._agents[agent.agent_id] = agent

    def replace_all_agents(self, agents: Iterable[Agent]) -> None:
        self._agents = {a.agent_id: a for a in agents}

    def list_agents(self) -> list[Agent]:
        return list(self._agents.values())

    def get_agent(self, agent_id: str) -> Agent | None:
        return self._agents.get(agent_id)

    def clear(self) -> None:
        self._events.clear()
        self._agents.clear()
        self._seen_fp.clear()
