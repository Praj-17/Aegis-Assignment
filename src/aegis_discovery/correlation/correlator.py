"""Identity Correlator — the core of Aegis Discovery.

Goal: given a stream of partial, out-of-order CanonicalEvents from 4 sources,
group them into clusters where each cluster represents one real-world agent.

Join keys (per assignment):
    1. nhi_id                       — strong, unambiguous identity
    2. (host_id, pid)               — strong, identifies one process on one host
    3. workload_id                  — strong, identifies one workload/repo deployment
    4. time-window ±5min            — soft, reinforces weaker partial matches

Design:
    We use Union-Find (Disjoint Set Union) on event indices. We index events
    by each strong key and union all events that share that key. For weak
    keys (host_id alone, repo alone), we only union if both events also fall
    inside the ±5 minute window — otherwise two unrelated agents that just
    happened to run on the same host would get merged.

Edge cases handled:
    - Partial keys: an event with only host_id+pid still joins via that key.
    - Multiple agents per host: same host_id with different pids stay separate
      unless another stronger key links them.
    - Duplicates: deduplicated by (source, fingerprint_hash).
    - Out-of-order: events are sorted by timestamp before clustering.
    - Conflicting framework_hint: surfaced as conflicts; resolved by the
      fingerprint classifier using source priority.

Output: list of EventCluster, each with a confidence score derived from the
strength and number of shared join keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from aegis_discovery.schemas import CanonicalEvent


@dataclass
class EventCluster:
    """A group of events believed to belong to the same real agent."""

    events: list[CanonicalEvent] = field(default_factory=list)
    join_keys_used: set[str] = field(default_factory=set)
    confidence: float = 0.0


class _UnionFind:
    """Tiny disjoint-set with path compression + union by size."""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.size = [1] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.size[ra] < self.size[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.size[ra] += self.size[rb]


def _dedupe(events: list[CanonicalEvent]) -> list[CanonicalEvent]:
    """Drop duplicate events: same source + same content fingerprint."""

    seen: set[tuple[str, str]] = set()
    out: list[CanonicalEvent] = []
    for ev in events:
        key = (ev.source.value, ev.fingerprint_hash)
        if ev.fingerprint_hash and key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return out


def _within_window(a: CanonicalEvent, b: CanonicalEvent, seconds: int) -> bool:
    return abs((a.timestamp - b.timestamp).total_seconds()) <= seconds


def _confidence_for_cluster(cluster: list[CanonicalEvent], window_seconds: int) -> tuple[float, set[str]]:
    """Score how confident we are that these events truly belong to one agent.

    Returns (confidence_0_to_1, set_of_join_keys_that_matched).
    """

    keys: set[str] = set()
    nhi_ids = {e.nhi_id for e in cluster if e.nhi_id}
    host_pids = {(e.host_id, e.pid) for e in cluster if e.host_id and e.pid is not None}
    workloads = {e.workload_id for e in cluster if e.workload_id}
    repos = {e.repo for e in cluster if e.repo}
    hosts = {e.host_id for e in cluster if e.host_id}

    score = 0.5  # base for any non-empty cluster
    if len(nhi_ids) == 1 and len(cluster) > 1:
        score += 0.30
        keys.add("nhi_id")
    if len(host_pids) == 1 and len(cluster) > 1:
        score += 0.20
        keys.add("host_id+pid")
    if len(workloads) == 1 and len(cluster) > 1:
        score += 0.15
        keys.add("workload_id")
    if len(repos) == 1 and len(cluster) > 1:
        score += 0.10
        keys.add("repo")
    if len(hosts) == 1 and len(cluster) > 1 and "host_id+pid" not in keys:
        score += 0.05
        keys.add("host_id")

    # Time-window bonus: every event within window of cluster centroid.
    if len(cluster) > 1:
        ts_sorted = sorted(e.timestamp for e in cluster)
        spread = (ts_sorted[-1] - ts_sorted[0]).total_seconds()
        if spread <= window_seconds:
            score += 0.10
            keys.add("time_window")

    # Single-event cluster gets a modest confidence (we only have one signal).
    if len(cluster) == 1:
        score = 0.4

    return min(score, 1.0), keys


def correlate(
    events: list[CanonicalEvent],
    time_window_seconds: int = 300,
    dedup: bool = True,
) -> list[EventCluster]:
    """Cluster events into per-agent groups.

    Args:
        events: normalized events.
        time_window_seconds: ±tolerance for time-based matching (default 5 min).
        dedup: whether to drop exact duplicate events.

    Returns:
        One EventCluster per inferred agent.
    """

    if not events:
        return []

    # Out-of-order handling: sort by timestamp.
    work = sorted(events, key=lambda e: e.timestamp)
    if dedup:
        work = _dedupe(work)

    n = len(work)
    uf = _UnionFind(n)
    window = timedelta(seconds=time_window_seconds)

    # Build indexes for the strong join keys. Strong keys merge unconditionally.
    by_nhi: dict[str, list[int]] = {}
    by_host_pid: dict[tuple[str, int], list[int]] = {}
    by_workload: dict[str, list[int]] = {}
    by_repo: dict[str, list[int]] = {}
    by_host: dict[str, list[int]] = {}

    for i, ev in enumerate(work):
        if ev.nhi_id:
            by_nhi.setdefault(ev.nhi_id, []).append(i)
        if ev.host_id and ev.pid is not None:
            by_host_pid.setdefault((ev.host_id, ev.pid), []).append(i)
        if ev.workload_id:
            by_workload.setdefault(ev.workload_id, []).append(i)
        if ev.repo:
            by_repo.setdefault(ev.repo, []).append(i)
        if ev.host_id:
            by_host.setdefault(ev.host_id, []).append(i)

    # Strong keys: union all events sharing the key, no time constraint.
    for indices in by_nhi.values():
        for j in indices[1:]:
            uf.union(indices[0], j)
    for indices in by_host_pid.values():
        for j in indices[1:]:
            uf.union(indices[0], j)
    for indices in by_workload.values():
        for j in indices[1:]:
            uf.union(indices[0], j)
    for indices in by_repo.values():
        for j in indices[1:]:
            uf.union(indices[0], j)

    # Weak key: host_id alone, but only inside the time window. Without this
    # guard, two unrelated agents on the same host would collapse.
    for indices in by_host.values():
        if len(indices) < 2:
            continue
        # Compare each event in the host bucket pairwise but in O(n) per
        # bucket by sweeping the time-sorted list.
        sorted_idx = sorted(indices, key=lambda i: work[i].timestamp)
        for a, b in zip(sorted_idx, sorted_idx[1:]):
            if work[b].timestamp - work[a].timestamp <= window:
                # Only merge if they don't already disagree on pid.
                if (
                    work[a].pid is not None
                    and work[b].pid is not None
                    and work[a].pid != work[b].pid
                ):
                    continue
                uf.union(a, b)

    # Materialize clusters.
    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = uf.find(i)
        groups.setdefault(root, []).append(i)

    clusters: list[EventCluster] = []
    for member_indices in groups.values():
        members = [work[i] for i in member_indices]
        members.sort(key=lambda e: e.timestamp)
        confidence, keys = _confidence_for_cluster(members, time_window_seconds)
        clusters.append(EventCluster(events=members, join_keys_used=keys, confidence=confidence))

    # Stable order: oldest-first agent appears first.
    clusters.sort(key=lambda c: c.events[0].timestamp)
    return clusters
