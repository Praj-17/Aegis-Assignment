"""End-to-end pipeline orchestration.

Wires together:
    ingest -> normalize -> persist events -> correlate -> build agents
    -> fingerprint -> risk rules -> score -> policy -> persist agents.

Two entry points:
    `run_full_pipeline`     — re-correlate everything currently in storage.
    `ingest_and_process`    — add new raw events to storage, then re-run.
"""

from __future__ import annotations

import hashlib
from typing import Any

from aegis_discovery.config.settings import Settings
from aegis_discovery.correlation.agent_builder import build_agent_from_cluster
from aegis_discovery.correlation.correlator import correlate
from aegis_discovery.fingerprint.classifier import classify_agent
from aegis_discovery.ingestion.ingestor import parse_batch
from aegis_discovery.normalize.normalizer import normalize_one
from aegis_discovery.policy.recommender import attach_policy
from aegis_discovery.risk import rules as risk_rules
from aegis_discovery.risk.scorer import score_agent
from aegis_discovery.schemas import Agent, CanonicalEvent
from aegis_discovery.storage.database import Repository


def _stable_agent_id(cluster_events: list[CanonicalEvent]) -> str:
    """Derive a stable agent_id so re-running the pipeline doesn't rename agents.

    Priority: nhi_id > workload_id > (host_id, pid) > repo > hash of sorted event_ids.
    """

    for ev in cluster_events:
        if ev.nhi_id:
            return f"agent-nhi-{_short_slug(ev.nhi_id)}"
    for ev in cluster_events:
        if ev.workload_id:
            return f"agent-wl-{_short_slug(ev.workload_id)}"
    for ev in cluster_events:
        if ev.host_id and ev.pid is not None:
            return f"agent-hp-{_short_slug(f'{ev.host_id}-{ev.pid}')}"
    for ev in cluster_events:
        if ev.repo:
            return f"agent-repo-{_short_slug(ev.repo)}"
    joined = ",".join(sorted(e.event_id for e in cluster_events))
    return f"agent-{hashlib.sha1(joined.encode()).hexdigest()[:10]}"


def _short_slug(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)
    return safe[:24].strip("-").lower() or hashlib.sha1(value.encode()).hexdigest()[:8]


def normalize_and_store(repo: Repository, payload: Any) -> list[CanonicalEvent]:
    """Validate -> normalize -> persist. Returns the normalized events written."""

    raws = parse_batch(payload)
    canonicals = [normalize_one(r) for r in raws]
    repo.add_events(canonicals)
    return canonicals


def run_full_pipeline(repo: Repository, settings: Settings) -> list[Agent]:
    """Re-derive agents from every event currently in storage."""

    events = repo.list_events()
    if not events:
        repo.replace_all_agents([])
        return []

    clusters = correlate(
        events,
        time_window_seconds=settings.correlation.time_window_seconds,
        dedup=settings.correlation.duplicate_dedup,
    )

    agents: list[Agent] = []
    for cluster in clusters:
        agent_id = _stable_agent_id(cluster.events)
        agent = build_agent_from_cluster(cluster, agent_id=agent_id)
        agent = classify_agent(
            agent,
            cluster,
            source_priority=settings.correlation.source_priority_for_framework,
        )

        findings = risk_rules.evaluate(
            agent,
            external_hosts=settings.risk.external_llm_destinations,
            sensitive_classes=settings.risk.sensitive_data_classes,
        )
        agent.findings = findings

        agent = score_agent(agent, settings, findings=findings)
        agent = attach_policy(agent, settings, findings=findings)

        agents.append(agent)

    repo.replace_all_agents(agents)
    return agents


def ingest_and_process(repo: Repository, settings: Settings, payload: Any) -> list[Agent]:
    """High-level entry: ingest a batch of raw events and re-run the pipeline."""

    normalize_and_store(repo, payload)
    return run_full_pipeline(repo, settings)
