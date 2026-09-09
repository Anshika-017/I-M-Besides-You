#!/usr/bin/env python3
"""Ad-hoc investigation tool (Step 3 feasibility phase): print a condensed,
readable, chronological trace of one segment's raw events -- app/window,
browser route, clicks (with element info), form input (field name only,
not sensitive values unless short/benign), clipboard actions, navigation,
and any extracted_text. Read-only: does not touch segments.jsonl or any
Step 1/2 code or config.

Usage: python3 scripts/trace_workflow.py <session_id> <start_iso> <end_iso>
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procmine.io import iter_events  # noqa: E402

DATA_B = ROOT / "data" / "dataset_b"


def to_ms(iso: str) -> int:
    return int(datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp() * 1000)


def summarize(ev: dict, t0: int) -> str | None:
    dt = (ev["timestamp_ms"] - t0) / 1000.0
    et = ev["event_type"]
    ctx = ev.get("context") or {}
    payload = ev.get("payload") or {}
    app = (ctx.get("active_app") or {}).get("app_name")
    title = (ctx.get("active_app") or {}).get("window_title")
    tab = ctx.get("active_browser_tab") or {}

    if et == "app_switch":
        na = payload.get("new_app", {})
        return f"{dt:6.1f}s  APP_SWITCH      -> {na.get('app_name')}  [{(na.get('window_title') or '')[:60]}]"
    if et == "browser_navigation":
        url = payload.get("url") or payload.get("to_url")
        return f"{dt:6.1f}s  NAVIGATE        -> {url}"
    if et == "browser_click":
        el = (payload.get("element") or {})
        attrs = el.get("attributes") or {}
        label = el.get("text") or attrs.get("aria-label") or attrs.get("placeholder") or attrs.get("id") or el.get("tag")
        return f"{dt:6.1f}s  CLICK           {el.get('tag','?')} '{label}'"
    if et == "browser_form_input":
        field = (payload.get("element") or {}).get("attributes", {}).get("name") or (payload.get("element") or {}).get("attributes", {}).get("id")
        val = payload.get("value")
        val_preview = (str(val)[:40] + "...") if val and len(str(val)) > 40 else val
        return f"{dt:6.1f}s  FORM_INPUT      field='{field}' value='{val_preview}'"
    if et == "clipboard_change":
        cp = payload.get("content_preview") or payload.get("new_content") or payload.get("content")
        cp = (str(cp)[:60]) if cp else None
        return f"{dt:6.1f}s  CLIPBOARD       '{cp}'"
    if et == "mouse_click":
        return f"{dt:6.1f}s  mouse_click     (app={app})"
    if et == "dialog_opened":
        return f"{dt:6.1f}s  DIALOG_OPEN     {payload.get('title') or ''}"
    if et == "dialog_closed":
        return f"{dt:6.1f}s  DIALOG_CLOSE"
    if et == "window_title_change":
        return f"{dt:6.1f}s  TITLE_CHANGE    -> {(title or '')[:70]}"
    if et == "shortcut":
        return f"{dt:6.1f}s  shortcut        {payload.get('key_combo') or payload.get('combo')}"
    return None  # suppress keystroke / screenshot_smart / window_state_change / scroll noise


def main():
    session_id, start_iso, end_iso = sys.argv[1], sys.argv[2], sys.argv[3]
    events = list(iter_events(DATA_B / session_id))
    s, e = to_ms(start_iso), to_ms(end_iso)
    window = [ev for ev in events if s <= ev["timestamp_ms"] <= e]
    print(f"=== {session_id}  {start_iso} -> {end_iso}  ({len(window)} raw events) ===")

    n_keystroke = sum(1 for ev in window if ev["event_type"] == "keystroke")
    n_scroll = sum(1 for ev in window if ev["event_type"] == "mouse_scroll")
    n_screenshot = sum(1 for ev in window if ev["event_type"] == "screenshot_smart")

    for ev in window:
        line = summarize(ev, s)
        if line:
            print(" ", line)

    print(f"  (suppressed: {n_keystroke} keystroke, {n_scroll} scroll, {n_screenshot} screenshot events)")

    # show any extracted_text once (dedup near-identical captures)
    seen_text = set()
    for ev in window:
        t = (ev.get("context") or {}).get("extracted_text")
        if t and t.get("text"):
            key = t["text"][:80]
            if key not in seen_text:
                seen_text.add(key)
                print(f"\n  [extracted_text @ {(ev['timestamp_ms']-s)/1000:.1f}s, source={t.get('source')}]")
                print(" ", t["text"][:600].replace("\n", "\n   "))


if __name__ == "__main__":
    main()
