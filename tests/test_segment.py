"""Unit tests for the core segmentation logic. These don't touch the
dataset — they test the boundary-generation/filtering rules in isolation
against small synthetic event lists, so a change to the algorithm's logic
fails fast without needing to run the full dataset_a evaluation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.segment import (  # noqa: E402
    SegmentationConfig, _debounce, _merge_short_segments, segment_session, dest_identity,
)


def app_switch(ts_ms, app_name, window_title=""):
    return {
        "event_type": "app_switch",
        "timestamp_ms": ts_ms,
        "payload": {"new_app": {"app_name": app_name, "window_title": window_title}},
    }


def other_event(ts_ms, event_type="keystroke"):
    return {"event_type": event_type, "timestamp_ms": ts_ms}


def test_debounce_collapses_burst_to_first_event():
    events = [app_switch(1000, "chrome"), app_switch(1500, "chrome"), app_switch(2500, "chrome")]
    candidates = _debounce(events, debounce_ms=2000)
    assert len(candidates) == 1
    assert candidates[0].ts_ms == 1000


def test_debounce_keeps_separated_events_distinct():
    events = [app_switch(1000, "chrome"), app_switch(10000, "excel")]
    candidates = _debounce(events, debounce_ms=2000)
    assert [c.ts_ms for c in candidates] == [1000, 10000]


def test_merge_short_segments_drops_boundary_too_close_to_previous():
    # boundary at 5000 would create a 5s segment after a boundary at 0 (session start)
    edges = _merge_short_segments(boundaries=[5000, 20000], session_start=0, session_end=30000, min_duration_ms=10000)
    assert edges == [0, 20000, 30000]


def test_merge_short_segments_keeps_boundary_far_enough_away():
    edges = _merge_short_segments(boundaries=[15000], session_start=0, session_end=30000, min_duration_ms=10000)
    assert edges == [0, 15000, 30000]


def test_segment_session_covers_full_span_with_no_gaps():
    events = [
        other_event(0),
        app_switch(20000, "excel"),
        app_switch(45000, "chrome"),
        other_event(60000),
    ]
    cfg = SegmentationConfig(debounce_ms=2000, min_duration_ms=10000, use_idle_fallback=False)
    segments = segment_session(events, cfg)
    assert segments[0][0] == 0
    assert segments[-1][1] == 60000
    for (s1, e1), (s2, e2) in zip(segments, segments[1:]):
        assert e1 == s2, "segments must exactly tile the session with no gaps or overlaps"


def test_segment_session_empty_input():
    assert segment_session([], SegmentationConfig()) == []


def test_dest_identity_distinguishes_same_app_different_window():
    a = dest_identity(app_switch(0, "Google Chrome", "HR Portal"))
    b = dest_identity(app_switch(0, "Google Chrome", "Finance Portal"))
    assert a != b
    assert a[0:2] == b[0:2] == ("app", "Google Chrome")
