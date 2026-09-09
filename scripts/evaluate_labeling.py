#!/usr/bin/env python3
"""Build and evaluate the Step 1 labeling stage: given segments, assign
each one a label such that segments from the same real process share a
label. Two evaluation phases, both against dataset_a's ground truth, both
using the same dev/test session split as evaluate_segmentation.py:

  PHASE 1 — ORACLE segments: cluster the TRUE (start_ts, end_ts) executions
  from gt_manifest.json. This isolates "how good is clustering itself" from
  "how much does our own boundary-detection noise hurt it" — if clustering
  can't even group perfectly-cut segments correctly, there's no point
  blaming the segmentation stage for a bad end-to-end result.

  PHASE 2 — PREDICTED segments: cluster the segments our own (frozen, from
  evaluate_segmentation.py) boundary detector actually produces. Each
  predicted segment gets a "pseudo-true" label by majority time-overlap
  with a ground-truth execution (or "NOISE" if no execution covers most of
  it) — this is ONLY used to score clustering quality, never fed into the
  clustering itself.

For both phases: sweep a few feature-set variants and clustering distance
thresholds on DEV, pick the best by V-measure, confirm once on the
held-out TEST sessions.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procmine.io import list_sessions, iter_events, load_gt_manifest, split_dev_test  # noqa: E402
from procmine.evaluate import iso_to_ms  # noqa: E402
from procmine.features import extract_segment_features, SegmentFeatures  # noqa: E402
from procmine.label import LabelingConfig, build_feature_matrix, cluster_segments  # noqa: E402
from procmine.segment import SegmentationConfig, segment_session  # noqa: E402

from sklearn.metrics import adjusted_rand_score, v_measure_score, homogeneity_score, completeness_score  # noqa: E402

DATA_A = ROOT / "data" / "dataset_a"
OUT_DIR = ROOT / "reports" / "step1"

FROZEN_SEGMENTATION_CONFIG = SegmentationConfig()  # chosen config from evaluate_segmentation.py


def true_executions(gtm: dict) -> list[tuple[str, int, int]]:
    out = []
    for proc in gtm.get("processes", []):
        for ex in proc.get("executions", []):
            if ex.get("start_ts") and ex.get("end_ts"):
                out.append((proc["code"], iso_to_ms(ex["start_ts"]), iso_to_ms(ex["end_ts"])))
    return out


def slice_events(events: list[dict], s: int, e: int) -> list[dict]:
    return [ev for ev in events if s <= ev["timestamp_ms"] <= e]


def collect_oracle(sessions: list[Path]) -> tuple[list[SegmentFeatures], list[str]]:
    feats_list, labels = [], []
    for ses in sessions:
        gtm = load_gt_manifest(ses)
        if gtm is None:
            continue
        events = list(iter_events(ses))
        for code, s, e in true_executions(gtm):
            seg_events = slice_events(events, s, e)
            feats_list.append(extract_segment_features(ses.name, s, e, seg_events))
            labels.append(code)
    return feats_list, labels


def collect_predicted(sessions: list[Path], seg_config: SegmentationConfig) -> tuple[list[SegmentFeatures], list[str]]:
    feats_list, labels = [], []
    for ses in sessions:
        gtm = load_gt_manifest(ses)
        if gtm is None:
            continue
        events = list(iter_events(ses))
        if not events:
            continue
        true_execs = true_executions(gtm)
        segments = segment_session(events, seg_config)
        for s, e in segments:
            seg_events = slice_events(events, s, e)
            feats_list.append(extract_segment_features(ses.name, s, e, seg_events))
            best_code, best_overlap = None, 0
            for code, ts_, te_ in true_execs:
                overlap = max(0, min(e, te_) - max(s, ts_))
                if overlap > best_overlap:
                    best_overlap, best_code = overlap, code
            seg_dur = max(1, e - s)
            labels.append(best_code if best_code and best_overlap >= 0.5 * seg_dur else "NOISE")
    return feats_list, labels


def score(true_labels: list[str], pred_clusters, exclude_noise: bool = False) -> dict:
    if exclude_noise:
        idx = [i for i, t in enumerate(true_labels) if t != "NOISE"]
        true_labels = [true_labels[i] for i in idx]
        pred_clusters = [pred_clusters[i] for i in idx]
    n_true = len(set(true_labels))
    n_pred = len(set(pred_clusters))
    return {
        "n_segments": len(true_labels),
        "n_true_classes": n_true,
        "n_pred_clusters": n_pred,
        "ari": round(adjusted_rand_score(true_labels, pred_clusters), 4),
        "v_measure": round(v_measure_score(true_labels, pred_clusters), 4),
        "homogeneity": round(homogeneity_score(true_labels, pred_clusters), 4),
        "completeness": round(completeness_score(true_labels, pred_clusters), 4),
    }


FEATURE_VARIANTS = {
    "cat_only": LabelingConfig(use_text=False),
    "cat_plus_text": LabelingConfig(use_text=True, categorical_weight=1.0, text_weight=1.0),
    "text_heavy": LabelingConfig(use_text=True, categorical_weight=0.5, text_weight=1.5),
}
# First pass used a coarse grid [0.3, 0.5, 0.7, 0.9, 1.1, 1.3] and found a
# sharp collapse to a single giant cluster somewhere between 0.3 and 0.5.
# This finer grid resolves what's actually happening in that region: a
# real plateau (V-measure ~0.567-0.570) between 0.25 and 0.32, not a knife
# edge -- see WORKLOG.md. 0.30 (the LabelingConfig default) sits in the
# middle of that plateau.
THRESHOLDS = [0.20, 0.25, 0.28, 0.30, 0.32, 0.35, 0.40, 0.50, 0.70, 1.00]


def sweep(feats_list, labels, exclude_noise=False):
    """Builds the feature matrix ONCE per feature variant (the expensive
    part -- fitting TF-IDF over ~1000+ segments of text), then reuses it
    across every threshold in THRESHOLDS (cheap -- clustering only)."""
    results = {}
    for fname, base_cfg in FEATURE_VARIANTS.items():
        X = build_feature_matrix(feats_list, base_cfg)
        for thr in THRESHOLDS:
            cfg = LabelingConfig(distance_threshold=thr, use_text=base_cfg.use_text,
                                  categorical_weight=base_cfg.categorical_weight,
                                  text_weight=base_cfg.text_weight)
            clusters = cluster_segments(X, cfg)
            results[f"{fname}_thr{thr}"] = score(labels, clusters, exclude_noise=exclude_noise)
    return results


def print_table(results: dict):
    print(f"{'config':28s} {'ARI':>7s} {'V-meas':>7s} {'Homog':>7s} {'Compl':>7s} {'nTrue':>6s} {'nPred':>6s}")
    for name, r in results.items():
        print(f"{name:28s} {r['ari']:7.3f} {r['v_measure']:7.3f} {r['homogeneity']:7.3f} "
              f"{r['completeness']:7.3f} {r['n_true_classes']:6d} {r['n_pred_clusters']:6d}")


def confusion_pairs(true_labels, clusters, top_k=8):
    """Which pairs of TRUE labels most often end up in the SAME cluster —
    a concrete look at what's being confused, not just a summary score."""
    cluster_members = defaultdict(list)
    for t, c in zip(true_labels, clusters):
        cluster_members[c].append(t)
    pair_counts = Counter()
    for members in cluster_members.values():
        counts = Counter(members)
        codes = sorted(counts)
        for i in range(len(codes)):
            for j in range(i + 1, len(codes)):
                pair_counts[(codes[i], codes[j])] += min(counts[codes[i]], counts[codes[j]])
    return pair_counts.most_common(top_k)


