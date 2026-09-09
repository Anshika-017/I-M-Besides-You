"""Step 1 segmentation: cut a session's event stream into candidate
business-process-execution spans (start_ms, end_ms).

This module implements ONLY boundary detection (deciding where one
execution ends and the next begins). Assigning a consistent label to each
segment (e.g. clustering same-process segments together so the same real
process gets the same label) is a separate, later step — seeing whether we
can even find the right CUTS is a big enough question on its own, and the
two problems use different evidence. See WORKLOG.md for the full reasoning
trail behind every design choice below.

Design is evidence-based, built directly on findings in
`reports/exploration/*.json`:

  - `app_switch` and `browser_navigation` events sit within ~8s of ~98% of
    ground-truth process boundaries (`explore_same_app_boundaries.py`).
    That's the primary candidate-generation signal.
  - But most such events do NOT mark a boundary — a single execution
    typically contains several of them too (median 2 per execution, up to
    142) as the worker bounces between the same handful of apps
    (`explore_oversegmentation.py`). Naively cutting on every one of them
    would over-segment by ~4-5x.
  - App identity alone barely tells a real boundary apart from an interior
    switch: 92.3% of true boundaries reuse an app also used in the
    execution right before them, because the whole environment only has
    ~5-6 applications total. Finer-grained identity — (app_name,
    window_title) or (browser, url), exploiting that these portals are
    single-page apps with distinct hash routes per page — helps some
    (7.7% -> 35.7% "introduces something new" rate at true boundaries) but
    isn't a clean standalone rule either.
  - Debouncing near-simultaneous events (a lot of raw "switches" are
    focus-flicker within the same UI action, e.g. 15+ app_switch events in
    a 2-second span in one observed example) cuts candidate noise by more
    than half (-57%) without materially hurting recall.
  - The shortest real execution observed in dataset_a is ~16.6s; segments
    much shorter than that are far more likely to be leftover fragments
    from noisy candidates than real distinct executions.

The algorithm therefore works in three stages, each directly answering one
of the findings above:

  1. CANDIDATE GENERATION (`generate_candidates`): every debounced
     app_switch/browser_navigation burst is a candidate cut point. A
     self-computed idle-gap fallback adds candidates in stretches with no
     such event at all (covers dataset_a's small residual of boundaries
     with no nearby signal event at all).
  2. FILTERING (`_merge_short_segments`): candidates that would create a
     segment shorter than `min_duration_ms` get dropped (merged into the
     still-open segment). This directly targets the over-segmentation
     problem.
  3. FRESHNESS WEIGHTING (`_apply_freshness_filter`, optional):
     candidates whose destination was already seen recently in the
     currently-open segment can be suppressed. This is tested as a
     variant, NOT assumed to help — see `scripts/evaluate_segmentation.py`
     for whether it actually improves results.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


def dest_identity(event: dict) -> Optional[tuple]:
    """A destination identity for a candidate-boundary event, finer
    grained than app_name alone. Comparing raw app_name strings is the
    right thing to do here (not gt_manifest's declared "apps" tokens,
    which use a different, incompatible naming format and were shown in
    exploration to be incomplete anyway)."""
    et = event.get("event_type")
    if et == "app_switch":
        new_app = (event.get("payload") or {}).get("new_app") or {}
        return ("app", new_app.get("app_name"), new_app.get("window_title"))
    if et == "browser_navigation":
        payload = event.get("payload") or {}
        url = payload.get("url") or payload.get("to_url")
        return ("browser", url)
    return None


@dataclass
class SegmentationConfig:
    """Defaults here are the configuration chosen by
    `scripts/evaluate_segmentation.py` (config name `V2_min15s`) after
    comparing 10 variants on a dev split of dataset_a and confirming the
    choice on a held-out test split. See `reports/step1/` for the full
    comparison table and WORKLOG.md for the reasoning. Headline numbers on
    the held-out test split (10s matching tolerance): precision 0.545,
    recall 0.937, F1 0.689. `use_freshness_filter` was tested and made
    results worse at this min_duration (it trades away real recall for
    only a small precision gain) so it defaults to off.
    """
    debounce_ms: int = 2000
    min_duration_ms: int = 15000
    idle_gap_ms: int = 8000
    use_idle_fallback: bool = True
    use_freshness_filter: bool = False
    freshness_lookback_ms: int = 30000


@dataclass
class Candidate:
    ts_ms: int
    source: str  # "signal" or "idle"
    identity: Optional[tuple]


def _debounce(signal_events: list[dict], debounce_ms: int) -> list[Candidate]:
    """Collapse bursts of app_switch/browser_navigation events that occur
    within `debounce_ms` of each other into a single candidate, taken at
    the burst's first event (that's when the transition began)."""
    if not signal_events:
        return []
    candidates = []
    burst_start = signal_events[0]
    last_ts = signal_events[0]["timestamp_ms"]
    for e in signal_events[1:]:
        if e["timestamp_ms"] - last_ts > debounce_ms:
            candidates.append(Candidate(burst_start["timestamp_ms"], "signal", dest_identity(burst_start)))
            burst_start = e
        last_ts = e["timestamp_ms"]
    candidates.append(Candidate(burst_start["timestamp_ms"], "signal", dest_identity(burst_start)))
    return candidates


def _idle_gap_candidates(events: list[dict], idle_gap_ms: int, existing: list[Candidate]) -> list[Candidate]:
    """Self-computed idle gaps (from our own sorted timestamps — NOT the
    recording agent's `ms_since_last_event` field, which was shown during
    exploration to be unreliable exactly where it would matter) that
    aren't already covered by a nearby signal-based candidate."""
    existing_ts = sorted(c.ts_ms for c in existing)
    out = []
    for a, b in zip(events, events[1:]):
        gap = b["timestamp_ms"] - a["timestamp_ms"]
        if gap >= idle_gap_ms:
            t = b["timestamp_ms"]
            if not any(abs(t - et) <= idle_gap_ms for et in existing_ts):
                out.append(Candidate(t, "idle", None))
    return out


