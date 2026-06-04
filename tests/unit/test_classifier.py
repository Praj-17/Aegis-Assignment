"""Fingerprint classifier: framework conflict resolution by source priority."""

from __future__ import annotations

from datetime import datetime, timezone

from aegis_discovery.correlation.correlator import EventCluster
from aegis_discovery.correlation.agent_builder import build_agent_from_cluster
from aegis_discovery.fingerprint.classifier import classify_agent
from aegis_discovery.normalize.normalizer import normalize_one


SOURCE_PRIORITY = ["CapabilityHint", "NHIManifest", "RuntimeEvent", "SaaSAuditEvent"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_capability_hint_wins_over_runtime() -> None:
    events = [
        normalize_one({"type": "CapabilityHint", "repo": "r", "framework_hint": "langchain", "timestamp": _now()}),
        normalize_one({"type": "RuntimeEvent", "host_id": "h", "pid": 1, "framework_hint": "crewai", "timestamp": _now()}),
    ]
    cluster = EventCluster(events=events, confidence=0.9)
    agent = build_agent_from_cluster(cluster, agent_id="a-1")
    agent = classify_agent(agent, cluster, SOURCE_PRIORITY)
    assert agent.framework == "langchain"
    assert len(agent.conflicts) == 1
    assert agent.conflicts[0].winning_source == "CapabilityHint"


def test_no_conflict_returns_clean_framework() -> None:
    events = [
        normalize_one({"type": "CapabilityHint", "repo": "r", "framework_hint": "crewai", "timestamp": _now()}),
        normalize_one({"type": "RuntimeEvent", "host_id": "h", "pid": 1, "framework_hint": "crewai", "timestamp": _now()}),
    ]
    cluster = EventCluster(events=events, confidence=0.9)
    agent = build_agent_from_cluster(cluster, agent_id="a-2")
    agent = classify_agent(agent, cluster, SOURCE_PRIORITY)
    assert agent.framework == "crewai"
    assert agent.conflicts == []


def test_falls_back_to_runtime_destination_when_no_hint() -> None:
    events = [
        normalize_one({"type": "RuntimeEvent", "host_id": "h", "pid": 1, "destination": "api.openai.com", "timestamp": _now()}),
    ]
    cluster = EventCluster(events=events, confidence=0.4)
    agent = build_agent_from_cluster(cluster, agent_id="a-3")
    agent = classify_agent(agent, cluster, SOURCE_PRIORITY)
    assert agent.framework == "direct_sdk_or_agentic_llm"


def test_mcp_detected_from_config_files() -> None:
    events = [
        normalize_one({"type": "CapabilityHint", "repo": "r", "imports": [], "config_files": [".cursor/mcp.json"], "timestamp": _now()}),
    ]
    cluster = EventCluster(events=events, confidence=0.5)
    agent = build_agent_from_cluster(cluster, agent_id="a-4")
    agent = classify_agent(agent, cluster, SOURCE_PRIORITY)
    assert agent.framework == "mcp"


def test_conflict_lowers_correlation_confidence() -> None:
    events = [
        normalize_one({"type": "CapabilityHint", "repo": "r", "framework_hint": "langchain", "timestamp": _now()}),
        normalize_one({"type": "RuntimeEvent", "host_id": "h", "pid": 1, "framework_hint": "crewai", "timestamp": _now()}),
    ]
    cluster = EventCluster(events=events, confidence=0.9)
    agent = build_agent_from_cluster(cluster, agent_id="a-5")
    before = agent.correlation_confidence
    classify_agent(agent, cluster, SOURCE_PRIORITY)
    assert agent.correlation_confidence < before
