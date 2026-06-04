# Aegis Discovery — Architecture

This document explains the design choices behind the service: how partial signals from four sources are turned into one canonical Agent record, how risk is computed, and how a policy is recommended with evidence. Execution commands live in [README.md](README.md).

## 1. Problem framing

Aegis sees agents through four lenses, and none of them is complete on its own:

| Source              | Strong on                                   | Blind to                      |
|---------------------|---------------------------------------------|-------------------------------|
| `RuntimeEvent`      | host_id, pid, destination, observed tools   | identity, repo, data classes  |
| `NHIManifest`       | nhi_id, workload_id, permissions            | runtime behavior, repo        |
| `CapabilityHint`    | repo, imports, framework_hint               | runtime, data classes         |
| `SaaSAuditEvent`    | data_classes, nhi_id, tools                 | host/process identity         |

The job of this service is to fuse these partial views into one canonical Agent per real agent, decide what risk that agent poses, and recommend exactly one policy with a defensible evidence chain.

## 2. Pipeline shape

```
raw events  ->  normalize  ->  persist  ->  correlate  ->  build agent
                                                   |
                                                   v
                                       fingerprint -> risk rules
                                                   |
                                                   v
                                          score -> recommend policy
                                                   |
                                                   v
                                              persist agents
                                                   |
                                                   v
                                               API / UI
```

Each box is one module under `src/aegis_discovery/`. The pipeline is intentionally a straight line with no fan-out — every step takes the agent's view of the world a little further, and every step is testable in isolation.

## 3. Canonical schemas

Defined in [src/aegis_discovery/schemas.py](src/aegis_discovery/schemas.py).

- `CanonicalEvent` — every raw shape collapses here. Missing fields stay `None`/`[]`. The rest of the system never sees a `RuntimeEvent` directly.
- `Agent` — the output. Carries identity, framework, risk score + factors + findings, recommended policy + evidence, correlation confidence, and conflicts.
- `RiskFinding`, `PolicyRecommendation`, `AgentGraph` — small auxiliary types.

Why one canonical event type instead of four downstream paths? Because every downstream component (correlator, scorer, recommender) needs the same fields. Forking the data model would mean duplicating that logic four times.

## 4. Normalizer

[src/aegis_discovery/normalize/normalizer.py](src/aegis_discovery/normalize/normalizer.py)

Per-source mappers move fields into the canonical shape, fill defaults (UTC timestamps), and compute a stable content fingerprint (`sha256` of the sorted-key JSON) used for deduplication. Capability hints with no explicit framework get one derived from imports (e.g. `langchain` import -> `langchain`) or config files (`mcp.json` or `.cursor/` -> `mcp`).

## 5. Identity Correlator — the core

[src/aegis_discovery/correlation/correlator.py](src/aegis_discovery/correlation/correlator.py)

Uses **Union-Find (Disjoint Set Union)** over event indices. We build an index for each join key, then union all event indices that share a key. The four required join keys are split into two tiers:

- **Strong keys (merge unconditionally):** `nhi_id`, `(host_id, pid)`, `workload_id`, and `repo`. Each of these is a globally unique identifier in its own namespace, so two events sharing one almost certainly belong to the same agent.
- **Weak key (merge inside the time window):** `host_id` alone. Two events on the same host with no other shared key only merge if they are within ±5 minutes (configurable in `config.yml`) and don't disagree on pid. Without that guard, two unrelated agents on the same host would collapse into one.

This design directly addresses the edge cases the assignment calls out:

| Edge case                            | How it's handled                                                   |
|--------------------------------------|--------------------------------------------------------------------|
| Partial information                  | Each strong key is independent; missing keys are simply not indexed |
| Multiple agents on the same host     | Different pids stay in separate clusters; weak host-only merging is gated on time window and pid agreement |
| Duplicate events                     | Deduped by `(source, fingerprint_hash)` before clustering          |
| Conflicting `framework_hint`         | Events still merge via shared identity keys; the classifier records the conflict and resolves it by source priority |
| Out-of-order arrival                 | Events are sorted by timestamp before clustering, so order of arrival doesn't change results |

### Correlation confidence (bonus)

Each cluster gets a `correlation_confidence` in [0, 1] based on:
- Base of 0.5 for any cluster.
- +0.30 if all events share a single `nhi_id` (strongest).
- +0.20 if all events share a `(host_id, pid)`.
- +0.15 if all events share `workload_id`.
- +0.10 if all events share `repo`.
- +0.05 if they share `host_id` only and no `(host_id, pid)` already matched.
- +0.10 if all events fall inside the time window.

A single-event "cluster" gets 0.4 — we have only one signal so we're modestly confident at best. A framework conflict trims 0.1 off the final score, because conflicts are a sign we merged two things that disagree on something fundamental.

## 6. Agent builder

[src/aegis_discovery/correlation/agent_builder.py](src/aegis_discovery/correlation/agent_builder.py)

