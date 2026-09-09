#!/usr/bin/env python3
"""Apply the frozen Step 1 pipeline to dataset_b and produce segments.jsonl.

This script does NOT tune anything — SegmentationConfig() and
LabelingConfig() are used with their defaults exactly as chosen and
validated against dataset_a's ground truth (see WORKLOG.md and
reports/step1/). Dataset_b has no ground truth, and per the assignment
(and explicit instruction) is not used for any tuning or threshold
selection; this script only ever reads dataset_b once it's already fixed.

Also deliberately does NOT read or use the leaked test-harness/generator
text found incidentally in some dataset_b events (see WORKLOG.md, Day 1) —
that text is not treated as ground truth anywhere in this pipeline.

Steps:
  1. Cut every session into segments with the frozen SegmentationConfig.
  2. Extract features for every segment across ALL sessions.
  3. Cluster ALL of dataset_b's segments JOINTLY (not per-session) with the
     frozen LabelingConfig, since the same real process can occur in
     different sessions and must get the same label.
  4. Turn each cluster into a human-readable (but non-authoritative) label
     string, derived from that cluster's most common app + browser route —
     the label text itself isn't evaluated per the assignment, but a
     descriptive label is far more useful for the Step 2 analysis than an
     opaque cluster index.
  5. Write segments.jsonl (one JSON object per line: session_id, start,
     end, label) and a companion summary report for Step 2 to build on.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procmine.io import list_sessions, iter_events  # noqa: E402
from procmine.segment import SegmentationConfig, segment_session  # noqa: E402
from procmine.features import extract_segment_features, SegmentFeatures  # noqa: E402
from procmine.label import LabelingConfig, build_feature_matrix, cluster_segments  # noqa: E402

DATA_B = ROOT / "data" / "dataset_b"
OUT_SEGMENTS = ROOT / "segments.jsonl"
OUT_SUMMARY = ROOT / "reports" / "step1" / "dataset_b_segmentation_summary.json"


def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str) -> str:
    text = text.lower().strip()
    out = []
    for ch in text:
        out.append(ch if ch.isalnum() else "-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "unknown"


def cluster_label(cluster_id: int, member_feats: list[SegmentFeatures]) -> str:
    app_counts = Counter()
    route_counts = Counter()
    for f in member_feats:
        app_counts.update(f.app_counts)
        route_counts.update(f.route_counts)
    top_app = app_counts.most_common(1)[0][0] if app_counts else "unknownapp"
    top_route = route_counts.most_common(1)[0][0] if route_counts else None
    app_slug = slugify(top_app)
    if top_route:
        # route looks like "#/payroll-items" or "#/cases/<id>" -- keep the
        # meaningful part after the leading "#/"
        route_slug = slugify(top_route.split("#/", 1)[-1])
        return f"proc_{cluster_id:02d}_{app_slug}_{route_slug}"
    return f"proc_{cluster_id:02d}_{app_slug}"


def main():
    sessions = list_sessions(DATA_B)
    print(f"dataset_b: {len(sessions)} sessions")

    all_feats: list[SegmentFeatures] = []
    all_segments: list[tuple[str, int, int]] = []  # (session_id, start_ms, end_ms)
    seg_config = SegmentationConfig()
    print(f"Using frozen SegmentationConfig: {seg_config}")

    for ses in sessions:
        events = list(iter_events(ses))
        if not events:
            print(f"  {ses.name}: no events, skipping")
            continue
        segments = segment_session(events, seg_config)
        print(f"  {ses.name}: {len(events)} events -> {len(segments)} segments")
        for s, e in segments:
            seg_events = [ev for ev in events if s <= ev["timestamp_ms"] <= e]
            all_feats.append(extract_segment_features(ses.name, s, e, seg_events))
            all_segments.append((ses.name, s, e))

    print(f"\nTotal segments across dataset_b: {len(all_segments)}")

    label_config = LabelingConfig()
    print(f"Using frozen LabelingConfig: {label_config}")
    X = build_feature_matrix(all_feats, label_config)
    clusters = cluster_segments(X, label_config)
    n_clusters = len(set(clusters))
    print(f"Discovered {n_clusters} clusters")

    members_by_cluster = defaultdict(list)
    for feats, c in zip(all_feats, clusters):
        members_by_cluster[c].append(feats)
    labels_by_cluster = {c: cluster_label(c, members) for c, members in members_by_cluster.items()}

    # cluster size distribution -- flagged for Step 2, not filtered here.
    # dataset_a validation found ~18-20% of predicted segments don't
    # correspond to any real process (see WORKLOG.md); we have no ground
    # truth to check that on dataset_b, but singleton/near-singleton
    # clusters (a "process" that never recurs) are the same kind of
    # pattern the README says a real process should NOT show
    # ("the same process appears many times a day").
    cluster_sizes = Counter(clusters)
    singleton_clusters = sum(1 for c, n in cluster_sizes.items() if n == 1)
    singleton_segments = singleton_clusters

    records = []
    for (ses_id, s, e), c in zip(all_segments, clusters):
        records.append({
            "session_id": ses_id,
            "start": ms_to_iso(s),
            "end": ms_to_iso(e),
            "label": labels_by_cluster[c],
            "_sort_key": (ses_id, s),
        })
    records.sort(key=lambda r: r["_sort_key"])

    with open(OUT_SEGMENTS, "w", encoding="utf-8") as f:
        for r in records:
            out = {"session_id": r["session_id"], "start": r["start"], "end": r["end"], "label": r["label"]}
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print(f"\nWrote {len(records)} segments to {OUT_SEGMENTS.relative_to(ROOT)}")

    summary = {
        "n_sessions": len(sessions),
        "n_segments": len(all_segments),
        "n_clusters": n_clusters,
        "segmentation_config": vars(seg_config),
        "labeling_config": vars(label_config),
        "cluster_sizes": {labels_by_cluster[c]: n for c, n in cluster_sizes.most_common()},
        "singleton_clusters": singleton_clusters,
        "singleton_segments_fraction": round(singleton_segments / len(all_segments), 4),
        "segments_per_session": {ses.name: sum(1 for r in records if r["session_id"] == ses.name) for ses in sessions},
    }
    OUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_SUMMARY, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"Wrote summary to {OUT_SUMMARY.relative_to(ROOT)}")
    print(f"\nCluster sizes: {dict(cluster_sizes.most_common(10))} ...")
    print(f"Singleton clusters (never recur -- likely noise, per dataset_a's finding that "
          f"~18-20% of predicted segments don't correspond to a real process): "
          f"{singleton_clusters}/{n_clusters} clusters, {singleton_segments}/{len(all_segments)} segments "
          f"({100*singleton_segments/len(all_segments):.1f}%)")


if __name__ == "__main__":
    main()
