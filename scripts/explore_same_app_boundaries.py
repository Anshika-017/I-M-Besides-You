#!/usr/bin/env python3
"""Follow-up to explore_dataset_a.py: dig into the ~20-40% of ground-truth
process boundaries that are NOT near an app_switch or browser_navigation
event — the "hard" case for segmentation.

Rather than looking at start/end timestamps independently (as
explore_dataset_a.py did), this script works at the TRANSITION level: for
each session, order ground-truth executions by start time and look at each
(end of execution i -> start of execution i+1) pair. This lets us split
transitions into "same process code both sides" (the classic "case 1 then
case 2 of the same procedure, back to back" pattern the README calls out)
vs "different process code" transitions, and check which group is actually
responsible for the signal-poor boundaries.

For each transition we measure:
  - gap_ms: real elapsed time between end_i and start_{i+1} (from the
    ground truth timestamps themselves, not from any event)
  - nearest app_switch / browser_navigation delta to start_{i+1}
  - whether a clipboard_change or window_title_change event occurs within
    a +/-3s window of start_{i+1} (candidate secondary signals)
  - whether the apps used by execution i and i+1 are identical, overlapping,
    or disjoint (from gt_manifest's own "apps" list per execution)

Prints aggregate stats split by same-process vs different-process, plus a
handful of concrete worked examples (raw events around a few "hard,
same-process" transitions) so the pattern can be inspected directly rather
than only summarized.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procmine.io import list_sessions, iter_events, load_gt_manifest  # noqa: E402

DATA_A = ROOT / "data" / "dataset_a"
OUT_DIR = ROOT / "reports" / "exploration"

NEAR_MS = 1000        # "near an app_switch/navigation" threshold
WINDOW_MS = 3000       # window to look for secondary signals around a boundary


def iso_to_ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def flatten_executions(gtm: dict) -> list[dict]:
    out = []
    for proc in gtm.get("processes", []):
        for ex in proc.get("executions", []):
            if not (ex.get("start_ts") and ex.get("end_ts")):
                continue
            out.append({
                "code": proc["code"],
                "family_name": proc.get("family_name"),
                "case_id": ex.get("case_id"),
                "start_ms": iso_to_ms(ex["start_ts"]),
                "end_ms": iso_to_ms(ex["end_ts"]),
                "apps": set(ex.get("apps") or []),
            })
    out.sort(key=lambda e: e["start_ms"])
    return out


def nearest_delta(target_ms: int, ts_list: list[int]) -> int | None:
    if not ts_list:
        return None
    return min(abs(target_ms - t) for t in ts_list)


def has_event_in_window(target_ms: int, ts_list: list[int], window_ms: int) -> bool:
    return any(abs(target_ms - t) <= window_ms for t in ts_list)


def main():
    sessions = list_sessions(DATA_A)

    rows = []
    for ses in sessions:
        gtm = load_gt_manifest(ses)
        if gtm is None:
            continue
        execs = flatten_executions(gtm)
        if len(execs) < 2:
            continue

        events = list(iter_events(ses))
        appsw_ts = [e["timestamp_ms"] for e in events if e.get("event_type") == "app_switch"]
        nav_ts = [e["timestamp_ms"] for e in events if e.get("event_type") == "browser_navigation"]
        clip_ts = [e["timestamp_ms"] for e in events if e.get("event_type") == "clipboard_change"]
        wtc_ts = [e["timestamp_ms"] for e in events if e.get("event_type") == "window_title_change"]

        for i in range(len(execs) - 1):
            cur, nxt = execs[i], execs[i + 1]
            b = nxt["start_ms"]
            d_appsw = nearest_delta(b, appsw_ts)
            d_nav = nearest_delta(b, nav_ts)
            near_appsw = d_appsw is not None and d_appsw <= NEAR_MS
            near_nav = d_nav is not None and d_nav <= NEAR_MS
            rows.append({
                "session": ses.name,
                "cur_code": cur["code"],
                "nxt_code": nxt["code"],
                "same_process": cur["code"] == nxt["code"],
                "same_case": cur["case_id"] == nxt["case_id"],
                "gap_ms": nxt["start_ms"] - cur["end_ms"],
                "apps_identical": cur["apps"] == nxt["apps"],
                "apps_overlap": bool(cur["apps"] & nxt["apps"]),
                "near_appswitch": near_appsw,
                "near_navigation": near_nav,
                "near_either": near_appsw or near_nav,
                "has_clipboard_nearby": has_event_in_window(b, clip_ts, WINDOW_MS),
                "has_titlechange_nearby": has_event_in_window(b, wtc_ts, WINDOW_MS),
                "boundary_ms": b,
            })

    n = len(rows)
    print(f"Total transitions analyzed: {n}\n")

    for group_name, pred in [
        ("ALL", lambda r: True),
        ("same_process", lambda r: r["same_process"]),
        ("different_process", lambda r: not r["same_process"]),
    ]:
        subset = [r for r in rows if pred(r)]
        m = len(subset)
        if m == 0:
            continue
        near_either = sum(r["near_either"] for r in subset)
        near_appsw = sum(r["near_appswitch"] for r in subset)
        near_nav = sum(r["near_navigation"] for r in subset)
        clip_nearby = sum(r["has_clipboard_nearby"] for r in subset)
        title_nearby = sum(r["has_titlechange_nearby"] for r in subset)
        apps_identical = sum(r["apps_identical"] for r in subset)
        gaps = sorted(r["gap_ms"] for r in subset)
        median_gap = gaps[m // 2]
        print(f"--- {group_name} (n={m}) ---")
        print(f"  near app_switch (<= {NEAR_MS}ms): {near_appsw}/{m} = {100*near_appsw/m:.1f}%")
        print(f"  near browser_navigation (<= {NEAR_MS}ms): {near_nav}/{m} = {100*near_nav/m:.1f}%")
        print(f"  near either: {near_either}/{m} = {100*near_either/m:.1f}%")
        print(f"  apps identical (cur vs next): {apps_identical}/{m} = {100*apps_identical/m:.1f}%")
        print(f"  clipboard_change within +/-{WINDOW_MS}ms of boundary: {clip_nearby}/{m} = {100*clip_nearby/m:.1f}%")
        print(f"  window_title_change within +/-{WINDOW_MS}ms of boundary: {title_nearby}/{m} = {100*title_nearby/m:.1f}%")
        print(f"  gap_ms (real elapsed time between executions): median={median_gap}, "
              f"min={gaps[0]}, max={gaps[-1]}")
        print()

    # The specifically hard bucket: same process, not near either signal
    hard = [r for r in rows if r["same_process"] and not r["near_either"]]
    print(f"=== HARD bucket: same_process AND not near app_switch/navigation (n={len(hard)}) ===")
    if hard:
        gaps = sorted(r["gap_ms"] for r in hard)
        clip_nearby = sum(r["has_clipboard_nearby"] for r in hard)
        title_nearby = sum(r["has_titlechange_nearby"] for r in hard)
        apps_identical = sum(r["apps_identical"] for r in hard)
        print(f"  gap_ms: median={gaps[len(gaps)//2]}, p25={gaps[len(gaps)//4]}, p75={gaps[3*len(gaps)//4]}, "
              f"min={gaps[0]}, max={gaps[-1]}")
        print(f"  apps identical: {apps_identical}/{len(hard)} = {100*apps_identical/len(hard):.1f}%")
        print(f"  clipboard_change nearby: {clip_nearby}/{len(hard)} = {100*clip_nearby/len(hard):.1f}%")
        print(f"  window_title_change nearby: {title_nearby}/{len(hard)} = {100*title_nearby/len(hard):.1f}%")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "same_app_boundaries.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    print(f"\nFull per-transition detail written to reports/exploration/same_app_boundaries.json")

    return rows


if __name__ == "__main__":
    main()
