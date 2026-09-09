"""Evaluate predicted (start_ms, end_ms) segments against dataset_a's
ground truth (`gt_manifest.json`).

Methodology: both the true executions and the predicted segments are
reduced to a set of "cut point" timestamps (every segment's start and end
edge). A predicted cut point counts as correct (a true positive) if it
lands within `tolerance_ms` of some true cut point, matched greedily
nearest-first with a one-to-one constraint (each true cut point can match
at most one predicted cut point and vice versa). This is a boundary-level
evaluation, not a segment-overlap one — it directly measures "did we find
the transitions" rather than "does the label match" (label assignment is a
separate, later step — see segment.py's module docstring).

Greedy nearest-first matching is not a globally optimal assignment (that
would need something like the Hungarian algorithm), but boundaries are
sparse relative to the tolerance windows used here, so the two rarely
disagree in practice and greedy matching is far simpler to read and audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


def iso_to_ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _dedupe(sorted_ts: list[int], eps_ms: int) -> list[int]:
    """Collapse timestamps within eps_ms of each other into one. Needed
    because a true execution's end_ts and the next execution's start_ts
    are frequently (median 2ms apart in dataset_a) the same real-world
    moment and shouldn't be counted as two separate boundaries."""
    out = []
    for t in sorted_ts:
        if out and t - out[-1] <= eps_ms:
            continue
        out.append(t)
    return out


def true_boundaries_from_gt_manifest(gtm: dict, dedupe_ms: int = 500) -> list[int]:
    ts = []
    for proc in gtm.get("processes", []):
        for ex in proc.get("executions", []):
            for key in ("start_ts", "end_ts"):
                v = ex.get(key)
                if v:
                    ts.append(iso_to_ms(v))
    return _dedupe(sorted(ts), dedupe_ms)


def predicted_boundaries_from_segments(segments: list[tuple[int, int]], dedupe_ms: int = 500) -> list[int]:
    ts = []
    for s, e in segments:
        ts.append(s)
        ts.append(e)
    return _dedupe(sorted(ts), dedupe_ms)


@dataclass
class MatchResult:
    tp: int
    fp: int
    fn: int
    # signed: predicted_ts - true_ts, for each matched pair. Positive means
    # the predicted boundary lagged the true one (expected, given the
    # ~3-6s observable-action lag found during exploration).
    signed_errors_ms: list[int] = field(default_factory=list)


def match_boundaries(true_ts: list[int], pred_ts: list[int], tolerance_ms: int) -> MatchResult:
    candidates = []
    for i, t in enumerate(true_ts):
        for j, p in enumerate(pred_ts):
            d = abs(t - p)
            if d <= tolerance_ms:
                candidates.append((d, i, j))
    candidates.sort(key=lambda x: x[0])
    matched_true, matched_pred = set(), set()
    errors = []
    for d, i, j in candidates:
        if i in matched_true or j in matched_pred:
            continue
        matched_true.add(i)
        matched_pred.add(j)
        errors.append(pred_ts[j] - true_ts[i])
    tp = len(matched_true)
    fn = len(true_ts) - tp
    fp = len(pred_ts) - tp
    return MatchResult(tp=tp, fp=fp, fn=fn, signed_errors_ms=errors)


def precision_recall_f1(m: MatchResult) -> tuple[float, float, float]:
    p = m.tp / (m.tp + m.fp) if (m.tp + m.fp) else 0.0
    r = m.tp / (m.tp + m.fn) if (m.tp + m.fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1