def main():
    all_sessions = list_sessions(DATA_A)
    dev, test = split_dev_test(all_sessions)
    print(f"dataset_a sessions: {len(all_sessions)} -> {len(dev)} dev / {len(test)} held-out test\n")

    print("################ PHASE 1: ORACLE segments (true boundaries) ################")
    feats_dev, labels_dev = collect_oracle(dev)
    print(f"dev oracle segments: {len(feats_dev)}, true process classes: {len(set(labels_dev))}\n")
    oracle_dev_results = sweep(feats_dev, labels_dev)
    print_table(oracle_dev_results)

    best_oracle_name = max(oracle_dev_results, key=lambda n: oracle_dev_results[n]["v_measure"])
    print(f"\nBest on DEV by V-measure: {best_oracle_name}")

    feature_name, thr_str = best_oracle_name.rsplit("_thr", 1)
    best_cfg_template = FEATURE_VARIANTS[feature_name]
    best_cfg = LabelingConfig(distance_threshold=float(thr_str), use_text=best_cfg_template.use_text,
                               categorical_weight=best_cfg_template.categorical_weight,
                               text_weight=best_cfg_template.text_weight)

    print(f"\n=== TEST set (oracle segments), config={best_oracle_name} ===")
    feats_test, labels_test = collect_oracle(test)
    X_test = build_feature_matrix(feats_test, best_cfg)
    clusters_test = cluster_segments(X_test, best_cfg)
    test_score = score(labels_test, clusters_test)
    print(json.dumps(test_score, indent=2))
    print("\nTop confused true-label pairs (test, oracle segments):")
    for pair, n in confusion_pairs(labels_test, clusters_test):
        print(f"  {pair}: {n}")

    print("\n################ PHASE 2: PREDICTED segments (our own segmenter) ################")
    feats_dev_p, labels_dev_p = collect_predicted(dev, FROZEN_SEGMENTATION_CONFIG)
    n_noise_dev = sum(1 for l in labels_dev_p if l == "NOISE")
    print(f"dev predicted segments: {len(feats_dev_p)} ({n_noise_dev} = "
          f"{100*n_noise_dev/len(feats_dev_p):.1f}% pseudo-labeled NOISE, excluded from scoring)\n")
    pred_dev_results = sweep(feats_dev_p, labels_dev_p, exclude_noise=True)
    print_table(pred_dev_results)
    print(
        "\nNOTE: NOT re-selecting a threshold here. The table above is a diagnostic "
        "showing how quality varies under segmentation noise, but re-optimizing a "
        "second threshold specifically for predicted segments would be tuning "
        "against information we won't have on dataset_b (no ground truth there "
        "either way, but conceptually this mirrors the same overfitting risk). "
        f"Applying the ORACLE-selected config ({best_oracle_name}) as-is instead, "
        "to measure how much real segmentation noise costs a config chosen "
        "independently of it."
    )

    print(f"\n=== TEST set (predicted segments), config={best_oracle_name} (carried over from Phase 1) ===")
    feats_test_p, labels_test_p = collect_predicted(test, FROZEN_SEGMENTATION_CONFIG)
    n_noise_test = sum(1 for l in labels_test_p if l == "NOISE")
    print(f"test predicted segments: {len(feats_test_p)} ({n_noise_test} = "
          f"{100*n_noise_test/len(feats_test_p):.1f}% pseudo-labeled NOISE, excluded from scoring)")
    X_test_p = build_feature_matrix(feats_test_p, best_cfg)
    clusters_test_p = cluster_segments(X_test_p, best_cfg)
    idx = [i for i, l in enumerate(labels_test_p) if l != "NOISE"]
    test_score_p = score([labels_test_p[i] for i in idx], [clusters_test_p[i] for i in idx])
    print(json.dumps(test_score_p, indent=2))
    print("\nTop confused true-label pairs (test, predicted segments):")
    for pair, n in confusion_pairs([labels_test_p[i] for i in idx], [clusters_test_p[i] for i in idx]):
        print(f"  {pair}: {n}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "oracle_dev_sweep": oracle_dev_results,
        "oracle_best_config": best_oracle_name,
        "oracle_test_score": test_score,
        "predicted_dev_sweep_diagnostic": pred_dev_results,
        "predicted_test_score_using_oracle_config": test_score_p,
        "predicted_config_used": best_oracle_name,
        "predicted_noise_fraction_dev": n_noise_dev / len(feats_dev_p),
        "predicted_noise_fraction_test": n_noise_test / len(feats_test_p),
    }
    with open(OUT_DIR / "labeling_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"\nWrote reports/step1/labeling_results.json")


if __name__ == "__main__":
    main()
