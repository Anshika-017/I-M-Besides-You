#!/usr/bin/env python3
"""Step 2: process-mining analysis of dataset_b's segments.jsonl.

Reads the existing Step 1 output as-is (no re-segmentation, no
re-clustering, no dataset_b tuning of any kind) and produces:

  1. Per-label (raw, all 99) frequency/duration/recurrence/headcount stats
     -> reports/step2/label_stats.json, label_stats.csv
  2. Evidence-based consolidation groups: labels whose feature centroids
     are close in the SAME space Step 1's clustering used, even though the
     strict per-segment threshold kept them in separate clusters
     -> reports/step2/consolidation_groups.json
  3. Group-level (consolidated) stats -- the practical unit of analysis
     for automation prioritization -- with a transparent, documented
     scoring formula
     -> reports/step2/process_groups.json, process_groups.csv
  4. A transition summary at the group level (which group's segments tend
     to precede which, within a session)
     -> reports/step2/transitions.json
  5. A ranked automation candidate list with an explicit scoring formula
     -> reports/step2/candidate_ranking.json, candidate_ranking.csv

Every number in the final report should be traceable back to one of these
files (or directly to segments.jsonl / the raw dataset_b events).
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procmine.analyze import (  # noqa: E402
    load_segments, attach_features, aggregate_by_label, label_centroids,
    find_consolidation_candidates, cluster_centroids, describe,
)
from procmine.label import LabelingConfig  # noqa: E402

SEGMENTS_PATH = ROOT / "segments.jsonl"
DATA_B = ROOT / "data" / "dataset_b"
OUT_DIR = ROOT / "reports" / "step2"
CONSOLIDATION_MIN_SIMILARITY = 0.5   # for the pairwise "worth reviewing" evidence list
GROUP_DISTANCE_THRESHOLD = 0.40      # for the actual grouping (see analyze.cluster_centroids docstring)


def main():
    print("Loading segments.jsonl (Step 1 output, unmodified) ...")
    segments = load_segments(SEGMENTS_PATH)
    print(f"  {len(segments)} segments loaded")
    assert len(segments) == 456, f"expected 456 segments, got {len(segments)} -- did segments.jsonl change?"

    print("Re-extracting per-segment features (app/route/text) for analysis only ...")
    attach_features(segments, DATA_B)

    print("\n=== 1. Per-label stats (raw, all discovered labels) ===")
    label_stats = aggregate_by_label(segments)
    print(f"  {len(label_stats)} distinct labels (matches Step 1's n_clusters=99: "
          f"{len(label_stats) == 99})")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "label_stats.json", "w", encoding="utf-8") as f:
        json.dump({l: vars(s) for l, s in label_stats.items()}, f, indent=2, ensure_ascii=False)
    with open(OUT_DIR / "label_stats.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["label", "count", "total_duration_s", "median_duration_s", "mean_duration_s",
                    "n_sessions", "n_machines", "share_of_segments", "share_of_time",
                    "consistency_score", "n_distinct_apps", "n_distinct_routes", "top_app", "top_route"])
        for l, s in sorted(label_stats.items(), key=lambda kv: -kv[1].count):
            w.writerow([l, s.count, s.total_duration_s, s.duration_stats.get("median"),
                        s.duration_stats.get("mean"), len(s.sessions), len(s.machines),
                        s.share_of_segments, s.share_of_time, s.consistency_score,
                        s.n_distinct_apps, s.n_distinct_routes,
                        s.top_apps[0][0] if s.top_apps else "", s.top_routes[0][0] if s.top_routes else ""])

    # sanity totals
    total_count = sum(s.count for s in label_stats.values())
    total_time = sum(s.total_duration_s for s in label_stats.values())
    print(f"  sum of per-label counts = {total_count} (should be 456)")
    print(f"  sum of per-label durations = {total_time:.1f}s")

    print("\n=== 2. Consolidation candidates (centroid similarity in Step 1's feature space) ===")
    config = LabelingConfig()  # frozen, same as Step 1 -- no dataset_b tuning
    centroids, all_labels = label_centroids(segments, config)
    pairs = find_consolidation_candidates(centroids, min_similarity=CONSOLIDATION_MIN_SIMILARITY)
    print(f"  {len(pairs)} label pairs with centroid cosine similarity >= {CONSOLIDATION_MIN_SIMILARITY}")
    for a, b, sim in pairs[:15]:
        print(f"    {sim:.3f}  {a}  <->  {b}")

    print(f"\n  NOTE: an earlier version grouped labels by connected components over this "
          f"pairwise list (union-find / single-linkage). That chained catastrophically -- "
          f"95 of 99 labels collapsed into one group at similarity>=0.5, because chains of "
          f"individually-reasonable pairwise links transitively connected almost everything. "
          f"See WORKLOG.md. Using average-linkage agglomerative clustering on the centroids "
          f"instead (below), which doesn't have that failure mode.")

    groups = cluster_centroids(centroids, distance_threshold=GROUP_DISTANCE_THRESHOLD)
    n_multi = sum(1 for m in groups.values() if len(m) > 1)
    sizes = sorted((len(m) for m in groups.values()), reverse=True)
    print(f"  -> {len(groups)} consolidated groups at distance_threshold={GROUP_DISTANCE_THRESHOLD} "
          f"({n_multi} contain >1 label, {len(groups) - n_multi} are singletons, "
          f"largest group has {sizes[0]} members)")

    with open(OUT_DIR / "consolidation_groups.json", "w", encoding="utf-8") as f:
        json.dump({
            "pairwise_evidence_min_similarity": CONSOLIDATION_MIN_SIMILARITY,
            "pairwise_evidence": [{"label_a": a, "label_b": b, "cosine_similarity": s} for a, b, s in pairs],
            "group_distance_threshold": GROUP_DISTANCE_THRESHOLD,
            "group_method": "AgglomerativeClustering(cosine, average linkage) on label centroids",
            "groups": groups,
        }, f, indent=2, ensure_ascii=False)

    print("\n=== 3. Group-level (consolidated) stats ===")
    group_stats = {}
    for gid, members in groups.items():
        segs_in_group = [s for s in segments if s.label in members]
        durations = [s.duration_s for s in segs_in_group]
        dur_stats = describe(durations)
        app_counter, route_counter = Counter(), Counter()
        for s in segs_in_group:
            if s.features:
                app_counter.update(s.features.app_counts)
                route_counter.update(s.features.route_counts)
        sessions = sorted({s.session_id for s in segs_in_group})
        machines = sorted({s.machine for s in segs_in_group})
        mean_d = dur_stats.get("mean", 0)
        cv = (dur_stats.get("stdev", 0) / mean_d) if mean_d else 0.0
        group_stats[gid] = {
            "member_labels": members,
            "n_members": len(members),
            "count": len(segs_in_group),
            "total_duration_s": round(sum(durations), 1),
            "duration_stats": dur_stats,
            "n_sessions": len(sessions), "sessions": sessions,
            "n_machines": len(machines), "machines": machines,
            "consistency_score": round(max(0.0, 1.0 - min(cv, 1.0)), 3),
            "top_apps": app_counter.most_common(3),
            "top_routes": route_counter.most_common(3),
        }

    total_segments = len(segments)
    total_time_all = sum(s.duration_s for s in segments)
    for gid, gs in group_stats.items():
        gs["share_of_segments"] = round(gs["count"] / total_segments, 4)
        gs["share_of_time"] = round(gs["total_duration_s"] / total_time_all, 4) if total_time_all else 0.0

    with open(OUT_DIR / "process_groups.json", "w", encoding="utf-8") as f:
        json.dump(group_stats, f, indent=2, ensure_ascii=False)
    with open(OUT_DIR / "process_groups.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group_id", "n_members", "count", "total_duration_s", "median_duration_s",
                    "n_sessions", "n_machines", "share_of_segments", "share_of_time",
                    "consistency_score", "top_app", "top_route", "member_labels"])
        for gid, gs in sorted(group_stats.items(), key=lambda kv: -kv[1]["count"]):
            w.writerow([gid, gs["n_members"], gs["count"], gs["total_duration_s"],
                        gs["duration_stats"].get("median"), gs["n_sessions"], gs["n_machines"],
                        gs["share_of_segments"], gs["share_of_time"], gs["consistency_score"],
                        gs["top_apps"][0][0] if gs["top_apps"] else "",
                        gs["top_routes"][0][0] if gs["top_routes"] else "",
                        "|".join(gs["member_labels"])])

    top_groups = sorted(group_stats.items(), key=lambda kv: -kv[1]["count"])[:10]
    print("  Top 10 groups by frequency:")
    for gid, gs in top_groups:
        print(f"    {gid}: count={gs['count']:3d} time={gs['total_duration_s']:7.1f}s "
              f"sessions={gs['n_sessions']:2d} machines={gs['n_machines']} members={gs['n_members']} "
              f"top_route={gs['top_routes'][0][0] if gs['top_routes'] else '-'}")

    print("\n=== 3b. Process families (grouping groups by shared top-level route) ===")
    # One more, even coarser layer, requested by the assignment's "are
    # there different handling patterns within the same process?"
    # question. Several of the 40 groups above share the same top-level
    # SPA route (e.g. group_003/group_007/group_010 are all
    # "leave-applications") but didn't merge even at the group threshold
    # -- that's the interesting case: same apparent business process,
    # different enough handling (different apps, different session/machine
    # mix, different duration profile) to look like distinct variants
    # rather than noise. This grouping is purely by the literal top-level
    # route token (transparent, not a similarity score) specifically so it
    # can be cross-checked against the group-level (similarity-based)
    # view above.
    def route_family(top_route):
        if not top_route or not top_route.startswith("#/"):
            return "no_route"
        return top_route.split("/")[1] if len(top_route.split("/")) > 1 else "no_route"

    family_members = defaultdict(list)
    for gid, gs in group_stats.items():
        top_route = gs["top_routes"][0][0] if gs["top_routes"] else None
        family_members[route_family(top_route)].append(gid)

    family_stats = {}
    for family, gids in family_members.items():
        member_labels = [l for gid in gids for l in group_stats[gid]["member_labels"]]
        segs_in_family = [s for s in segments if s.label in member_labels]
        durations = [s.duration_s for s in segs_in_family]
        dur_stats = describe(durations)
        sessions = sorted({s.session_id for s in segs_in_family})
        machines = sorted({s.machine for s in segs_in_family})
        mean_d = dur_stats.get("mean", 0)
        cv = (dur_stats.get("stdev", 0) / mean_d) if mean_d else 0.0

        # Feasibility signal: how dominated is this family by a single
        # application? A process that lives almost entirely in one app
        # (e.g. a browser portal) is a narrower, more tractable automation
        # surface than one that genuinely spans two+ applications (e.g.
        # browser + Word), which would need a hybrid automation approach.
        app_totals = Counter()
        for gid in gids:
            for app, cnt in group_stats[gid]["top_apps"]:
                app_totals[app] += cnt
        total_app_events = sum(app_totals.values())
        dominant_app, dominant_app_count = (app_totals.most_common(1)[0] if app_totals else (None, 0))
        dominant_app_share = round(dominant_app_count / total_app_events, 4) if total_app_events else 0.0

        family_stats[family] = {
            "member_groups": gids, "n_variant_groups": len(gids),
            "member_labels": member_labels,
            "count": len(segs_in_family), "total_duration_s": round(sum(durations), 1),
            "duration_stats": dur_stats,
            "n_sessions": len(sessions), "sessions": sessions,
            "n_machines": len(machines), "machines": machines,
            "consistency_score": round(max(0.0, 1.0 - min(cv, 1.0)), 3),
            "share_of_segments": round(len(segs_in_family) / total_segments, 4),
            "share_of_time": round(sum(durations) / total_time_all, 4) if total_time_all else 0.0,
            "dominant_app": dominant_app, "dominant_app_share": dominant_app_share,
            "apps_used": app_totals.most_common(5),
        }

    with open(OUT_DIR / "process_families.json", "w", encoding="utf-8") as f:
        json.dump(family_stats, f, indent=2, ensure_ascii=False)
    with open(OUT_DIR / "process_families.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["family", "n_variant_groups", "count", "total_duration_s", "median_duration_s",
                    "n_sessions", "n_machines", "share_of_segments", "share_of_time",
                    "consistency_score", "dominant_app", "dominant_app_share", "member_groups"])
        for fam, fs in sorted(family_stats.items(), key=lambda kv: -kv[1]["count"]):
            w.writerow([fam, fs["n_variant_groups"], fs["count"], fs["total_duration_s"],
                        fs["duration_stats"].get("median"), fs["n_sessions"], fs["n_machines"],
                        fs["share_of_segments"], fs["share_of_time"], fs["consistency_score"],
                        fs["dominant_app"], fs["dominant_app_share"],
                        "|".join(fs["member_groups"])])

    print(f"  {len(family_stats)} process families (from {len(group_stats)} groups)")
    for fam, fs in sorted(family_stats.items(), key=lambda kv: -kv[1]["count"])[:10]:
        variant_note = f" ({fs['n_variant_groups']} variant groups)" if fs["n_variant_groups"] > 1 else ""
        print(f"    {fam:20s} count={fs['count']:3d} time={fs['total_duration_s']:7.1f}s "
              f"sessions={fs['n_sessions']:2d}/15 machines={fs['n_machines']}/4 "
              f"dominant_app={fs['dominant_app']}({fs['dominant_app_share']:.0%}){variant_note}")

    print("\n=== 4. Transitions (group-level, within-session order) ===")
    transition_counts = Counter()
    label_to_group = {l: gid for gid, members in groups.items() for l in members}
    by_session = defaultdict(list)
    for s in segments:
        by_session[s.session_id].append(s)
    for session_id, segs in by_session.items():
        segs_sorted = sorted(segs, key=lambda s: s.start_ms)
        for a, b in zip(segs_sorted, segs_sorted[1:]):
            ga, gb = label_to_group[a.label], label_to_group[b.label]
            if ga != gb:
                transition_counts[(ga, gb)] += 1
    top_transitions = transition_counts.most_common(15)
    with open(OUT_DIR / "transitions.json", "w", encoding="utf-8") as f:
        json.dump([{"from": a, "to": b, "count": c} for (a, b), c in transition_counts.most_common()],
                   f, indent=2)
    print("  Top 15 group-to-group transitions:")
    for (a, b), c in top_transitions:
        print(f"    {c:3d}x  {a} -> {b}")

    print("\n=== 5. Automation candidate ranking ===")
    # Transparent scoring: each component normalized to [0,1] against the
    # max observed value across groups, then combined with documented
    # weights. No monetary values invented -- this is a RELATIVE ranking,
    # not an ROI-in-dollars estimate. See WORKLOG.md / step2 report for
    # the rationale behind each weight.
    max_count = max(gs["count"] for gs in group_stats.values())
    max_time = max(gs["total_duration_s"] for gs in group_stats.values())
    WEIGHTS = {"frequency": 0.35, "time_share": 0.25, "consistency": 0.20,
               "recurrence": 0.10, "headcount": 0.10}

    ranking = []
    for gid, gs in group_stats.items():
        frequency_score = gs["count"] / max_count
        time_score = gs["total_duration_s"] / max_time
        consistency_score = gs["consistency_score"]
        recurrence_score = gs["n_sessions"] / 15
        headcount_score = gs["n_machines"] / 4
        composite = (WEIGHTS["frequency"] * frequency_score
                     + WEIGHTS["time_share"] * time_score
                     + WEIGHTS["consistency"] * consistency_score
                     + WEIGHTS["recurrence"] * recurrence_score
                     + WEIGHTS["headcount"] * headcount_score)
        ranking.append({
            "group_id": gid, "composite_score": round(composite, 4),
            "frequency_score": round(frequency_score, 3), "time_score": round(time_score, 3),
            "consistency_score": round(consistency_score, 3), "recurrence_score": round(recurrence_score, 3),
            "headcount_score": round(headcount_score, 3),
            "count": gs["count"], "total_duration_s": gs["total_duration_s"],
            "n_sessions": gs["n_sessions"], "n_machines": gs["n_machines"],
            "n_distinct_apps_used": len(set(gs["top_apps"] and [a for a, _ in gs["top_apps"]] or [])),
            "top_route": gs["top_routes"][0][0] if gs["top_routes"] else None,
            "member_labels": gs["member_labels"],
        })
    ranking.sort(key=lambda r: -r["composite_score"])

    with open(OUT_DIR / "candidate_ranking.json", "w", encoding="utf-8") as f:
        json.dump({"weights": WEIGHTS, "ranking": ranking}, f, indent=2, ensure_ascii=False)
    with open(OUT_DIR / "candidate_ranking.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "group_id", "composite_score", "frequency_score", "time_score",
                    "consistency_score", "recurrence_score", "headcount_score",
                    "count", "total_duration_s", "n_sessions", "n_machines", "top_route"])
        for i, r in enumerate(ranking, 1):
            w.writerow([i, r["group_id"], r["composite_score"], r["frequency_score"], r["time_score"],
                        r["consistency_score"], r["recurrence_score"], r["headcount_score"],
                        r["count"], r["total_duration_s"], r["n_sessions"], r["n_machines"], r["top_route"]])

    print(f"  Weights used: {WEIGHTS}")
    print("  Top 10 candidates:")
    for i, r in enumerate(ranking[:10], 1):
        print(f"    {i:2d}. {r['group_id']:10s} score={r['composite_score']:.3f} "
              f"count={r['count']:3d} time={r['total_duration_s']:7.1f}s "
              f"sessions={r['n_sessions']}/15 machines={r['n_machines']}/4 "
              f"route={r['top_route']}")

    print("\n=== 6. Automation candidate ranking -- FAMILY level (primary view) ===")
    # Same transparent formula as the group-level ranking above, applied
    # one level up. This is the primary view for candidate selection: a
    # "process family" (e.g. all leave-application variants combined) is
    # closer to what a business person would call "one process" than
    # either the raw 99 labels (too fragmented) or the 40 groups (still
    # splits some clear same-route variants apart, by design -- see 3b).
    max_count_f = max(fs["count"] for fs in family_stats.values())
    max_time_f = max(fs["total_duration_s"] for fs in family_stats.values())
    family_ranking = []
    for fam, fs in family_stats.items():
        frequency_score = fs["count"] / max_count_f
        time_score = fs["total_duration_s"] / max_time_f
        consistency_score = fs["consistency_score"]
        recurrence_score = fs["n_sessions"] / 15
        headcount_score = fs["n_machines"] / 4
        composite = (WEIGHTS["frequency"] * frequency_score
                     + WEIGHTS["time_share"] * time_score
                     + WEIGHTS["consistency"] * consistency_score
                     + WEIGHTS["recurrence"] * recurrence_score
                     + WEIGHTS["headcount"] * headcount_score)
        family_ranking.append({
            "family": fam, "composite_score": round(composite, 4),
            "frequency_score": round(frequency_score, 3), "time_score": round(time_score, 3),
            "consistency_score": round(consistency_score, 3), "recurrence_score": round(recurrence_score, 3),
            "headcount_score": round(headcount_score, 3),
            "count": fs["count"], "total_duration_s": fs["total_duration_s"],
            "n_sessions": fs["n_sessions"], "n_machines": fs["n_machines"],
            "n_variant_groups": fs["n_variant_groups"], "member_groups": fs["member_groups"],
        })
    family_ranking.sort(key=lambda r: -r["composite_score"])

    with open(OUT_DIR / "candidate_ranking_family_level.json", "w", encoding="utf-8") as f:
        json.dump({"weights": WEIGHTS, "ranking": family_ranking}, f, indent=2, ensure_ascii=False)
    with open(OUT_DIR / "candidate_ranking_family_level.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "family", "composite_score", "frequency_score", "time_score",
                    "consistency_score", "recurrence_score", "headcount_score",
                    "count", "total_duration_s", "n_sessions", "n_machines", "n_variant_groups"])
        for i, r in enumerate(family_ranking, 1):
            w.writerow([i, r["family"], r["composite_score"], r["frequency_score"], r["time_score"],
                        r["consistency_score"], r["recurrence_score"], r["headcount_score"],
                        r["count"], r["total_duration_s"], r["n_sessions"], r["n_machines"],
                        r["n_variant_groups"]])

    print(f"  Top families by composite score:")
    for i, r in enumerate(family_ranking[:10], 1):
        print(f"    {i:2d}. {r['family']:20s} score={r['composite_score']:.3f} "
              f"count={r['count']:3d} time={r['total_duration_s']:7.1f}s "
              f"sessions={r['n_sessions']}/15 machines={r['n_machines']}/4 "
              f"variants={r['n_variant_groups']}")

    print(f"\nAll artifacts written to {OUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
