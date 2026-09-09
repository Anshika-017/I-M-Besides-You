#!/usr/bin/env python3
"""Follow-up to explore_same_app_boundaries.py: now that we know
app_switch/browser_navigation events are a good signal for FINDING
boundaries (98.3% coverage within an 8s window), check the flip side —
how many of these events happen INSIDE a single execution, where they must
NOT be treated as a cut point.

For every dated execution in gt_manifest.json, counts app_switch and
browser_navigation events that fall strictly inside the execution's
(start_ts, end_ts) interval, away from the boundaries themselves (using an
8s exclusion margin at each edge, matching the match window we validated
for boundary detection). If naive "every app_switch is a cut" segmentation
were used, each of these interior events would be a false-positive cut.

Also tests one specific hypothesis for telling boundary switches apart from
interior switches: within one execution, does app-switching tend to
"round-trip" back to an app already used earlier in the SAME execution
(e.g. chrome -> excel -> chrome), whereas a boundary switch is more likely
to land on a genuinely new app combination? Measured via the destination
app_name of each switch.
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
BOUNDARY_MARGIN_MS = 8000  # events within this margin of start/end are "boundary", not "interior"


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
                "start_ms": iso_to_ms(ex["start_ts"]),
                "end_ms": iso_to_ms(ex["end_ts"]),
                "apps": ex.get("apps") or [],
            })
    out.sort(key=lambda e: e["start_ms"])
    return out


def describe(values: list[float]) -> dict:
    if not values:
        return {}
    s = sorted(values)
    n = len(s)
    return {
        "n": n, "min": s[0], "median": s[n // 2],
        "p75": s[int(0.75 * (n - 1))], "p90": s[int(0.90 * (n - 1))],
        "max": s[-1], "mean": round(sum(s) / n, 2),
    }


def debounced_count(timestamps: list[int], gap_ms: int = 2000) -> int:
    """Collapse a burst of events that occur within `gap_ms` of each other
    into one. Returns the number of distinct bursts, not the raw count."""
    if not timestamps:
        return 0
    ts = sorted(timestamps)
    bursts = 1
    for a, b in zip(ts, ts[1:]):
        if b - a > gap_ms:
            bursts += 1
    return bursts


def dest_identity(e: dict) -> tuple[str, str] | None:
    """A finer-grained destination identity than app_name alone: (app_name,
    window_title) for app_switch, or (app_name, url) for browser_navigation.
    Two events with the same app_name but different window_title/url are
    treated as different destinations."""
    if e["event_type"] == "app_switch":
        new_app = (e.get("payload") or {}).get("new_app", {}) or {}
        return (new_app.get("app_name"), new_app.get("window_title"))
    if e["event_type"] == "browser_navigation":
        payload = e.get("payload") or {}
        return ("browser", payload.get("url") or payload.get("to_url"))
    return None


def main():
    sessions = list_sessions(DATA_A)

    # burst / debounce and fine-grained-identity accounting
    interior_burst_counts = []
    boundary_fine_repeat = 0
    boundary_fine_fresh = 0
    boundary_fine_checked = 0
    interior_fine_roundtrip = 0
    interior_fine_fresh = 0

    interior_counts = []          # interior signal-events per execution
    n_apps_per_execution = []
    zero_interior = 0
    executions_with_multi_apps = 0
    interior_events_total = 0
    round_trip_count = 0          # interior switch lands on an app already used earlier in same execution
    fresh_count = 0                # interior switch lands on an app not yet used in this execution
    example_sequences = []

    boundary_fresh = 0             # first switch of an execution lands on app not in previous execution's apps
    boundary_repeat = 0
    total_boundaries_checked = 0

    for ses in sessions:
        gtm = load_gt_manifest(ses)
        if gtm is None:
            continue
        execs = flatten_executions(gtm)
        events = list(iter_events(ses))
        signal_events = [e for e in events if e.get("event_type") in ("app_switch", "browser_navigation")]

        for i, ex in enumerate(execs):
            n_apps_per_execution.append(len(set(ex["apps"])))
            if len(set(ex["apps"])) > 1:
                executions_with_multi_apps += 1

            lo = ex["start_ms"] + BOUNDARY_MARGIN_MS
            hi = ex["end_ms"] - BOUNDARY_MARGIN_MS
            interior = [e for e in signal_events if lo < e["timestamp_ms"] < hi] if lo < hi else []
            interior_counts.append(len(interior))
            interior_events_total += len(interior)
            if len(interior) == 0:
                zero_interior += 1
            interior_burst_counts.append(debounced_count([e["timestamp_ms"] for e in interior]))

            seen_apps = set()
            seen_fine = set()
            # seed with the app active at execution start, if we can tell from the first signal event at/before start
            seq_for_example = []
            for e in interior:
                app_name = None
                if e["event_type"] == "app_switch":
                    app_name = (e.get("payload") or {}).get("new_app", {}).get("app_name")
                else:  # browser_navigation
                    app_name = "browser:" + str((e.get("payload") or {}).get("url", ""))[:40]
                seq_for_example.append((e["timestamp_ms"] - ex["start_ms"], e["event_type"], app_name))
                if app_name in seen_apps:
                    round_trip_count += 1
                else:
                    fresh_count += 1
                    seen_apps.add(app_name)

                fid = dest_identity(e)
                if fid is not None:
                    if fid in seen_fine:
                        interior_fine_roundtrip += 1
                    else:
                        interior_fine_fresh += 1
                        seen_fine.add(fid)

            if len(example_sequences) < 6 and len(interior) >= 2:
                example_sequences.append({
                    "session": ses.name, "code": ex["code"], "family_name": ex["family_name"],
                    "duration_s": round((ex["end_ms"] - ex["start_ms"]) / 1000, 1),
                    "declared_apps": ex["apps"],
                    "interior_sequence": seq_for_example,
                })

            # boundary check: the first signal event AT/after start (within margin) -- does its destination
            # app appear among the apps ACTUALLY OBSERVED (via raw app_switch events) during the PREVIOUS
            # execution's own time range? We use raw observed apps rather than gt_manifest's declared
            # "apps" field, because that field turned out to be incomplete (see WORKLOG: e.g. "Microsoft
            # Word" shows up in raw events for executions whose declared apps list doesn't mention word),
            # and because comparing raw app_name to raw app_name avoids a token-format mismatch (declared
            # apps use lowercase short tokens like "chrome"; raw events use display names like
            # "Google Chrome" -- comparing these directly against each other silently never matches).
            if i > 0:
                prev = execs[i - 1]
                prev_observed_apps = {
                    (e.get("payload") or {}).get("new_app", {}).get("app_name")
                    for e in signal_events
                    if e["event_type"] == "app_switch" and prev["start_ms"] <= e["timestamp_ms"] <= prev["end_ms"]
                }
                prev_observed_apps.discard(None)
                prev_observed_fine = {
                    dest_identity(e)
                    for e in signal_events
                    if prev["start_ms"] <= e["timestamp_ms"] <= prev["end_ms"] and dest_identity(e) is not None
                }
                near_start = [e for e in signal_events if abs(e["timestamp_ms"] - ex["start_ms"]) <= BOUNDARY_MARGIN_MS]
                if near_start:
                    e0 = min(near_start, key=lambda e: abs(e["timestamp_ms"] - ex["start_ms"]))
                    dest = None
                    if e0["event_type"] == "app_switch":
                        dest = (e0.get("payload") or {}).get("new_app", {}).get("app_name")
                    if dest:
                        total_boundaries_checked += 1
                        if dest in prev_observed_apps:
                            boundary_repeat += 1
                        else:
                            boundary_fresh += 1
                    fine_dest = dest_identity(e0)
                    if fine_dest is not None:
                        boundary_fine_checked += 1
                        if fine_dest in prev_observed_fine:
                            boundary_fine_repeat += 1
                        else:
                            boundary_fine_fresh += 1

    print("=== Interior (non-boundary) app_switch/browser_navigation events per execution ===")
    print(json.dumps(describe(interior_counts), indent=2))
    print(f"executions with ZERO interior signal events: {zero_interior}/{len(interior_counts)} "
          f"= {100*zero_interior/len(interior_counts):.1f}%")
    print(f"total interior signal events across corpus: {interior_events_total} "
          f"(these would all be false-positive cuts under a naive 'every switch = boundary' rule)")
    print()

    print("=== Number of distinct apps declared per execution (gt_manifest apps field) ===")
    print(json.dumps(describe(n_apps_per_execution), indent=2))
    print(f"executions using >1 app: {executions_with_multi_apps}/{len(n_apps_per_execution)} "
          f"= {100*executions_with_multi_apps/len(n_apps_per_execution):.1f}%")
    print()

    print("=== Round-trip hypothesis: interior switch destination already seen earlier in same execution? ===")
    total_interior_dest = round_trip_count + fresh_count
    if total_interior_dest:
        print(f"round-trip (revisit): {round_trip_count}/{total_interior_dest} = {100*round_trip_count/total_interior_dest:.1f}%")
        print(f"fresh (new app for this execution): {fresh_count}/{total_interior_dest} = {100*fresh_count/total_interior_dest:.1f}%")
    print()

    print("=== Boundary switches: does the destination app appear in the PREVIOUS execution's app set? ===")
    if total_boundaries_checked:
        print(f"checked: {total_boundaries_checked}")
        print(f"dest app was ALSO used by previous execution (ambiguous/repeat): {boundary_repeat} "
              f"= {100*boundary_repeat/total_boundaries_checked:.1f}%")
        print(f"dest app is fresh vs previous execution: {boundary_fresh} "
              f"= {100*boundary_fresh/total_boundaries_checked:.1f}%")
    print()

    print("=== Debounced interior counts (bursts within 2s collapsed to 1) ===")
    print(json.dumps(describe(interior_burst_counts), indent=2))
    print(f"total debounced interior 'bursts': {sum(interior_burst_counts)} "
          f"(vs {interior_events_total} raw interior events)")
    print()

    print("=== Fine-grained identity ([app_name, window_title] or [browser, url]) instead of app_name alone ===")
    total_interior_fine = interior_fine_roundtrip + interior_fine_fresh
    if total_interior_fine:
        print(f"interior: round-trip (revisit same fine identity within same execution): "
              f"{interior_fine_roundtrip}/{total_interior_fine} = {100*interior_fine_roundtrip/total_interior_fine:.1f}%")
        print(f"interior: fresh fine identity: {interior_fine_fresh}/{total_interior_fine} "
              f"= {100*interior_fine_fresh/total_interior_fine:.1f}%")
    if boundary_fine_checked:
        print(f"boundary: dest fine identity ALSO seen in previous execution: "
              f"{boundary_fine_repeat}/{boundary_fine_checked} = {100*boundary_fine_repeat/boundary_fine_checked:.1f}%")
        print(f"boundary: dest fine identity FRESH vs previous execution: "
              f"{boundary_fine_fresh}/{boundary_fine_checked} = {100*boundary_fine_fresh/boundary_fine_checked:.1f}%")
    print()

    print("=== Example interior app-switch sequences (within one execution) ===")
    for ex in example_sequences:
        print(f"\n{ex['session']} | {ex['code']} {ex['family_name']} | duration={ex['duration_s']}s | "
              f"declared_apps={ex['declared_apps']}")
        for dt, etype, app in ex["interior_sequence"]:
            print(f"    +{dt/1000:6.1f}s  {etype:18s} -> {app}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "interior_counts_describe": describe(interior_counts),
        "zero_interior_fraction": zero_interior / len(interior_counts),
        "interior_events_total": interior_events_total,
        "n_apps_per_execution_describe": describe(n_apps_per_execution),
        "executions_with_multi_apps_fraction": executions_with_multi_apps / len(n_apps_per_execution),
        "round_trip_count": round_trip_count,
        "fresh_count": fresh_count,
        "boundary_repeat": boundary_repeat,
        "boundary_fresh": boundary_fresh,
        "total_boundaries_checked": total_boundaries_checked,
        "interior_burst_counts_describe": describe(interior_burst_counts),
        "interior_burst_total": sum(interior_burst_counts),
        "interior_fine_roundtrip": interior_fine_roundtrip,
        "interior_fine_fresh": interior_fine_fresh,
        "boundary_fine_repeat": boundary_fine_repeat,
        "boundary_fine_fresh": boundary_fine_fresh,
        "boundary_fine_checked": boundary_fine_checked,
        "example_sequences": example_sequences,
    }
    with open(OUT_DIR / "oversegmentation.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nFull detail written to reports/exploration/oversegmentation.json")


if __name__ == "__main__":
    main()
