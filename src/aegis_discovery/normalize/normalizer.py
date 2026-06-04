"""Map raw, source-specific events into a single CanonicalEvent shape.

The rest of the pipeline never sees a RuntimeEvent or NHIManifest directly.
The normalizer is the only place that knows about source-specific quirks.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from aegis_discovery.schemas import (
    CanonicalEvent,
    RawCapabilityHint,
    RawEvent,
    RawNHIManifest,
    RawRuntimeEvent,
    RawSaaSAuditEvent,
    SourceType,
)


KNOWN_FRAMEWORK_IMPORTS = {
    "langchain": "langchain",
    "langgraph": "langchain",
    "llama_index": "llama_index",
    "llamaindex": "llama_index",
    "crewai": "crewai",
    "autogen": "autogen",
    "semantic_kernel": "semantic_kernel",
    "anthropic": "direct_sdk_or_agentic_llm",
    "openai": "direct_sdk_or_agentic_llm",
}


def _ensure_ts(ts: datetime | None) -> datetime:
    if ts is None:
        return datetime.now(timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _fingerprint(payload: dict[str, Any]) -> str:
    """Stable hash so we can detect duplicate events from the same source."""

    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _new_event_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def normalize_runtime(raw: RawRuntimeEvent) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=raw.event_id or _new_event_id("rt"),
        source=SourceType.RUNTIME,
        nhi_id=raw.nhi_id,
        host_id=raw.host_id,
        pid=raw.pid,
        workload_id=raw.workload_id,
        provider=raw.provider,
        model=raw.model,
        framework_hint=raw.framework_hint,
        tools=list(raw.tools_called or []),
        destination=raw.destination,
        timestamp=_ensure_ts(raw.timestamp),
        fingerprint_hash=_fingerprint(raw.model_dump(mode="json")),
        raw=raw.model_dump(mode="json"),
    )


def normalize_nhi(raw: RawNHIManifest) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=raw.event_id or _new_event_id("nhi"),
        source=SourceType.NHI,
        nhi_id=raw.nhi_id,
        host_id=raw.host_id,
        workload_id=raw.workload_id,
        provider=raw.provider,
        model=raw.model,
        permissions=list(raw.permissions or []),
        timestamp=_ensure_ts(raw.timestamp),
        fingerprint_hash=_fingerprint(raw.model_dump(mode="json")),
        raw=raw.model_dump(mode="json"),
    )


def normalize_capability(raw: RawCapabilityHint) -> CanonicalEvent:
    imports = list(raw.imports or [])
    framework_hint = raw.framework_hint
    if not framework_hint:
        # Derive from imports if the scanner didn't already classify.
        for imp in imports:
            key = imp.lower().split(".")[0]
            if key in KNOWN_FRAMEWORK_IMPORTS:
                framework_hint = KNOWN_FRAMEWORK_IMPORTS[key]
                break
        else:
            # mcp.json or .cursor/ in the config file list = MCP-enabled agent.
            cfgs = [c.lower() for c in (raw.config_files or [])]
            if any("mcp.json" in c or ".cursor" in c for c in cfgs):
                framework_hint = "mcp"

    return CanonicalEvent(
        event_id=raw.event_id or _new_event_id("cap"),
        source=SourceType.CAPABILITY,
        repo=raw.repo,
        workload_id=raw.workload_id,
        framework_hint=framework_hint,
        provider=raw.provider,
        model=raw.model,
        imports=imports,
        config_files=list(raw.config_files or []),
        tools=list(raw.declared_tools or []),
        timestamp=_ensure_ts(raw.timestamp),
        fingerprint_hash=_fingerprint(raw.model_dump(mode="json")),
        raw=raw.model_dump(mode="json"),
    )


def normalize_saas(raw: RawSaaSAuditEvent) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=raw.event_id or _new_event_id("saas"),
        source=SourceType.SAAS,
        nhi_id=raw.nhi_id,
        host_id=raw.host_id,
        workload_id=raw.workload_id,
        tools=list(raw.tools_called or []),
        data_classes=list(raw.data_classes or []),
        destination=raw.destination,
        timestamp=_ensure_ts(raw.timestamp),
        fingerprint_hash=_fingerprint(raw.model_dump(mode="json")),
        raw=raw.model_dump(mode="json"),
    )


_DISPATCH = {
    "RuntimeEvent": (RawRuntimeEvent, normalize_runtime),
    "NHIManifest": (RawNHIManifest, normalize_nhi),
    "CapabilityHint": (RawCapabilityHint, normalize_capability),
    "SaaSAuditEvent": (RawSaaSAuditEvent, normalize_saas),
}


def normalize_one(raw: RawEvent | dict[str, Any]) -> CanonicalEvent:
    """Normalize a single raw event (model or dict) to CanonicalEvent."""

    if isinstance(raw, dict):
        type_ = raw.get("type")
        if type_ not in _DISPATCH:
            raise ValueError(f"Unknown event type: {type_!r}. Expected one of {list(_DISPATCH)}.")
        model_cls, fn = _DISPATCH[type_]
        return fn(model_cls.model_validate(raw))

    # Pydantic model branch.
    type_ = raw.type
    _, fn = _DISPATCH[type_]
    return fn(raw)  # type: ignore[arg-type]


def normalize_many(raws: list[RawEvent | dict[str, Any]]) -> list[CanonicalEvent]:
    return [normalize_one(r) for r in raws]
