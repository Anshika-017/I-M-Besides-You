#!/usr/bin/env python3
"""Build and evaluate the Step 1 segmentation algorithm against dataset_a's
ground truth. This is the script that actually decides which configuration
of src/procmine/segment.py we ship — nothing here is applied to dataset_b.

Method:
  1. Split dataset_a's 63 sessions into a DEV set (~50 sessions, used to
     compare configurations) and a held-out TEST set (~13 sessions, never
     looked at until one configuration is chosen). This guards against
     picking a configuration that happens to fit dataset_a's 63 sessions
     as a whole rather than one that generalizes — the same overfitting
     risk the assignment explicitly warns about for dataset_a -> dataset_b,
     just checked one level down first, where we actually have the
     ground truth to check it.
  2. Run a small grid of configurations (see CONFIGS below) on DEV, score
     each with boundary precision/recall/F1 (tolerance 10s, chosen because
     exploration showed the observable-action lag behind the true
     boundary is usually under ~8s) plus mean predicted/true segment count
     ratio (an over/under-segmentation summary) and signed timing error.
  3. Report the DEV comparison table, pick the best configuration, then
     report that ONE configuration's numbers on TEST (the number we
     actually trust).
  4. Pull a handful of concrete failure examples for the chosen
     configuration so errors can be inspected, not just counted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procmine.io import list_sessions, iter_events, load_gt_manifest  # noqa: E402
from procmine.segment import SegmentationConfig, segment_session  # noqa: E402
from procmine.evaluate import (  # noqa: E402
    true_boundaries_from_gt_manifest, predicted_boundaries_from_segments,
    match_boundaries, precision_recall_f1,
)

DATA_A = ROOT / "data" / "dataset_a"
OUT_DIR = ROOT / "reports" / "step1"
TOLERANCE_MS = 10_000

CONFIGS = {
    "V1_naive_debounce_only":
        SegmentationConfig(debounce_ms=2000, min_duration_ms=0, use_idle_fallback=False, use_freshness_filter=False),
    "V2_min5s":
        SegmentationConfig(debounce_ms=2000, min_duration_ms=5000, use_idle_fallback=True, use_freshness_filter=False),
    "V2_min8s":
        SegmentationConfig(debounce_ms=2000, min_duration_ms=8000, use_idle_fallback=True, use_freshness_filter=False),
    "V2_min12s":
        SegmentationConfig(debounce_ms=2000, min_duration_ms=12000, use_idle_fallback=True, use_freshness_filter=False),
    "V2_min15s":
        SegmentationConfig(debounce_ms=2000, min_duration_ms=15000, use_idle_fallback=True, use_freshness_filter=False),
    "V2_min20s":
        SegmentationConfig(debounce_ms=2000, min_duration_ms=20000, use_idle_fallback=True, use_freshness_filter=False),
    "V3_min8s_fresh":
        SegmentationConfig(debounce_ms=2000, min_duration_ms=8000, use_idle_fallback=True, use_freshness_filter=True),
    "V3_min12s_fresh":
        SegmentationConfig(debounce_ms=2000, min_duration_ms=12000, use_idle_fallback=True, use_freshness_filter=True),
    "V3_min15s_fresh":
        SegmentationConfig(debounce_ms=2000, min_duration_ms=15000, use_idle_fallback=True, use_freshness_filter=True),
    "V4_min12s_no_idle":
        SegmentationConfig(debounce_ms=2000, min_duration_ms=12000, use_idle_fallback=False, use_freshness_filter=False),
}


def split_sessions(sessions: list[Path]) -> tuple[list[Path], list[Path]]:
    dev, test = [], []
    for i, s in enumerate(sessions):
        (test if i % 5 == 4 else dev).append(s)
    return dev, test


def describe(values: list[float]) -> dict:
    if not values:
        return {}
    s = sorted(values)
    n = len(s)
    return {"n": n, "min": s[0], "median": s[n // 2], "p90": s[int(0.9 * (n - 1))], "max": s[-1]}


def evaluate_config(sessions: list[Path], config: SegmentationConfig, tolerance_ms: int = TOLERANCE_MS) -> dict:
    total_tp = total_fp = total_fn = 0
    all_errors = []
    seg_count_ratios = []
    per_session = {}

    for ses in sessions:
        gtm = load_gt_manifest(ses)
        if gtm is None:
            continue
        true_ts = true_boundaries_from_gt_manifest(gtm)
        if not true_ts:
            continue
        events = list(iter_events(ses))
        if not events:
            continue
        segments = segment_session(events, config)
        pred_ts = predicted_boundaries_from_segments(segments)

        m = match_boundaries(true_ts, pred_ts, tolerance_ms)
        total_tp += m.tp
        total_fp += m.fp
        total_fn += m.fn
        all_errors.extend(m.signed_errors_ms)

        n_true_segments = sum(1 for p in gtm.get("processes", []) for ex in p.get("executions", [])
                               if ex.get("start_ts") and ex.get("end_ts"))
        if n_true_segments:
            seg_count_ratios.append(len(segments) / n_true_segments)

        per_session[ses.name] = {"tp": m.tp, "fp": m.fp, "fn": m.fn, "n_pred_segments": len(segments),
                                  "n_true_segments": n_true_segments}

    precision, recall, f1 = precision_recall_f1(type("M", (), {"tp": total_tp, "fp": total_fp, "fn": total_fn})())
    return {
        "tp": total_tp, "fp": total_fp, "fn": total_fn,
        "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
        "mean_segment_count_ratio": round(sum(seg_count_ratios) / len(seg_count_ratios), 3) if seg_count_ratios else None,
        "signed_timing_error_ms": describe(all_errors),
        "per_session": per_session,
    }


def main():
    all_sessions = list_sessions(DATA_A)
    dev, test = split_sessions(all_sessions)
    print(f"dataset_a sessions: {len(all_sessions)} total -> {len(dev)} dev / {len(test)} held-out test\n")

    print("=== DEV set: comparing configurations ===")
    print(f"{'config':24s} {'P':>6s} {'R':>6s} {'F1':>6s} {'segRatio':>9s} {'medErr(ms)':>11s} {'TP':>5s} {'FP':>6s} {'FN':>5s}")
    dev_results = {}
    for name, cfg in CONFIGS.items():
        res = evaluate_config(dev, cfg)
        dev_results[name] = res
        med_err = res["signed_timing_error_ms"].get("median", "-")
        print(f"{name:24s} {res['precision']:6.3f} {res['recall']:6.3f} {res['f1']:6.3f} "
              f"{str(res['mean_segment_count_ratio']):>9s} {str(med_err):>11s} "
              f"{res['tp']:5d} {res['fp']:6d} {res['fn']:5d}")

    best_name = max(dev_results, key=lambda n: dev_results[n]["f1"])
    print(f"\nBest on DEV by F1: {best_name} (F1={dev_results[best_name]['f1']})")

    print(f"\n=== TEST set (held out, never used above): {best_name} ===")
    test_res = evaluate_config(test, CONFIGS[best_name])
    print(json.dumps({k: v for k, v in test_res.items() if k != "per_session"}, indent=2))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "dev_comparison.json", "w", encoding="utf-8") as f:
        json.dump({k: {kk: vv for kk, vv in v.items() if kk != "per_session"} for k, v in dev_results.items()},
                   f, indent=2)
    with open(OUT_DIR / "test_result.json", "w", encoding="utf-8") as f:
        json.dump(test_res, f, indent=2)
    with open(OUT_DIR / "chosen_config.json", "w", encoding="utf-8") as f:
        json.dump({"name": best_name, "config": vars(CONFIGS[best_name])}, f, indent=2)
    print(f"\nWrote reports/step1/dev_comparison.json, test_result.json, chosen_config.json")


if __name__ == "__main__":
    main()
