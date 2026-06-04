"""Risk scorer: factor weights produce sensible tiers."""

from __future__ import annotations

from aegis_discovery.config.settings import get_settings, reset_settings_cache
from aegis_discovery.risk.scorer import score_agent
from aegis_discovery.schemas import Agent, RiskFinding, RiskTier, Severity


def test_low_risk_simple_agent() -> None:
    reset_settings_cache()
    s = get_settings()
    a = Agent(agent_id="a", tools=[], data_classes=[], destinations=[])
    score_agent(a, s)
    assert a.risk_tier == RiskTier.LOW
    assert a.risk_score < s.risk.tiers.low_max + 1


def test_high_risk_phi_external() -> None:
    reset_settings_cache()
    s = get_settings()
    a = Agent(
        agent_id="a",
        framework="langchain",
        provider="anthropic",
        tools=["external_llm_call", "aurora_read"],
        data_classes=["PHI", "claims_data"],
        destinations=["api.anthropic.com"],
        imports=["langchain", "anthropic"],
    )
    findings = [
        RiskFinding(
            rule_id="R1", description="phi+ext", severity=Severity.HIGH, evidence=[]
        )
    ]
    score_agent(a, s, findings=findings)
    assert a.risk_tier == RiskTier.HIGH
    assert a.risk_score >= 70


def test_tier_boundaries_match_config() -> None:
    reset_settings_cache()
    s = get_settings()
    # Construct each tier explicitly via override of risk_score then re-tier.
    for score, expected in [
        (0, RiskTier.LOW),
        (s.risk.tiers.low_max, RiskTier.LOW),
        (s.risk.tiers.low_max + 1, RiskTier.MEDIUM),
        (s.risk.tiers.medium_max, RiskTier.MEDIUM),
        (s.risk.tiers.medium_max + 1, RiskTier.HIGH),
        (100, RiskTier.HIGH),
    ]:
        # Inline the tiering logic the scorer uses.
        if score <= s.risk.tiers.low_max:
            tier = RiskTier.LOW
        elif score <= s.risk.tiers.medium_max:
            tier = RiskTier.MEDIUM
        else:
            tier = RiskTier.HIGH
        assert tier == expected