def generate_candidates(events: list[dict], config: SegmentationConfig) -> list[Candidate]:
    signal_events = [e for e in events if e.get("event_type") in ("app_switch", "browser_navigation")]
    candidates = _debounce(signal_events, config.debounce_ms)
    if config.use_idle_fallback:
        candidates = candidates + _idle_gap_candidates(events, config.idle_gap_ms, candidates)
    candidates.sort(key=lambda c: c.ts_ms)
    return candidates


def _apply_freshness_filter(candidates: list[Candidate], config: SegmentationConfig) -> list[Candidate]:
    """Optional: suppress candidates whose destination identity was
    already seen within the last `freshness_lookback_ms` (likely a
    round-trip within the current segment, not a new one). This signal is
    real but weak on its own (measured 35.7% vs 7.7% baseline "introduces
    something new" rate) — tested here as a variant, not assumed to help
    the end-to-end result."""
    kept = []
    recent: list[tuple[int, tuple]] = []  # (ts_ms, identity), sliding window
    for c in candidates:
        recent = [(t, i) for t, i in recent if c.ts_ms - t <= config.freshness_lookback_ms]
        is_repeat = c.identity is not None and any(i == c.identity for _, i in recent)
        if c.source == "idle" or not is_repeat:
            kept.append(c)
        if c.identity is not None:
            recent.append((c.ts_ms, c.identity))
    return kept


def _merge_short_segments(boundaries: list[int], session_start: int, session_end: int, min_duration_ms: int) -> list[int]:
    """Drop any candidate boundary that would create a segment shorter
    than `min_duration_ms` since the last kept boundary (i.e. merge it
    into the still-open segment). The session's own start/end are always
    kept as the outer edges."""
    edges = [session_start] + sorted(boundaries) + [session_end]
    kept = [edges[0]]
    for t in edges[1:-1]:
        if t - kept[-1] >= min_duration_ms:
            kept.append(t)
    kept.append(session_end)
    return kept


def segment_session(events: list[dict], config: SegmentationConfig) -> list[tuple[int, int]]:
    """Cut one session's chronological event list into (start_ms, end_ms)
    segments covering the whole session.

    Note: this covers 100% of the session's time span, including stretches
    that are really "noise"/unrelated activity rather than a labeled
    business process (recall: ~20% of session time in dataset_a isn't
    covered by any ground-truth execution). Telling apart a real process
    segment from a noise segment is deferred to the labeling stage, not
    attempted here — see module docstring.
    """
    if not events:
        return []
    session_start = events[0]["timestamp_ms"]
    session_end = events[-1]["timestamp_ms"]
    if session_start == session_end:
        return [(session_start, session_end)]

    candidates = generate_candidates(events, config)
    if config.use_freshness_filter:
        candidates = _apply_freshness_filter(candidates, config)

    boundary_ts = [c.ts_ms for c in candidates if session_start < c.ts_ms < session_end]
    edges = _merge_short_segments(boundary_ts, session_start, session_end, config.min_duration_ms)
    return list(zip(edges, edges[1:]))
