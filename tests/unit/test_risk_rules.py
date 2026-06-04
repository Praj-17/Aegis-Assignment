"""Tests for the three required risk rules."""

from __future__ import annotations

from aegis_discovery.risk.rules import (
    rule_agent_without_aegislib,
    rule_phi_to_external_llm,
    rule_unexpected_tool_use,
)
from aegis_discovery.schemas import Agent, Severity


EXTERNAL_HOSTS = ["api.anthropic.com", "api.openai.com"]
SENSITIVE = ["PHI", "PCI", "credentials", "claims_data"]


def test_r1_phi_external_llm_fires_high() -> None:
    a = Agent(
        agent_id="a",
        data_classes=["PHI"],
        destinations=["api.anthropic.com"],
    )
    f = rule_phi_to_external_llm(a, EXTERNAL_HOSTS, SENSITIVE)
    assert f is not None
    assert f.severity == Severity.HIGH


def test_r1_no_phi_no_external_returns_none() -> None:
    a = Agent(agent_id="a", data_classes=["marketing_copy"], destinations=[])
    f = rule_phi_to_external_llm(a, EXTERNAL_HOSTS, SENSITIVE)
    assert f is None


def test_r2_framework_without_aegislib_high_when_data_present() -> None:
    a = Agent(
        agent_id="a",
        framework="langchain",
        imports=["langchain", "anthropic"],
        data_classes=["PHI"],
    )
    f = rule_agent_without_aegislib(a)
    assert f is not None
    assert f.severity == Severity.HIGH


def test_r2_framework_with_aegislib_returns_none() -> None:
    a = Agent(
        agent_id="a",
        framework="langchain",
        imports=["langchain", "aegislib"],
    )
    assert rule_agent_without_aegislib(a) is None


def test_r2_no_repo_visibility_medium() -> None:
    a = Agent(agent_id="a", framework="langchain", imports=[])
    f = rule_agent_without_aegislib(a)
    assert f is not None
    assert f.severity == Severity.MEDIUM


def test_r3_unexpected_tool_use_fires_high_for_db_tools() -> None:
    a = Agent(
        agent_id="a",
        framework="langchain",
        tools=["aurora_read"],
        imports=["langchain"],
    )
    f = rule_unexpected_tool_use(a)
    assert f is not None
    assert f.severity == Severity.HIGH


def test_r3_returns_none_for_baseline_tools() -> None:
    a = Agent(
        agent_id="a",
        framework="langchain",
        tools=["external_llm_call", "search"],
        imports=["langchain"],
    )
    assert rule_unexpected_tool_use(a) is None
