"""CLI entrypoint: run the pipeline against one or more JSON sample files.

Usage:
    python -m aegis_discovery.cli.run_pipeline samples/scenario_full.json
    python -m aegis_discovery.cli.run_pipeline samples/runtime_events.json \
        samples/nhi_manifests.json samples/capability_hints.json samples/saas_audit_events.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from aegis_discovery.config.settings import get_settings
from aegis_discovery.pipeline import ingest_and_process
from aegis_discovery.storage.database import InMemoryRepository


def _merge_payloads(paths: list[Path]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            events.extend(data)
        elif isinstance(data, dict) and "events" in data:
            events.extend(data["events"])
        elif isinstance(data, dict) and "type" in data:
            events.append(data)
        else:
            raise SystemExit(f"Unrecognized JSON structure in {path}")
    return events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Aegis Discovery pipeline against JSON files.")
    parser.add_argument("files", nargs="+", type=Path, help="One or more JSON files of raw events.")
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output (default: compact).",
    )
    args = parser.parse_args(argv)

    events = _merge_payloads(args.files)
    settings = get_settings()
    repo = InMemoryRepository()
    agents = ingest_and_process(repo, settings, events)

    output = {
        "input_events": len(events),
        "agents": [a.model_dump(mode="json") for a in agents],
    }
    indent = 2 if args.pretty else None
    json.dump(output, sys.stdout, indent=indent, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
