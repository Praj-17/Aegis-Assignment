"""Ingestion layer: accept raw events (single or batch, dicts or models),
validate against the union of raw schemas, return list of typed raw events.

Persistence and pipeline orchestration happen elsewhere; this is just the
"front door" that turns untyped JSON into typed RawEvent objects.
"""

from __future__ import annotations

from typing import Any

from aegis_discovery.schemas import (
    RawCapabilityHint,
    RawEvent,
    RawNHIManifest,
    RawRuntimeEvent,
    RawSaaSAuditEvent,
)


_RAW_BY_TYPE = {
    "RuntimeEvent": RawRuntimeEvent,
    "NHIManifest": RawNHIManifest,
    "CapabilityHint": RawCapabilityHint,
    "SaaSAuditEvent": RawSaaSAuditEvent,
}


class IngestionError(ValueError):
    pass


def parse_event(payload: dict[str, Any]) -> RawEvent:
    """Validate a single raw event dict into the right RawEvent subtype."""

    if not isinstance(payload, dict):
        raise IngestionError(f"Each event must be an object, got {type(payload).__name__}.")
    type_ = payload.get("type")
    if type_ not in _RAW_BY_TYPE:
        raise IngestionError(
            f"Unknown event type {type_!r}. Expected one of {list(_RAW_BY_TYPE)}."
        )
    model_cls = _RAW_BY_TYPE[type_]
    try:
        return model_cls.model_validate(payload)
    except Exception as exc:  # pydantic.ValidationError or others
        raise IngestionError(f"Invalid {type_} payload: {exc}") from exc


def parse_batch(payload: Any) -> list[RawEvent]:
    """Accept either a list of events or a dict with an `events` key."""

    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and "events" in payload:
        items = payload["events"]
    elif isinstance(payload, dict) and "type" in payload:
        # Single event wrapped as a dict.
        items = [payload]
    else:
        raise IngestionError(
            "Payload must be a list of events, or an object with an `events` array."
        )
    if not isinstance(items, list):
        raise IngestionError("`events` must be a list.")
    return [parse_event(item) for item in items]
