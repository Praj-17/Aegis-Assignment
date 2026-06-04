"""Deterministic rule-based fingerprint classifier.

Classifies an agent's framework using:
    - Repo imports (e.g. langchain, crewai, llama_index)
    - Config files (mcp.json, .cursor/)
    - Runtime destinations (api.anthropic.com, api.openai.com)
    - Source-priority resolution when events disagree on `framework_hint`.

Source priority: a repo scan (CapabilityHint) sees actual `import` statements,
so it's more authoritative than a runtime guess. We resolve conflicts using
the priority list in `config.yml` (CapabilityHint > NHIManifest > RuntimeEvent
> SaaSAuditEvent). Disagreements are recorded in `Agent.conflicts` so they're
visible in the evidence chain.

Production evolution: see ARCHITECTURE.md — these rules become weak labels for
a supervised classifier trained on labeled agents, then a learned model
combined with these deterministic checks as guardrails.
"""

from __future__ import annotations

from collections import defaultdict

from aegis_discovery.correlation.correlator import EventCluster
from aegis_discovery.schemas import Agent, CanonicalEvent, FrameworkConflict


# Lowercase substrings -> framework label.
IMPORT_TO_FRAMEWORK = {
    "langchain": "langchain",
    "langgraph": "langchain",
    "llama_index": "llama_index",
    "llamaindex": "llama_index",
    "crewai": "crewai",
    "autogen": "autogen",
    "semantic_kernel": "semantic_kernel",
}

DIRECT_SDK_IMPORTS = {"anthropic", "openai", "cohere", "mistralai", "google.generativeai"}

MCP_CONFIG_FILES = {"mcp.json", ".cursor", ".cursor/", ".mcp/"}

EXTERNAL_LLM_HOSTS = {
    "api.anthropic.com",
    "api.openai.com",
    "api.cohere.ai",
    "api.mistral.ai",
    "generativelanguage.googleapis.com",
}


def _from_imports(imports: list[str]) -> str | None:
    for imp in imports:
        key = imp.lower().split(".")[0]
        if key in IMPORT_TO_FRAMEWORK:
            return IMPORT_TO_FRAMEWORK[key]
    for imp in imports:
        key = imp.lower().split(".")[0]
        if key in DIRECT_SDK_IMPORTS:
            return "direct_sdk_or_agentic_llm"
    return None


def _from_config_files(config_files: list[str]) -> str | None:
    for cfg in config_files:
        c = cfg.lower()
        if any(marker in c for marker in MCP_CONFIG_FILES):
            return "mcp"
    return None


def _from_runtime(events: list[CanonicalEvent]) -> str | None:
    for ev in events:
        if ev.destination and ev.destination.lower() in EXTERNAL_LLM_HOSTS:
            if ev.tools:
                return "direct_sdk_or_agentic_llm"
            return "direct_sdk_or_agentic_llm"
    return None


def _resolve_conflict(
    candidates: dict[str, list[str]],
    source_priority: list[str],
) -> tuple[str, list[str]]:
    """Pick the winning framework from {source: [framework]} using priority."""

    for src in source_priority:
        if src in candidates and candidates[src]:
            return candidates[src][0], candidates[src]
    # Fallback: first available.
    first_src = next(iter(candidates))
    return candidates[first_src][0], candidates[first_src]


def classify_agent(
    agent: Agent,
    cluster: EventCluster,
    source_priority: list[str],
) -> Agent:
    """Set `agent.framework` and record any framework_hint conflicts.

    Strategy:
        1. Collect every framework signal grouped by the source that produced it.
        2. If there's only one distinct value, use it.
        3. Otherwise pick the value from the highest-priority source and record
           the disagreement on the agent.
    """

    by_source: dict[str, list[str]] = defaultdict(list)

    for ev in cluster.events:
        candidate = None

        # Per-event hint first (explicit field).
        if ev.framework_hint:
            candidate = ev.framework_hint
        # Then derive from imports / config files (only applies to capability).
        if not candidate and ev.imports:
            candidate = _from_imports(ev.imports)
        if not candidate and ev.config_files:
            candidate = _from_config_files(ev.config_files)
        # Runtime destination as a weaker signal.
        if not candidate and ev.destination and ev.destination.lower() in EXTERNAL_LLM_HOSTS:
            candidate = "direct_sdk_or_agentic_llm"

        if candidate:
            by_source[ev.source.value].append(candidate.lower())

    if not by_source:
        # No signals — try a last-pass runtime check across the cluster.
        rt = _from_runtime(cluster.events)
        agent.framework = rt
        return agent

    distinct_values = {v for vals in by_source.values() for v in vals}

    if len(distinct_values) == 1:
        agent.framework = distinct_values.pop()
        return agent

    # Conflict: more than one distinct framework label across events.
    winner, _ = _resolve_conflict(by_source, source_priority)
    agent.framework = winner
    agent.conflicts.append(
        FrameworkConflict(
            field="framework_hint",
            values=sorted(distinct_values),
            winning_source=_winning_source(by_source, source_priority),
            note=(
                f"Conflicting framework_hint across events: {sorted(distinct_values)}. "
                f"Resolved to {winner!r} by source priority."
            ),
        )
    )
    # A conflict shouldn't make us 100% confident in correlation.
    agent.correlation_confidence = round(max(0.0, agent.correlation_confidence - 0.1), 3)
    return agent


def _winning_source(by_source: dict[str, list[str]], source_priority: list[str]) -> str:
    for src in source_priority:
        if src in by_source and by_source[src]:
            return src
    return next(iter(by_source))
