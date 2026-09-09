"""Feature extraction for the labeling stage: turn a (start_ms, end_ms)
segment into a description of what happened during it, so that segments
from the same real business process end up looking similar to each other
and segments from different processes look different — that's what the
clustering step in `label.py` needs.

Checked before building this (see WORKLOG.md): 99.5% of dataset_a's
ground-truth executions have at least one event with non-empty
`context.extracted_text`, with a median of ~2,225 characters of on-screen
text per execution. That's much richer than the raw "~4% of events have
extracted_text" figure in DATA_SCHEMA.md suggests — over a ~30s execution
with dozens of events, at least one usually catches text. So screen text
is used as a feature, not just app/window identity.

Three feature groups per segment:
  - `app_counts`: how much time-weighted evidence there is for each
    active application during the segment (from `context.active_app`,
    present on nearly every event, not just app_switch events).
  - `route_counts`: coarse browser routes visited (the SPA hash-route
    path, e.g. "#/payroll-items" — see WORKLOG.md's single-page-app
    finding — with any trailing numeric/id-looking path segment stripped,
    so two different case IDs on the same page count as the same route).
  - `text`: all `extracted_text` seen during the segment, concatenated.
    Turned into features by the caller (a char n-gram TF-IDF vectorizer in
    `label.py`), not here — this module only collects the raw text.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field


_ID_SEGMENT_RE = re.compile(r"^[0-9a-fA-F-]{3,}$")


def _coarse_route(url: str) -> str | None:
    """Reduce a URL to a stable route signature: keep the hash-routing
    path, drop query strings, and replace path segments that look like
    IDs (all-digit, or long hex/uuid-like tokens) with a placeholder so
    "#/cases/482" and "#/cases/119" collapse to the same route."""
    if not url:
        return None
    frag = url.split("#", 1)[1] if "#" in url else url
    frag = frag.split("?", 1)[0]
    parts = [p for p in frag.split("/") if p]
    norm = []
    for p in parts:
        if p.isdigit() or _ID_SEGMENT_RE.match(p):
            norm.append("<id>")
        else:
            norm.append(p)
    return "#/" + "/".join(norm) if norm else None


@dataclass
class SegmentFeatures:
    session_id: str
    start_ms: int
    end_ms: int
    app_counts: Counter = field(default_factory=Counter)
    route_counts: Counter = field(default_factory=Counter)
    text_parts: list = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(self.text_parts)


def extract_segment_features(session_id: str, start_ms: int, end_ms: int, events: list[dict]) -> SegmentFeatures:
    """`events` should already be filtered/sliced to roughly this
    segment's time range by the caller (see `label.py`), which knows the
    full session's event list and can slice efficiently rather than
    filtering the whole session per segment."""
    feats = SegmentFeatures(session_id=session_id, start_ms=start_ms, end_ms=end_ms)
    for e in events:
        ctx = e.get("context") or {}
        app = (ctx.get("active_app") or {}).get("app_name")
        if app:
            feats.app_counts[app] += 1

        tab = ctx.get("active_browser_tab") or {}
        route = _coarse_route(tab.get("url") or "")
        if route:
            feats.route_counts[route] += 1
        if e.get("event_type") == "browser_navigation":
            payload = e.get("payload") or {}
            route = _coarse_route(payload.get("url") or payload.get("to_url") or "")
            if route:
                feats.route_counts[route] += 1

        extracted = ctx.get("extracted_text")
        if extracted and extracted.get("text"):
            feats.text_parts.append(extracted["text"])

    return feats
