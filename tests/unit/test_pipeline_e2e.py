"""End-to-end pipeline test using the in-memory repository."""

from __future__ import annotations

import json
from pathlib import Path

from aegis_discovery.config.settings import get_settings, reset_settings_cache
from aegis_discovery.pipeline import ingest_and_process
from aegis_discovery.storage.database import InMemoryRepository


SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def test_scenario_full_produces_two_agents() -> None:
    reset_settings_cache()
    payload = json.loads((SAMPLES / "scenario_full.json").read_text(encoding="utf-8"))
    repo = InMemoryRepository()
    agents = ingest_and_process(repo, get_settings(), payload)

    assert len(agents) == 2
    ids = {a.workload_id for a in agents}
    assert ids == {"claims-processor", "marketing-summary"}

    claims = next(a for a in agents if a.workload_id == "claims-processor")
    assert claims.risk_tier.value == "HIGH"
    assert claims.recommended_policy == "phi-handling-v3"
    assert any("PHI" in e for e in claims.evidence)
    assert any(f.rule_id.startswith("R1") for f in claims.findings)
    assert any(f.rule_id.startswith("R2") for f in claims.findings)
    assert any(f.rule_id.startswith("R3") for f in claims.findings)


def test_edge_cases_handled_without_errors() -> None:
    reset_settings_cache()
    payload = json.loads((SAMPLES / "edge_cases.json").read_text(encoding="utf-8"))
    repo = InMemoryRepository()
    agents = ingest_and_process(repo, get_settings(), payload)
    # We don't pin exact counts, just that the run is stable and produces agents.
    assert len(agents) >= 2
    for a in agents:
        assert a.correlation_confidence > 0