Collapses a cluster's events into a single Agent: first-non-null wins for identity scalars, list-valued fields (`tools`, `data_classes`, `imports`, `destinations`) are union'd in first-seen order. `agent_id` is derived deterministically from the strongest identity available (`agent-nhi-<slug>` > `agent-wl-<slug>` > `agent-hp-<host-pid>` > `agent-repo-<slug>`) so re-running the pipeline doesn't churn IDs.

## 7. Fingerprint classifier

[src/aegis_discovery/fingerprint/classifier.py](src/aegis_discovery/fingerprint/classifier.py)

Deterministic rules:
- Repo imports `langchain` / `langgraph` -> LangChain. `crewai` -> CrewAI. `llama_index` -> LlamaIndex. `autogen` / `semantic_kernel` -> their respective frameworks. Imports of just `anthropic`/`openai`/`cohere` SDKs -> `direct_sdk_or_agentic_llm`.
- Config files `mcp.json` or `.cursor/` -> MCP-enabled.
- Runtime destinations matching known external LLM hosts (`api.anthropic.com`, etc.) -> `direct_sdk_or_agentic_llm`.

### Conflict resolution

The assignment doesn't prescribe how to resolve disagreement on `framework_hint`. We use **source priority weighted by trust**: `CapabilityHint` > `NHIManifest` > `RuntimeEvent` > `SaaSAuditEvent`. A repo scan sees actual `import` statements; runtime is more of an inference. The winning source's value is chosen, the disagreement is recorded as a `FrameworkConflict` on the agent (visible in the API and the UI), and `correlation_confidence` is reduced by 0.1.

### Path to a learned classifier

These deterministic rules are also a usable weak-label generator. To evolve to ML:
1. Use the current classifier as labeling-function output on historical events.
2. Train a multi-class classifier (XGBoost or a small transformer) on features extracted from `imports`, `config_files`, runtime call patterns, and `tools_called` sequences.
3. Keep the deterministic rules as a guardrail / sanity check: if the model and rules disagree by a wide margin, flag for human review and feed the decision back into training labels.
4. Watch for label drift as new frameworks emerge; bias the loss toward recall on novel framework classes.

## 8. Risk rules

[src/aegis_discovery/risk/rules.py](src/aegis_discovery/risk/rules.py)

The three required rules, plus a couple of nearby ones:

- **R1 — PHI to External LLM.** Fires HIGH when `data_classes` contains `PHI` and the agent has a confirmed external LLM destination (or uses the `external_llm_call` tool). A softer variant fires MEDIUM for other sensitive classes (`PCI`, `credentials`, etc.).
- **R2 — Agent Without aegislib.** Fires HIGH if a framework is classified, a repo scan exists, the imports don't include `aegislib`, and the agent touches data. Fires MEDIUM if no repo scan is correlated (we can't confirm SDK use either way).
- **R3 — Unexpected Tool Use.** Compares observed `tools` against the framework's baseline tool set ([src/aegis_discovery/risk/baseline.py](src/aegis_discovery/risk/baseline.py)) plus the agent's declared imports. Tools outside that set are flagged. Severity becomes HIGH if any of those tools look DB-/secret-/shell-related.

Every finding carries its own evidence list. The same evidence lines feed both the UI and the policy recommender.

## 9. Risk scorer

[src/aegis_discovery/risk/scorer.py](src/aegis_discovery/risk/scorer.py)

A 0-100 composite from four factors, each independently scaled to 0-100:

| Factor       | What it captures                                                       | Driven by                              |
|--------------|------------------------------------------------------------------------|----------------------------------------|
| Scope        | breadth of tool / destination access                                   | size of `tools` and `destinations`     |
| Sensitivity  | how sensitive the touched data classes are                             | `PHI`/`PCI`/`credentials` vs others    |
| Autonomy     | external network egress, unsupervised execution                        | external destinations, agentic frameworks |
| Drift        | deviation from framework baseline + missing `aegislib`                 | tools outside baseline, no SDK import  |

Default weights live in [config.yml](config.yml) (`sensitivity 0.35`, `drift 0.25`, `scope 0.20`, `autonomy 0.20`). A HIGH-severity finding floor-clamps the score so a HIGH rule firing can never yield a LOW agent. Tier boundaries come from the assignment (0-39 LOW, 40-69 MEDIUM, 70-100 HIGH) and live in config for easy tuning.

Every factor is exposed on the Agent (`risk_factors`), so reviewers can see exactly why a number came out the way it did.

## 10. Policy recommender

[src/aegis_discovery/policy/recommender.py](src/aegis_discovery/policy/recommender.py)

Decision order:
1. PHI + confirmed external LLM -> `phi-handling-v3`
2. Confirmed external LLM only -> `external-egress-redact`
3. Any LLM signal observed (e.g. provider name in SDK, model field present) -> `audit-all-llm-calls`

