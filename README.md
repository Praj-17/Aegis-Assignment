# Aegis Discovery

A small service that ingests partial agent signals from four sources, correlates them into one canonical Agent record, scores risk, and recommends a policy with evidence.

Architecture, design choices, and limitations live in [ARCHITECTURE.md](ARCHITECTURE.md).

## Setup

```sh
./scripts/set_uv.sh
```

This installs `uv`, creates `.venv`, and installs `requirements.txt`.

## Run API

```sh
./scripts/run_api.sh
```

Then open `http://localhost:8000/` for the single-page UI. Interactive API docs: `http://localhost:8000/docs`.

## Run Pipeline (CLI)

```sh
./scripts/run_pipeline.sh samples/scenario_full.json --pretty
```

Runs the full pipeline against one or more JSON files of raw events and prints the resulting agent records.

## Run Tests

```sh
./scripts/run_tests.sh
```

## Docker

```sh
docker compose up --build
```

Service is exposed on `http://localhost:8000/`.

```sh
curl http://localhost:8000/health
```

## Stop Services

```sh
docker compose down
```

## Sample API Calls

Ingest events and run the pipeline:

```sh
curl -X POST http://localhost:8000/events \
  -H "content-type: application/json" \
  --data @samples/scenario_full.json
```

List agents:

```sh
curl http://localhost:8000/agents | jq
```

Get one agent + its graph:

```sh
curl http://localhost:8000/agents/<agent_id> | jq
curl http://localhost:8000/agents/<agent_id>/graph | jq
```

Reset the store:

```sh
curl -X DELETE http://localhost:8000/events
```

## Layout

```
app.py                  FastAPI app factory + entrypoint (`uvicorn app:app`)
src/aegis_discovery/    Pipeline modules (api routes, ingestion, normalize,
                        correlation, fingerprint, risk, policy, graph, storage)
samples/                Realistic, intentionally partial input files
tests/unit/             Unit tests (correlation edge cases focused)
web/index.html          Single-page UI
scripts/                POSIX shell scripts (uv, api, pipeline, tests)
config.yml              Non-secret settings (correlation, risk, policies)
```
