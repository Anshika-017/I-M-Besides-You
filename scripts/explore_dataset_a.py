#!/usr/bin/env python3
"""Exploration pass over Dataset A: understand the raw event stream and the
ground truth well enough to design a segmentation approach for Step 1.

This script does not implement segmentation. It only measures things we need
to know before designing it:

  1. Corpus shape (events/session, chunks/session, event type mix) — read
     for free from each chunk's manifest.json, no need to open events.jsonl.
  2. Ground truth shape from gt_manifest.json — how many process executions
     exist, how long they run, how many variants per process, how often an
     execution is split across a continuation boundary.
  3. The quirks DATA_SCHEMA.md warns about in gt.jsonl (duplicate
     process_started, unpaired process_switched_out) — quantified, not just
     acknowledged.
  4. The key question for segmentation design: do raw event-stream signals
     (app_switch events, idle gaps between events) actually line up with
     where gt_manifest.json says a process execution starts/ends? This is
     tested against a random-timestamp control group so "app switches are
     near boundaries" is a measured claim, not an assumption.

Writes a detailed JSON dump to reports/exploration/dataset_a_summary.json
and prints a concise summary to stdout.
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procmine.io import list_sessions, list_chunks, load_manifest, iter_events, load_gt, load_gt_manifest  # noqa: E402

DATA_A = ROOT / "data" / "dataset_a"
OUT_DIR = ROOT / "reports" / "exploration"


def iso_to_ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def corpus_overview(sessions: list[Path]) -> dict:
    """Cheap pass: sum up each chunk's precomputed manifest statistics
    instead of opening events.jsonl. Manifests already contain per-chunk
    event_type/layer counts, so we get corpus-wide totals for free."""
    chunks_per_session = []
    events_per_session = []
    type_counts = Counter()
    layer_counts = Counter()

    for ses in sessions:
        chunks = list_chunks(ses)
        chunks_per_session.append(len(chunks))
        n_events = 0
        for c in chunks:
            m = load_manifest(c)
            n_events += m["statistics"]["total_events"]
            for k, v in m["statistics"]["events_by_type"].items():
                type_counts[k] += v
            for k, v in m["statistics"]["events_by_layer"].items():
                layer_counts[k] += v
        events_per_session.append(n_events)

    return {
        "n_sessions": len(sessions),
        "chunks_per_session": describe(chunks_per_session),
        "events_per_session": describe(events_per_session),
        "event_type_counts": dict(type_counts.most_common()),
        "layer_counts": dict(layer_counts.most_common()),
    }


def describe(values: list[float]) -> dict:
    if not values:
        return {}
    s = sorted(values)
    return {
        "n": len(s),
        "min": s[0],
        "p25": pct(s, 0.25),
        "median": pct(s, 0.5),
        "p75": pct(s, 0.75),
        "p95": pct(s, 0.95),
        "max": s[-1],
        "mean": round(statistics.mean(s), 1),
    }


def pct(sorted_values: list[float], q: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = q * (len(sorted_values) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def gt_manifest_overview(sessions: list[Path]) -> dict:
    process_info = {}  # code -> {family_name, domain, count}
    variants_by_process = defaultdict(Counter)
    durations_sec = []
    continuation_count = 0
    total_executions = 0
    executions_per_session = []
    session_span_sec = []
    covered_sec_per_session = []

    for ses in sessions:
        gtm = load_gt_manifest(ses)
        if gtm is None:
            continue
        session_start = iso_to_ms(gtm["session"]["start_ts"]) if gtm["session"].get("start_ts") else None
        session_end = iso_to_ms(gtm["session"]["end_ts"]) if gtm["session"].get("end_ts") else None
        covered_ms = 0
        n_exec_this_session = 0
        for proc in gtm.get("processes", []):
            code = proc["code"]
            if code not in process_info:
                process_info[code] = {
                    "family_name": proc.get("family_name"),
                    "domain": proc.get("domain"),
                    "count": 0,
                    "sessions": set(),
                }
            for ex in proc.get("executions", []):
                total_executions += 1
                n_exec_this_session += 1
                process_info[code]["count"] += 1
                process_info[code]["sessions"].add(ses.name)
                variants_by_process[code][ex.get("variant")] += 1
                st, en = ex.get("start_ts"), ex.get("end_ts")
                if st and en:
                    dur = (iso_to_ms(en) - iso_to_ms(st)) / 1000.0
                    durations_sec.append(dur)
                    covered_ms += max(0, iso_to_ms(en) - iso_to_ms(st))
                if ex.get("continues_from_prev") or ex.get("continues_to_next"):
                    continuation_count += 1
        executions_per_session.append(n_exec_this_session)
        if session_start and session_end:
            span = (session_end - session_start) / 1000.0
            session_span_sec.append(span)
            covered_sec_per_session.append(covered_ms / 1000.0)

    # convert sets to counts for JSON-friendliness
    processes_summary = {
        code: {
            "family_name": info["family_name"],
            "domain": info["domain"],
            "n_executions": info["count"],
            "n_sessions_appearing_in": len(info["sessions"]),
            "variants": dict(variants_by_process[code]),
        }
        for code, info in sorted(process_info.items())
    }

    coverage_ratio = [
        c / s for c, s in zip(covered_sec_per_session, session_span_sec) if s > 0
    ]

    return {
        "n_distinct_processes": len(process_info),
        "total_executions": total_executions,
        "executions_per_session": describe(executions_per_session),
        "execution_duration_sec": describe(durations_sec),
        "executions_with_continuation_flag": continuation_count,
        "session_span_sec": describe(session_span_sec),
        "fraction_of_session_time_covered_by_some_execution": describe(coverage_ratio),
        "processes": processes_summary,
    }


def gt_jsonl_quirks(sessions: list[Path]) -> dict:
    event_type_counts = Counter()
    duplicate_process_started = 0
    total_process_started = 0
    switched_out_count = 0
    suspended_count = 0
    resumed_count = 0

    for ses in sessions:
        gt = load_gt(ses)
        prev = None
        for rec in gt:
            ev = rec.get("event")
            event_type_counts[ev] += 1
            if ev == "process_started":
                total_process_started += 1
                if prev and prev.get("event") == "process_started" and prev.get("process_code") == rec.get("process_code") and prev.get("case_id") == rec.get("case_id"):
                    duplicate_process_started += 1
            elif ev == "process_switched_out":
                switched_out_count += 1
            elif ev == "process_suspended":
                suspended_count += 1
            elif ev == "process_resumed":
                resumed_count += 1
            prev = rec

    return {
        "event_type_counts": dict(event_type_counts.most_common()),
        "process_started_total": total_process_started,
        "process_started_immediate_duplicates": duplicate_process_started,
        "process_switched_out_total": switched_out_count,
        "process_suspended_total": suspended_count,
        "process_resumed_total": resumed_count,
    }


def boundary_signal_analysis(sessions: list[Path], sample_sessions: int = 63, seed: int = 42) -> dict:
    """For each execution boundary (start_ts, end_ts) from gt_manifest, find
    the nearest raw event in events.jsonl and measure:
      - time delta to nearest event of any kind
      - time delta to nearest app_switch event
      - the ms_since_last_event value of the nearest event (i.e. was there
        an idle gap right at this boundary?)
    Compared against the same measurements at random (non-boundary)
    timestamps within the same sessions, as a control.
    """
    rng = random.Random(seed)
    boundary_nearest_any_ms = []
    boundary_nearest_appswitch_ms = []
    boundary_gap_before_ms = []  # ms_since_last_event of the nearest event

    control_nearest_any_ms = []
    control_nearest_appswitch_ms = []
    control_gap_before_ms = []

    sessions_to_use = sessions[:sample_sessions]

    for ses in sessions_to_use:
        gtm = load_gt_manifest(ses)
        if gtm is None:
            continue

        events = list(iter_events(ses))
        if not events:
            continue
        timestamps = [e["timestamp_ms"] for e in events]
        gaps = [e.get("correlation", {}).get("ms_since_last_event") for e in events]
        appswitch_timestamps = [e["timestamp_ms"] for e in events if e.get("event_type") == "app_switch"]

        boundaries_ms = []
        for proc in gtm.get("processes", []):
            for ex in proc.get("executions", []):
                for key in ("start_ts", "end_ts"):
                    ts = ex.get(key)
                    if ts:
                        boundaries_ms.append(iso_to_ms(ts))

        def nearest_delta(target_ms: int, ts_list: list[int]) -> int | None:
            if not ts_list:
                return None
            # binary search would be faster; linear is fine at this scale
            return min(abs(target_ms - t) for t in ts_list)

        def nearest_index(target_ms: int, ts_list: list[int]) -> int:
            best_i, best_d = 0, abs(target_ms - ts_list[0])
            for i, t in enumerate(ts_list):
                d = abs(target_ms - t)
                if d < best_d:
                    best_d, best_i = d, i
            return best_i

        for b in boundaries_ms:
            i = nearest_index(b, timestamps)
            boundary_nearest_any_ms.append(abs(b - timestamps[i]))
            g = gaps[i]
            if g is not None:
                boundary_gap_before_ms.append(g)
            d = nearest_delta(b, appswitch_timestamps)
            if d is not None:
                boundary_nearest_appswitch_ms.append(d)

        # control: same number of random timestamps within session span
        if timestamps:
            lo, hi = timestamps[0], timestamps[-1]
            for _ in range(len(boundaries_ms)):
                t = rng.randint(lo, hi)
                i = nearest_index(t, timestamps)
                control_nearest_any_ms.append(abs(t - timestamps[i]))
                g = gaps[i]
                if g is not None:
                    control_gap_before_ms.append(g)
                d = nearest_delta(t, appswitch_timestamps)
                if d is not None:
                    control_nearest_appswitch_ms.append(d)

    return {
        "n_boundaries": len(boundary_nearest_any_ms),
        "boundary_nearest_event_delta_ms": describe(boundary_nearest_any_ms),
        "boundary_nearest_appswitch_delta_ms": describe(boundary_nearest_appswitch_ms),
        "boundary_ms_since_last_event_at_nearest": describe(boundary_gap_before_ms),
        "control_nearest_event_delta_ms": describe(control_nearest_any_ms),
        "control_nearest_appswitch_delta_ms": describe(control_nearest_appswitch_ms),
        "control_ms_since_last_event_at_nearest": describe(control_gap_before_ms),
    }


def main():
    sessions = list_sessions(DATA_A)
    print(f"Found {len(sessions)} dataset_a sessions.\n")

    print("=== 1. Corpus overview (from manifest.json, no events.jsonl reads) ===")
    corpus = corpus_overview(sessions)
    print(json.dumps({k: v for k, v in corpus.items() if k != "event_type_counts"}, indent=2))
    print("event_type_counts:", corpus["event_type_counts"])
    print()

    print("=== 2. gt_manifest.json overview (ground truth structure) ===")
    gtm_overview = gt_manifest_overview(sessions)
    print(json.dumps({k: v for k, v in gtm_overview.items() if k != "processes"}, indent=2))
    print("\nProcesses:")
    for code, info in gtm_overview["processes"].items():
        print(f"  {code}: {info['family_name']} [{info['domain']}] "
              f"executions={info['n_executions']} sessions={info['n_sessions_appearing_in']} "
              f"variants={info['variants']}")
    print()

    print("=== 3. gt.jsonl quirks ===")
    quirks = gt_jsonl_quirks(sessions)
    print(json.dumps(quirks, indent=2))
    print()

    print("=== 4. Boundary vs raw-event-signal analysis (this is the key one) ===")
    boundary = boundary_signal_analysis(sessions)
    print(json.dumps(boundary, indent=2))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "corpus_overview": corpus,
        "gt_manifest_overview": gtm_overview,
        "gt_jsonl_quirks": quirks,
        "boundary_signal_analysis": boundary,
    }
    out_path = OUT_DIR / "dataset_a_summary.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nFull detail written to {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
