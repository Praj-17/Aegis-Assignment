"""Canonical schemas used across the Aegis Discovery pipeline.

The raw inputs from the four sources are intentionally messy and partial.
Everything downstream of the normalizer speaks `CanonicalEvent` and `Agent`,
so the rest of the system never sees source-specific shapes.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# Raw input event types (what the 4 sources actually emit).
# We keep these permissive because real-world signals are partial.


class RawRuntimeEvent(BaseModel):
    """eBPF / network telemetry. Usually rich on host_id+pid+destination, weak on identity."""

    type: Literal["RuntimeEvent"] = "RuntimeEvent"
    event_id: str | None = None
    host_id: str | None = None
    pid: int | None = None
    workload_id: str | None = None
    nhi_id: str | None = None
    destination: str | None = None
    tools_called: list[str] = Field(default_factory=list)
    framework_hint: str | None = None
    provider: str | None = None
    model: str | None = None
    timestamp: datetime | None = None
    model_config = ConfigDict(extra="allow")


class RawNHIManifest(BaseModel):
    """Cloud IAM / identity inventory. Strong on nhi_id+workload_id."""

    type: Literal["NHIManifest"] = "NHIManifest"
    event_id: str | None = None
    nhi_id: str | None = None
    workload_id: str | None = None
    host_id: str | None = None
    provider: str | None = None
    model: str | None = None
    permissions: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None
    model_config = ConfigDict(extra="allow")


class RawCapabilityHint(BaseModel):
    """Repo scan findings. Strong on repo+framework_hint+imports."""

    type: Literal["CapabilityHint"] = "CapabilityHint"
    event_id: str | None = None
    repo: str | None = None
    workload_id: str | None = None
    framework_hint: str | None = None
    provider: str | None = None
    model: str | None = None
    imports: list[str] = Field(default_factory=list)
    config_files: list[str] = Field(default_factory=list)
    declared_tools: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None
    model_config = ConfigDict(extra="allow")


class RawSaaSAuditEvent(BaseModel):
    """SaaS platform audit logs. Strong on data_classes, tools_called, nhi_id."""

    type: Literal["SaaSAuditEvent"] = "SaaSAuditEvent"
    event_id: str | None = None
    nhi_id: str | None = None
    workload_id: str | None = None
    host_id: str | None = None
    tools_called: list[str] = Field(default_factory=list)
    data_classes: list[str] = Field(default_factory=list)
    destination: str | None = None
    timestamp: datetime | None = None
    model_config = ConfigDict(extra="allow")


RawEvent = RawRuntimeEvent | RawNHIManifest | RawCapabilityHint | RawSaaSAuditEvent


# Canonical event: every raw event maps into this shape.


class SourceType(str, Enum):
    RUNTIME = "RuntimeEvent"
    NHI = "NHIManifest"
    CAPABILITY = "CapabilityHint"
    SAAS = "SaaSAuditEvent"


class CanonicalEvent(BaseModel):
    """The shape every downstream component speaks. Missing fields stay None / []."""

    event_id: str
    source: SourceType
    nhi_id: str | None = None
    host_id: str | None = None
    pid: int | None = None
    workload_id: str | None = None
    repo: str | None = None
    provider: str | None = None
    model: str | None = None
    framework_hint: str | None = None
    tools: list[str] = Field(default_factory=list)
    data_classes: list[str] = Field(default_factory=list)
    destination: str | None = None
    imports: list[str] = Field(default_factory=list)
    config_files: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    timestamp: datetime
    fingerprint_hash: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


# Risk + Policy


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RiskFinding(BaseModel):
    rule_id: str
    description: str
    severity: Severity
    evidence: list[str] = Field(default_factory=list)


class PolicyRecommendation(BaseModel):
    policy: str
    confidence: float
    evidence: list[str] = Field(default_factory=list)


class FrameworkConflict(BaseModel):
    """Records that two events disagreed about framework_hint."""

    field: str
    values: list[str]
    winning_source: str
    note: str


class Agent(BaseModel):
    """The canonical Agent record produced by the pipeline."""

    agent_id: str
    nhi_id: str | None = None
    workload_id: str | None = None
    host_id: str | None = None
    pid: int | None = None
    repo: str | None = None
    framework: str | None = None
    provider: str | None = None
    model: str | None = None
    data_classes: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    destinations: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)

    risk_score: int = 0
    risk_tier: RiskTier = RiskTier.LOW
    risk_factors: dict[str, float] = Field(default_factory=dict)
    findings: list[RiskFinding] = Field(default_factory=list)

    recommended_policy: str | None = None
    policy_confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)

    correlation_confidence: float = 0.0
    conflicts: list[FrameworkConflict] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)
    first_seen: datetime | None = None
    last_seen: datetime | None = None


class IngestResponse(BaseModel):
    accepted_events: int
    new_or_updated_agents: int
    agents: list[Agent]


class GraphNode(BaseModel):
    id: str
    type: str
    label: str


class GraphEdge(BaseModel):
    source: str
    target: str
    label: str | None = None


class AgentGraph(BaseModel):
    agent_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
