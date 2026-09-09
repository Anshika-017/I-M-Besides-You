"""Step 2: process-mining analysis over a Step 1 `segments.jsonl` output.

This module is deliberately read-only with respect to Step 1: it loads
`segments.jsonl` exactly as produced (labels, boundaries — nothing
re-clustered, nothing re-segmented) and only RE-EXTRACTS per-segment
features (app/route/text) for descriptive analysis and for checking
whether some of the 99 discovered labels look like they should be read as
one practical process. It never rewrites segments.jsonl and never changes
a label.

Headcount/operator signal: dataset_b's session directory names embed the
recording machine (`ses_<date>-<time>-<machine>`), and every event's
`source.machine_id`/`source.username_hash` confirms one operator per
machine in this data (4 distinct machines, 4 distinct username_hash
values — checked, not assumed). This is genuine, observable log data, NOT
the leaked test-harness text, and is the basis for any headcount claim in
Step 2. See WORKLOG.md for why the leaked text is not used anywhere here.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .features import SegmentFeatures, extract_segment_features
from .io import iter_events
from .label import LabelingConfig, build_feature_matrix


def iso_to_dt(iso: str) -> datetime:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def machine_from_session_id(session_id: str) -> str:
    """dataset_b session dirs are named ses_<date>-<time>-<machine>. The
    machine name is everything after the second '-'-delimited date/time
    field. Verified against source.machine_id in the raw events (see
    WORKLOG.md) -- this is not a guess."""
    parts = session_id.split("-", 2)
    return parts[2] if len(parts) == 3 else session_id


@dataclass
class Segment:
    session_id: str
    start_iso: str
    end_iso: str
    label: str
    start_ms: int = field(init=False)
    end_ms: int = field(init=False)
    duration_s: float = field(init=False)
    machine: str = field(init=False)
    features: SegmentFeatures | None = None

    def __post_init__(self):
        self.start_ms = int(iso_to_dt(self.start_iso).timestamp() * 1000)
        self.end_ms = int(iso_to_dt(self.end_iso).timestamp() * 1000)
        self.duration_s = (self.end_ms - self.start_ms) / 1000.0
        self.machine = machine_from_session_id(self.session_id)


def load_segments(path: Path) -> list[Segment]:
    segments = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            segments.append(Segment(d["session_id"], d["start"], d["end"], d["label"]))
    return segments


def attach_features(segments: list[Segment], dataset_root: Path) -> None:
    """Re-extract app/route/text features for every segment, batching
    event loads by session (one iter_events pass per session, not per
    segment) since dataset_b has 15 sessions but 456 segments."""
    by_session: dict[str, list[Segment]] = defaultdict(list)
    for s in segments:
        by_session[s.session_id].append(s)

    for session_id, segs in by_session.items():
        session_dir = dataset_root / session_id
        events = list(iter_events(session_dir))
        for seg in segs:
            seg_events = [e for e in events if seg.start_ms <= e["timestamp_ms"] <= seg.end_ms]
            seg.features = extract_segment_features(session_id, seg.start_ms, seg.end_ms, seg_events)


def describe(values: list[float]) -> dict:
    if not values:
        return {}
    s = sorted(values)
    n = len(s)
    return {
        "n": n, "min": round(s[0], 1), "median": round(s[n // 2], 1),
        "mean": round(statistics.mean(s), 1),
        "p75": round(s[int(0.75 * (n - 1))], 1), "p90": round(s[int(0.90 * (n - 1))], 1),
        "max": round(s[-1], 1),
        "stdev": round(statistics.pstdev(s), 1) if n > 1 else 0.0,
    }


@dataclass
class LabelStats:
    label: str
    count: int
    total_duration_s: float
    duration_stats: dict
    sessions: list[str]
    machines: list[str]
    share_of_segments: float
    share_of_time: float
    top_apps: list[tuple[str, int]]
    top_routes: list[tuple[str, int]]
    n_distinct_apps: int
    n_distinct_routes: int
    consistency_score: float  # 1 - coefficient_of_variation of duration, clipped to [0,1]


def aggregate_by_label(segments: list[Segment]) -> dict[str, LabelStats]:
    total_segments = len(segments)
    total_time = sum(s.duration_s for s in segments)

    by_label: dict[str, list[Segment]] = defaultdict(list)
    for s in segments:
        by_label[s.label].append(s)

    out = {}
    for label, segs in by_label.items():
        durations = [s.duration_s for s in segs]
        dur_stats = describe(durations)
        mean_d = dur_stats["mean"]
        cv = (dur_stats["stdev"] / mean_d) if mean_d else 0.0
        consistency = max(0.0, 1.0 - min(cv, 1.0))

        app_counter, route_counter = Counter(), Counter()
        for s in segs:
            if s.features:
                app_counter.update(s.features.app_counts)
                route_counter.update(s.features.route_counts)

        out[label] = LabelStats(
            label=label,
            count=len(segs),
            total_duration_s=round(sum(durations), 1),
            duration_stats=dur_stats,
            sessions=sorted({s.session_id for s in segs}),
            machines=sorted({s.machine for s in segs}),
            share_of_segments=round(len(segs) / total_segments, 4),
            share_of_time=round(sum(durations) / total_time, 4) if total_time else 0.0,
            top_apps=app_counter.most_common(5),
            top_routes=route_counter.most_common(5),
            n_distinct_apps=len(app_counter),
            n_distinct_routes=len(route_counter),
            consistency_score=round(consistency, 3),
        )
    return out


def label_centroids(segments: list[Segment], config: LabelingConfig) -> tuple[dict[str, np.ndarray], list[str]]:
    """Build the SAME feature space Step 1's clustering used (same frozen
    LabelingConfig, fit jointly across all segments passed in), then
    average each label's member rows into a centroid vector. Used to
    quantitatively check whether two raw labels that stayed separate under
    the strict per-segment clustering threshold are nevertheless close in
    that same feature space -- evidence for consolidation, not a re-run of
    clustering."""
    feats = [s.features for s in segments]
    X = build_feature_matrix(feats, config)
    X = X.toarray()
    labels = [s.label for s in segments]

    by_label_idx: dict[str, list[int]] = defaultdict(list)
    for i, l in enumerate(labels):
        by_label_idx[l].append(i)

    centroids = {}
    for label, idxs in by_label_idx.items():
        centroids[label] = X[idxs].mean(axis=0)
    return centroids, sorted(by_label_idx.keys())


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def cluster_centroids(centroids: dict[str, np.ndarray], distance_threshold: float) -> dict[str, list[str]]:
    """Group the 99 raw labels into coarser "practical process groups" by
    running the SAME kind of clustering Step 1 used (AgglomerativeClustering,
    cosine distance, average linkage) -- but one level up, on each label's
    centroid rather than on individual segments, with a looser threshold.

    IMPORTANT: an earlier version of this analysis grouped labels with a
    naive "connect any pair above a similarity threshold, then take
    connected components" (union-find) approach. That is mathematically
    single-linkage clustering, and it chained catastrophically: at
    similarity >= 0.5, one moderately-similar pair after another
    transitively pulled 95 of the 99 labels into a single meaningless
    mega-group (see WORKLOG.md). Average-linkage agglomerative clustering
    (this function) doesn't have that failure mode -- it requires groups to
    be similar *on average*, not just linked by a single weak edge -- and
    was checked at a threshold sweep (0.30 to 0.60) to confirm it behaves
    sensibly (40 groups at 0.40, largest group size 13; no runaway
    collapse until much higher thresholds).
    """
    names = sorted(centroids.keys())
    X = np.array([centroids[n] for n in names])
    if len(names) <= 1:
        return {"group_000": names}
    from sklearn.cluster import AgglomerativeClustering
    model = AgglomerativeClustering(n_clusters=None, distance_threshold=distance_threshold,
                                     metric="cosine", linkage="average")
    cluster_ids = model.fit_predict(X)
    groups: dict[int, list[str]] = defaultdict(list)
    for name, cid in zip(names, cluster_ids):
        groups[cid].append(name)
    result = {}
    for i, (_, members) in enumerate(sorted(groups.items(), key=lambda kv: sorted(kv[1])[0])):
        result[f"group_{i:03d}"] = sorted(members)
    return result


def find_consolidation_candidates(centroids: dict[str, np.ndarray], min_similarity: float = 0.5) -> list[tuple[str, str, float]]:
    """All pairs of (different) labels whose centroid cosine similarity is
    >= min_similarity, sorted by similarity descending. min_similarity=0.5
    is deliberately looser than the clustering stage's own merge threshold
    (cosine distance 0.30 => similarity >= 0.70) -- this is a separate,
    weaker "worth reviewing" bar for Step 2 analysis, not a re-run of the
    Step 1 clustering decision."""
    names = sorted(centroids.keys())
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            sim = cosine_sim(centroids[names[i]], centroids[names[j]])
            if sim >= min_similarity:
                pairs.append((names[i], names[j], round(sim, 4)))
    pairs.sort(key=lambda x: -x[2])
    return pairs
