"""Normalizer: every raw shape collapses to the same CanonicalEvent shape."""

from __future__ import annotations

from datetime import datetime, timezone

from aegis_discovery.normalize.normalizer import normalize_one
from aegis_discovery.schemas import SourceType


def test_runtime_event_normalizes() -> None:
    raw = {
        "type": "RuntimeEvent",
        "event_id": "rt-1",
        "host_id": "h-1",
        "pid": 100,
        "destination": "api.openai.com",
        "tools_called": ["external_llm_call"],
        "timestamp": "2026-06-03T10:00:00Z",
    }
    e = normalize_one(raw)
    assert e.source == SourceType.RUNTIME
    assert e.host_id == "h-1"
    assert e.pid == 100
    assert e.destination == "api.openai.com"
    assert e.tools == ["external_llm_call"]
    assert e.timestamp.tzinfo is not None


def test_capability_hint_derives_framework_from_imports() -> None:
    raw = {
        "type": "CapabilityHint",
        "repo": "x",
        "imports": ["langchain", "anthropic"],
    }
    e = normalize_one(raw)
    assert e.source == SourceType.CAPABILITY
    assert e.framework_hint == "langchain"


def test_capability_hint_derives_mcp_from_config() -> None:
    raw = {
        "type": "CapabilityHint",
        "repo": "y",
        "imports": [],
        "config_files": [".cursor/mcp.json"],
    }
    e = normalize_one(raw)
    assert e.framework_hint == "mcp"


def test_missing_timestamp_defaults_to_now() -> None:
    raw = {"type": "NHIManifest", "nhi_id": "x"}
    e = normalize_one(raw)
    assert e.timestamp is not None
    # roughly now
    assert abs((datetime.now(timezone.utc) - e.timestamp).total_seconds()) < 5


def test_unknown_type_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        normalize_one({"type": "Nope"})


def test_fingerprint_stable_for_same_payload() -> None:
    raw = {
        "type": "RuntimeEvent",
        "host_id": "h-1",
        "pid": 100,
        "destination": "api.openai.com",
        "timestamp": "2026-06-03T10:00:00Z",
    }
    a = normalize_one(raw)
    b = normalize_one(raw)
    assert a.fingerprint_hash == b.fingerprint_hash
