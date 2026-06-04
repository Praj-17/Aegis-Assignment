"""Risk rules. Each rule returns a RiskFinding (or None) for a given Agent.

The assignment requires at least three rules; we implement those three plus
keep room for more. Every finding carries explainable evidence so we never
return a number without a "because".
"""

from __future__ import annotations

from aegis_discovery.risk.baseline import baseline_for
from aegis_discovery.schemas import Agent, RiskFinding, Severity


def _is_external_destination(dest: str, external_hosts: list[str]) -> bool:
    if not dest:
        return False
    d = dest.lower()
    return any(host.lower() in d for host in external_hosts)


def _agent_uses_external_llm(agent: Agent, external_hosts: list[str]) -> tuple[bool, str | None]:
    for dest in agent.destinations:
        if _is_external_destination(dest, external_hosts):
            return True, dest
    if agent.provider and agent.provider.lower() in {
        "anthropic",
        "openai",
        "cohere",
        "mistral",
        "google",
    }:
        return True, f"provider={agent.provider}"
    if "external_llm_call" in agent.tools:
        return True, "external_llm_call tool"
    return False, None


def rule_phi_to_external_llm(
    agent: Agent,
    external_hosts: list[str],
    sensitive_classes: list[str],
) -> RiskFinding | None:
    """Rule 1: PHI (or other sensitive) data + external LLM destination -> HIGH."""

    sensitive_seen = [c for c in agent.data_classes if c.upper() in {s.upper() for s in sensitive_classes}]
    uses_ext, where = _agent_uses_external_llm(agent, external_hosts)
    has_phi = "PHI" in (c.upper() for c in agent.data_classes)
    if has_phi and uses_ext:
        return RiskFinding(
            rule_id="R1_PHI_TO_EXTERNAL_LLM",
            description="Agent processes PHI and calls an external LLM provider.",
            severity=Severity.HIGH,
            evidence=[
                f"Agent data_classes include PHI ({sensitive_seen}).",
                f"Agent egress to external LLM observed: {where}.",
            ],
        )
    # Also fire for sensitive (non-PHI) leaving via external LLM, but at MEDIUM.
    if sensitive_seen and not has_phi and uses_ext:
        return RiskFinding(
            rule_id="R1_SENSITIVE_TO_EXTERNAL_LLM",
            description="Agent processes sensitive data classes and calls an external LLM.",
            severity=Severity.MEDIUM,
            evidence=[
                f"Sensitive data classes seen: {sensitive_seen}.",
                f"Agent egress to external LLM observed: {where}.",
            ],
        )
    return None


def rule_agent_without_aegislib(agent: Agent) -> RiskFinding | None:
    """Rule 2: Agent framework imports detected but no `aegislib` in imports."""

    if not agent.framework:
        return None
    if not agent.imports:
        # No repo scan saw this agent at all -> can't verify SDK usage.
        # Still note it at MEDIUM since the agent is observed but unverified.
        return RiskFinding(
            rule_id="R2_AGENT_NO_REPO_VISIBILITY",
            description="Detected agent framework but no repo scan found — Aegis SDK usage unverifiable.",
            severity=Severity.MEDIUM,
            evidence=[
                f"Framework classified as {agent.framework!r} from runtime/identity signals.",
                "No CapabilityHint (repo scan) was correlated to this agent.",
            ],
        )
    imports_lower = {i.lower() for i in agent.imports}
    if "aegislib" in imports_lower:
        return None
    severity = Severity.HIGH if agent.data_classes else Severity.MEDIUM
    return RiskFinding(
        rule_id="R2_AGENT_NO_AEGISLIB",
        description="Agent framework detected in repo but does not import aegislib.",
        severity=severity,
        evidence=[
            f"Framework: {agent.framework}.",
            f"Imports observed: {sorted(imports_lower)} (no aegislib).",
        ],
    )


def rule_unexpected_tool_use(agent: Agent) -> RiskFinding | None:
    """Rule 3: Agent calls a tool outside its baseline + declared set."""

    baseline = baseline_for(agent.framework)
    declared = {t.lower() for t in agent.imports}  # used as a soft allow-list
    allowed = baseline | declared
    if not allowed and not agent.tools:
        return None

    actual = {t.lower() for t in agent.tools}
    unexpected = sorted(t for t in actual if t not in {a.lower() for a in allowed})
    if not unexpected:
        return None

    # Anything talking to DB-like or filesystem-like tools while having data classes -> HIGH.
    high_risk_markers = {"aurora", "rds", "s3", "secrets", "kms", "filesystem", "shell", "exec"}
    severity = Severity.HIGH if any(
        any(m in u for m in high_risk_markers) for u in unexpected
    ) else Severity.MEDIUM

    return RiskFinding(
        rule_id="R3_UNEXPECTED_TOOL_USE",
        description="Agent invoked a tool/resource outside its baseline.",
        severity=severity,
        evidence=[
            f"Framework baseline: {sorted(baseline) or 'none'}.",
            f"Declared imports/tools: {sorted(declared) or 'none'}.",
            f"Tools observed outside baseline: {unexpected}.",
        ],
    )


def evaluate(
    agent: Agent,
    external_hosts: list[str],
    sensitive_classes: list[str],
) -> list[RiskFinding]:
    """Run every rule against the agent. Returns all firing findings."""

    findings: list[RiskFinding] = []
    for fn in (
        lambda: rule_phi_to_external_llm(agent, external_hosts, sensitive_classes),
        lambda: rule_agent_without_aegislib(agent),
        lambda: rule_unexpected_tool_use(agent),
    ):
        f = fn()
        if f is not None:
            findings.append(f)
    return findings
