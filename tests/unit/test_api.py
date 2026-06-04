"""HTTP-layer tests using FastAPI's TestClient."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import create_app
from aegis_discovery.api import dependencies as deps
from aegis_discovery.storage.database import InMemoryRepository


SAMPLES = Path(__file__).resolve().parents[2] / "samples"


@pytest.fixture()
def client() -> TestClient:
    repo = InMemoryRepository()

    def _override() -> InMemoryRepository:
        return repo

    app = create_app()
    app.dependency_overrides[deps.get_repository] = _override
    return TestClient(app)


def test_health(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_post_events_full_pipeline(client: TestClient) -> None:
    payload = json.loads((SAMPLES / "scenario_full.json").read_text(encoding="utf-8"))
    res = client.post("/events", json=payload)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["new_or_updated_agents"] == 2
    res2 = client.get("/agents")
    assert res2.status_code == 200
    agents = res2.json()
    assert len(agents) == 2


def test_get_agent_and_graph(client: TestClient) -> None:
    payload = json.loads((SAMPLES / "scenario_full.json").read_text(encoding="utf-8"))
    client.post("/events", json=payload)
    agents = client.get("/agents").json()
    aid = agents[0]["agent_id"]
    detail = client.get(f"/agents/{aid}").json()
    assert detail["agent_id"] == aid
    graph = client.get(f"/agents/{aid}/graph").json()
    assert graph["agent_id"] == aid
    assert len(graph["nodes"]) >= 2


def test_bad_event_type_returns_400(client: TestClient) -> None:
    res = client.post("/events", json=[{"type": "NotAType"}])
    assert res.status_code == 400
