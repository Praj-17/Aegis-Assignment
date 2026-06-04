"""Policy recommender: mapping + evidence chain."""

from __future__ import annotations

from aegis_discovery.config.settings import get_settings, reset_settings_cache
from aegis_discovery.policy.recommender import recommend
from aegis_discovery.schemas import Agent


def test_phi_external_maps_to_phi_handling_v3() -> None:
    reset_settings_cache()
    s = get_settings()
    a = Agent(
        agent_id="a",
        data_classes=["PHI"],
        destinations=["api.anthropic.com"],
        correlation_confidence=0.9,
    )
    rec = recommend(a, s)
    assert rec is not None
    assert rec.policy == "phi-handling-v3"
    assert any("PHI" in e for e in rec.evidence)


def test_external_only_maps_to_egress_redact() -> None:
    reset_settings_cache()
    s = get_settings()
    a = Agent(
        agent_id="a",
        data_classes=["marketing_copy"],
        destinations=["api.openai.com"],
        correlation_confidence=0.8,
    )
    rec = recommend(a, s)
    assert rec is not None
    assert rec.policy == "external-egress-redact"


def test_any_llm_falls_back_to_audit() -> None:
    reset_settings_cache()
    s = get_settings()
    a = Agent(agent_id="a", provider="anthropic", correlation_confidence=0.7)
    rec = recommend(a, s)
    assert rec is not None
    assert rec.policy == "audit-all-llm-calls"


def test_no_llm_signals_returns_none() -> None:
    reset_settings_cache()
    s = get_settings()
    a = Agent(agent_id="a", correlation_confidence=0.6)
    rec = recommend(a, s)
    assert rec is None
