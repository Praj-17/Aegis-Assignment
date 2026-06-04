"""Composite 0-100 risk score from four factors: Scope, Sensitivity, Autonomy, Drift.

Each factor is computed independently on a 0-100 scale, then combined with the
weights from `config.yml`. We expose every factor on the Agent so reviewers can
see why a score came out the way it did.

    Scope         breadth of tool / destination access
    Sensitivity   how sensitive the data classes are
    Autonomy      external network egress, unsupervised execution
    Drift         deviation from baseline tool set / no aegislib

Tier mapping (per assignment):
    0-39   LOW
    40-69  MEDIUM
    70-100 HIGH
"""

from __future__ import annotations

from aegis_discovery.config.settings import Settings
from aegis_discovery.risk.baseline import baseline_for
from aegis_discovery.schemas import Agent, RiskFinding, RiskTier, Severity


_SEVERITY_WEIGHT = {Severity.LOW: 25, Severity.MEDIUM: 55, Severity.HIGH: 85}


def _scope_score(agent: Agent) -> float:
    """More tools / more destinations -> higher score, saturating at ~6 of each."""

    tool_count = len(set(agent.tools))
    dest_count = len(set(agent.destinations))
    # Each tool worth ~12 pts, capped at 60; each dest ~15 pts, capped at 40.
    score = min(60, tool_count * 12) + min(40, dest_count * 15)
    return min(100.0, float(score))


def _sensitivity_score(agent: Agent, sensitive_classes: list[str]) -> float:
    if not agent.data_classes:
        return 0.0
    sensitive = {s.upper() for s in sensitive_classes}
    seen = [c.upper() for c in agent.data_classes]
    sensitive_seen = [c for c in seen if c in sensitive]
    # PHI/PCI/credentials are top-tier; anything else sensitive is mid.
    top_tier = {"PHI", "PCI", "CREDENTIALS"}
    if any(s in top_tier for s in sensitive_seen):
        return 100.0
    if sensitive_seen:
        return 70.0
    if seen:
        return 30.0
    return 0.0


def _autonomy_score(agent: Agent, external_hosts: list[str]) -> float:
    score = 0.0
    if any(any(h in (d or "").lower() for h in external_hosts) for d in agent.destinations):
        score += 60
    if "external_llm_call" in agent.tools:
        score += 25
    if agent.framework in {"langchain", "crewai", "autogen"}:
        # Multi-step agentic frameworks imply unsupervised loops.
        score += 25
    return min(100.0, score)


def _drift_score(agent: Agent) -> float:
    baseline = baseline_for(agent.framework)
    if not baseline and not agent.tools:
        return 0.0
    tools = {t.lower() for t in agent.tools}
    allowed = {b.lower() for b in baseline} | {i.lower() for i in agent.imports}
    if not allowed:
        # We saw the framework but have no baseline -> medium drift uncertainty.
        return 40.0
    outside = [t for t in tools if t not in allowed]
    no_sdk_penalty = 0.0
    if agent.framework and agent.imports and "aegislib" not in {i.lower() for i in agent.imports}:
        no_sdk_penalty = 20.0
    return min(100.0, len(outside) * 25.0 + no_sdk_penalty)


def score_agent(
    agent: Agent,
    settings: Settings,
    findings: list[RiskFinding] | None = None,
) -> Agent:
    w = settings.risk.weights
    ext = settings.risk.external_llm_destinations
    sensitive = settings.risk.sensitive_data_classes

    scope = _scope_score(agent)
    sensitivity = _sensitivity_score(agent, sensitive)
    autonomy = _autonomy_score(agent, ext)
    drift = _drift_score(agent)

    composite = (
        scope * w.scope
        + sensitivity * w.sensitivity
        + autonomy * w.autonomy
        + drift * w.drift
    )

    # Findings can nudge the score up so a HIGH rule firing is never a LOW agent.
    if findings:
        max_sev = max((_SEVERITY_WEIGHT[f.severity] for f in findings), default=0)
        composite = max(composite, max_sev * 0.85)

    score = int(round(min(100.0, max(0.0, composite))))

    tiers = settings.risk.tiers
    if score <= tiers.low_max:
        tier = RiskTier.LOW
    elif score <= tiers.medium_max:
        tier = RiskTier.MEDIUM
    else:
        tier = RiskTier.HIGH

    agent.risk_score = score
    agent.risk_tier = tier
    agent.risk_factors = {
        "scope": round(scope, 1),
        "sensitivity": round(sensitivity, 1),
        "autonomy": round(autonomy, 1),
        "drift": round(drift, 1),
    }
    return agent
