"""Build a partial Agent from a clustered set of CanonicalEvents.

This collapses many events into one record by:
    - Picking the most informative non-null value for identity fields.
    - Unioning list-valued fields (tools, data_classes, imports, destinations).
    - Recording the events that contributed.

Framework conflict resolution and risk/policy logic happen elsewhere; this
module is only about merging fields.
"""

from __future__ import annotations

import uuid

from aegis_discovery.correlation.correlator import EventCluster
from aegis_discovery.schemas import Agent, CanonicalEvent


def _first_non_null(events: list[CanonicalEvent], attr: str):
    for e in events:
        val = getattr(e, attr, None)
        if val:
            return val
    return None


def _union_list(events: list[CanonicalEvent], attr: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for e in events:
        for item in getattr(e, attr, []) or []:
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


def _new_agent_id() -> str:
    return f"agent-{uuid.uuid4().hex[:8]}"


def build_agent_from_cluster(
    cluster: EventCluster,
    agent_id: str | None = None,
) -> Agent:
    """Collapse a cluster of events into a single Agent."""

    events = cluster.events
    if not events:
        raise ValueError("Cannot build an agent from an empty cluster.")

    destinations = [e.destination for e in events if e.destination]
    destinations_uniq: list[str] = []
    for d in destinations:
        if d not in destinations_uniq:
            destinations_uniq.append(d)

    agent = Agent(
        agent_id=agent_id or _new_agent_id(),
        nhi_id=_first_non_null(events, "nhi_id"),
        workload_id=_first_non_null(events, "workload_id"),
        host_id=_first_non_null(events, "host_id"),
        pid=_first_non_null(events, "pid"),
        repo=_first_non_null(events, "repo"),
        provider=_first_non_null(events, "provider"),
        model=_first_non_null(events, "model"),
        tools=_union_list(events, "tools"),
        data_classes=_union_list(events, "data_classes"),
        imports=_union_list(events, "imports"),
        destinations=destinations_uniq,
        correlation_confidence=round(cluster.confidence, 3),
        source_event_ids=[e.event_id for e in events],
        first_seen=min(e.timestamp for e in events),
        last_seen=max(e.timestamp for e in events),
    )
    return agent