"Confirmed external" means a destination matches a known external LLM host or the agent uses the `external_llm_call` tool. A bare `provider=anthropic` is not enough — that just says "we use an Anthropic SDK", which is the catch-all `audit-all-llm-calls` case.

Every recommendation returns an `evidence` list. Recommendation confidence is `correlation_confidence + 0.2`, with a slight bonus for the PHI tier and a slight penalty for the audit tier (we're less sure when we only have a provider name).

## 11. Graph builder (bonus)

[src/aegis_discovery/graph/builder.py](src/aegis_discovery/graph/builder.py)

Builds `Agent -> Identity -> Tools -> Data Classes -> Destinations -> Policy` as flat `{nodes, edges}` JSON. The single-page UI lays it out as columns and draws an SVG. The graph is rebuilt on every `GET /agents/{id}/graph` call.

## 12. Storage

[src/aegis_discovery/storage/database.py](src/aegis_discovery/storage/database.py)

`SQLiteRepository` stores events and agents as JSON blobs keyed by id, with a dedup index on `(source, fingerprint_hash)`. The repository is defined as a `Protocol` so an `InMemoryRepository` can be substituted (used in every test). Persistence is intentionally simple — the value of this service is the domain logic, not the schema.

## 13. API surface

[src/aegis_discovery/api/routes.py](src/aegis_discovery/api/routes.py)

```
GET    /health                       liveness
GET    /metadata                     config snapshot (correlation window, policies, ext hosts)
POST   /events                       ingest events (list or {events:[]}), run pipeline
POST   /events/upload                multipart upload of a JSON file
POST   /pipeline/run                 re-run pipeline over everything in storage
DELETE /events                       reset the store
GET    /agents                       list agents (bonus)
GET    /agents/{id}                  agent detail (bonus)
GET    /agents/{id}/graph            Agent -> ... -> Policy graph (bonus)
GET    /                             single-page UI
```

## 14. Single-page UI

[web/index.html](web/index.html). Vanilla HTML / JS / SVG, no build step. Paste or upload events, hit "Run pipeline", and the page renders agent cards with the score, tier pill, framework, identity, tool / data / destination chips, finding evidence, recommended policy + evidence, the risk-factor bars, the graph, and the raw agent JSON. Conflicts are surfaced inline.

## 15. Known limitations

- **No baseline learning.** Drift detection uses a hard-coded baseline per framework. In production, baseline tool sets should be learned per agent over a quiet window.
- **In-process scheduler.** The pipeline runs synchronously inside the request. With thousands of events per second this becomes a problem — a real deployment would buffer ingest into a queue and run the correlator in batches.
- **No tenant isolation.** This is a single-tenant MVP.
- **Stable agent IDs are best-effort.** If a re-run sees a new strongest key (e.g. a previously-missing `nhi_id` shows up), the agent ID for that workload can change.
- **Time window is global.** A single ±5min window for every source. In reality, repo scans precede runtime by hours; we should have per-source skew tolerances.
- **No backpressure on conflicting nhi.** If two real agents share an `nhi_id` (shouldn't happen, but ops mistakes exist), we'd merge them. We'd need a fingerprint of process behavior to detect that.
- **Policy catalog is static.** Real policy selection should be data-driven (per environment, per data domain).
- **No auth / authz.** Out of scope for the MVP.

## 16. What I'd build next for production

1. **Event bus + batch correlator.** Kafka -> stream processor that maintains running clusters per join key, with TTL eviction.
2. **Learned framework classifier.** Use current rules as weak labels; ship a small XGBoost model behind a feature flag and shadow-evaluate.
3. **Behavioral baselines.** Per-agent baseline of `tools`, `destinations`, `data_classes` over a rolling 7d window; drift detection becomes "outside the p95 of the baseline" rather than "outside a hard-coded set".
4. **Policy engine.** Move from a Python function to a declarative engine (something OPA/Rego-shaped) so policies are versionable and testable on their own.
5. **Multi-tenancy + auth.** Tenant scoping at the repo layer; SSO + role-based access for the UI.
6. **Connectors.** Real eBPF agent, AWS CloudTrail/IAM-Access-Analyzer ingestor, Semgrep-style repo scanner, Okta/Google audit feed connector.
7. **Confidence-aware policy selection.** Below a confidence floor (e.g. 0.5) we should hold off recommending a strict policy and instead route to a "needs human review" queue.
8. **Observability.** Per-stage metrics (events normalized/sec, clusters/sec, average correlation confidence, rule firing rates) plus structured audit logs of every decision.
9. **Backfill + replay.** Pipeline must be idempotent on replay; today's stable IDs are a step toward this but we'd need versioned agent records.
10. **Adversarial-aware rules.** Detect agents that try to hide their identity (e.g. spoof `nhi_id` across hosts) by cross-referencing behavior fingerprints.
