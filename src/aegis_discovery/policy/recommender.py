"""Policy recommendation with evidence chain.

Decision order (most specific first):
    1. PHI + external LLM       -> phi-handling-v3
    2. External LLM only        -> external-egress-redact
    3. Any LLM usage at all     -> audit-all-llm-calls

Every recommendation returns the evidence used to reach it, plus a confidence
that incorporates both the rule strength and the underlying correlation
confidence (so an uncertain merge gives a hedged recommendation).
"""

from __future__ import annotations

from aegis_discovery.config.settings import Settings
from aegis_discovery.schemas import Agent, PolicyRecommendation, RiskFinding


def _has_phi(agent: Agent) -> bool:
    return any(c.upper() == "PHI" for c in agent.data_classes)


def _uses_external_llm(agent: Agent, external_hosts: list[str]) -> tuple[bool, list[str]]:
    """Strict: requires evidence of actual external egress.

    A provider name on its own (`provider=anthropic`) is *not* enough — that
    just signals "we use an LLM SDK". For external policy we need a confirmed
    egress destination or a tool call literally named `external_llm_call`.
    """

    matches: list[str] = []
    for dest in agent.destinations:
        if dest and any(h.lower() in dest.lower() for h in external_hosts):
            matches.append(dest)
    if "external_llm_call" in agent.tools:
        matches.append("external_llm_call tool observed")
    return bool(matches), matches


def _uses_any_llm(agent: Agent) -> bool:
    """Any LLM usage at all — including just a known provider name in the SDK."""

    if agent.provider and agent.provider.lower() in {
        "anthropic",
        "openai",
        "cohere",
        "mistral",
        "google",
    }:
        return True
    if "external_llm_call" in agent.tools:
        return True
    return bool(agent.model)


def recommend(
    agent: Agent,
    settings: Settings,
    findings: list[RiskFinding] | None = None,
) -> PolicyRecommendation | None:
    ext = settings.risk.external_llm_destinations
    findings = findings or []

    phi = _has_phi(agent)
    uses_ext, ext_evidence = _uses_external_llm(agent, ext)
    any_llm = _uses_any_llm(agent) or uses_ext

    base_conf = max(0.5, min(1.0, agent.correlation_confidence + 0.2))

    if phi and uses_ext:
        evidence = [
            "Agent processes PHI (data_classes includes PHI).",
            f"Agent calls external LLM provider(s): {ext_evidence}.",
        ]
        if any(f.rule_id.startswith("R2") for f in findings):
            evidence.append("Agent does not use aegislib (per repo scan).")
        return PolicyRecommendation(
            policy="phi-handling-v3",
            confidence=round(min(1.0, base_conf + 0.1), 3),
            evidence=evidence,
        )

    if uses_ext:
        return PolicyRecommendation(
            policy="external-egress-redact",
            confidence=round(base_conf, 3),
            evidence=[f"Agent egresses to external LLM(s): {ext_evidence}."]
            + (
                ["Sensitive data classes present: " + str(agent.data_classes)]
                if agent.data_classes
                else []
            ),
        )

    if any_llm:
        return PolicyRecommendation(
            policy="audit-all-llm-calls",
            confidence=round(max(0.55, base_conf - 0.1), 3),
            evidence=[
                "Agent shows LLM usage signals (provider/tool) without confirmed external egress."
            ],
        )

    return None


def attach_policy(
    agent: Agent,
    settings: Settings,
    findings: list[RiskFinding] | None = None,
) -> Agent:
    rec = recommend(agent, settings, findings)
    if rec is None:
        return agent
    agent.recommended_policy = rec.policy
    agent.policy_confidence = rec.confidence
    agent.evidence = rec.evidence
    return agent
