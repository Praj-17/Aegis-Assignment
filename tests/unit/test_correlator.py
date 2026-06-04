"""Correlator edge cases — the heart of the assignment.

Covers:
    - partial keys join into one cluster
    - duplicate dedup
    - out-of-order arrival
    - multiple agents on the same host (different pids)
    - conflicting framework_hint surfaces a conflict but events still merge
    - time-window boundary (±5 minute tolerance)
    - correlation confidence reflects key strength
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aegis_discovery.correlation.correlator import correlate
from aegis_discovery.normalize.normalizer import normalize_one


def _ts(offset_s: int = 0) -> str:
    base = datetime(2026, 6, 3, 10, 0, 0, tzinfo=timezone.utc)
    return (base + timedelta(seconds=offset_s)).isoformat()


def _events(*items):
    return [normalize_one(i) for i in items]


def test_partial_keys_merge_into_one_cluster() -> None:
    events = _events(
        {"type": "RuntimeEvent", "host_id": "h-1", "pid": 100, "destination": "api.openai.com", "timestamp": _ts(0)},
        {"type": "NHIManifest", "nhi_id": "role-x", "workload_id": "w-1", "host_id": "h-1", "timestamp": _ts(2)},
        {"type": "CapabilityHint", "repo": "r-1", "workload_id": "w-1", "framework_hint": "langchain", "timestamp": _ts(-30)},
        {"type": "SaaSAuditEvent", "nhi_id": "role-x", "data_classes": ["PHI"], "timestamp": _ts(5)},
    )
    clusters = correlate(events)
    assert len(clusters) == 1
    assert clusters[0].confidence > 0.7


def test_duplicate_events_are_deduped() -> None:
    same = {"type": "RuntimeEvent", "host_id": "h-2", "pid": 200, "destination": "api.openai.com", "timestamp": _ts(0)}
    events = _events(same, same, same)
    clusters = correlate(events)
    assert len(clusters) == 1
    assert len(clusters[0].events) == 1


def test_out_of_order_events_still_correlate() -> None:
    events = _events(
        {"type": "SaaSAuditEvent", "nhi_id": "role-z", "data_classes": ["PII"], "timestamp": _ts(60)},
        {"type": "RuntimeEvent", "host_id": "h-3", "pid": 300, "nhi_id": "role-z", "timestamp": _ts(0)},
        {"type": "NHIManifest", "nhi_id": "role-z", "workload_id": "w-3", "timestamp": _ts(30)},
    )
    clusters = correlate(events)
    assert len(clusters) == 1
    assert [e.event_id for e in clusters[0].events] == sorted(
        [e.event_id for e in clusters[0].events],
        key=lambda eid: next(
            ev.timestamp for ev in clusters[0].events if ev.event_id == eid
        ),
    )


def test_multiple_agents_on_same_host_with_different_pids() -> None:
    events = _events(
        {"type": "RuntimeEvent", "host_id": "h-5", "pid": 500, "destination": "api.openai.com", "timestamp": _ts(0)},
        {"type": "RuntimeEvent", "host_id": "h-5", "pid": 600, "destination": "api.anthropic.com", "timestamp": _ts(10)},
    )
    clusters = correlate(events)
    assert len(clusters) == 2


def test_conflicting_framework_hint_still_merges_via_shared_key() -> None:
    events = _events(
        {"type": "CapabilityHint", "repo": "r-x", "workload_id": "w-x", "framework_hint": "langchain", "timestamp": _ts(0)},
        {"type": "RuntimeEvent", "workload_id": "w-x", "host_id": "h-x", "pid": 1, "framework_hint": "crewai", "timestamp": _ts(20)},
    )
    clusters = correlate(events)
    assert len(clusters) == 1
    # The correlator merges; the classifier is what records the conflict.
    fhints = {e.framework_hint for e in clusters[0].events if e.framework_hint}
    assert fhints == {"langchain", "crewai"}


def test_time_window_boundary_inside() -> None:
    """Two RuntimeEvents on same host (no pid) within 5min should merge."""

    events = _events(
        {"type": "RuntimeEvent", "host_id": "h-tw", "destination": "api.openai.com", "timestamp": _ts(0)},
        {"type": "RuntimeEvent", "host_id": "h-tw", "destination": "api.anthropic.com", "timestamp": _ts(60 * 4)},
    )
    clusters = correlate(events, time_window_seconds=300)
    assert len(clusters) == 1


def test_time_window_boundary_outside() -> None:
    """Two RuntimeEvents on same host (no pid) > 5min apart should NOT merge."""

    events = _events(
        {"type": "RuntimeEvent", "host_id": "h-tw2", "destination": "api.openai.com", "timestamp": _ts(0)},
        {"type": "RuntimeEvent", "host_id": "h-tw2", "destination": "api.anthropic.com", "timestamp": _ts(60 * 10)},
    )
    clusters = correlate(events, time_window_seconds=300)
    assert len(clusters) == 2


def test_correlation_confidence_scales_with_key_strength() -> None:
    weak = _events(
        {"type": "RuntimeEvent", "host_id": "h-w", "destination": "api.openai.com", "timestamp": _ts(0)},
        {"type": "RuntimeEvent", "host_id": "h-w", "destination": "api.anthropic.com", "timestamp": _ts(30)},
    )
    strong = _events(
        {"type": "RuntimeEvent", "host_id": "h-s", "pid": 1, "nhi_id": "role-s", "timestamp": _ts(0)},
        {"type": "NHIManifest", "nhi_id": "role-s", "workload_id": "w-s", "host_id": "h-s", "timestamp": _ts(5)},
        {"type": "CapabilityHint", "workload_id": "w-s", "imports": ["langchain"], "timestamp": _ts(-10)},
    )
    weak_clusters = correlate(weak)
    strong_clusters = correlate(strong)
    assert strong_clusters[0].confidence > weak_clusters[0].confidence


def test_empty_input_returns_no_clusters() -> None:
    assert correlate([]) == []
