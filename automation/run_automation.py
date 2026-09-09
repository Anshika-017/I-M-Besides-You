#!/usr/bin/env python3
"""Step 3 prototype: browser automation for the expense-settlement
confirmation sub-flow (see reports/step3/step3_prototype.md for the full
writeup). Drives the mock app (automation/mock_app.py) with Playwright,
using the exact DOM interaction observed in dataset_b:

    click 4th-column <td> of a pending row
      -> fill #pi-note with a note
      -> click #btn-pi-ok
      -> verify the row now shows "confirmed"

For every item: decide via automation/decision.py (pure business logic,
no AI/LLM, no invented thresholds -- see that module's citations) whether
to AUTO_CONFIRM or route to HUMAN_REVIEW. HUMAN_REVIEW items are left
completely untouched in the queue (never clicked, never guessed at) and
written to a review file instead.

Usage:
    python3 automation/run_automation.py
Starts the mock app itself if it isn't already running on :5001, runs the
automation headless, writes output under automation/output/, and leaves
the mock app running afterward so the result can also be inspected by hand
at http://127.0.0.1:5001/.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from decision import decide, Outcome  # noqa: E402

APP_URL = "http://127.0.0.1:5001"
OUT_DIR = Path(__file__).resolve().parent / "output"


def ensure_app_running() -> subprocess.Popen | None:
    try:
        urllib.request.urlopen(APP_URL, timeout=1)
        print(f"Mock app already running at {APP_URL}")
        return None
    except Exception:
        pass
    print("Starting mock app (automation/mock_app.py) ...")
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve().parent / "mock_app.py")],
        cwd=str(Path(__file__).resolve().parent),
    )
    for _ in range(30):
        try:
            urllib.request.urlopen(APP_URL, timeout=1)
            print(f"Mock app ready at {APP_URL}")
            return proc
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("Mock app did not start in time")


def reset_app():
    urllib.request.urlopen(urllib.request.Request(f"{APP_URL}/api/reset", method="POST"), timeout=2)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    started_proc = ensure_app_running()
    reset_app()

    log = []
    auto_confirmed = []
    human_review = []
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(APP_URL)

        rows = page.locator("#pi-table tbody tr")
        n_rows = rows.count()
        print(f"Found {n_rows} rows in the queue.")

        # Snapshot row data BEFORE acting on any of them -- we process the
        # queue in the order observed in the raw logs (top to bottom,
        # table order), and act on each row independently afterward via
        # its stable row id, since actions change the DOM as we go.
        row_data = []
        for i in range(n_rows):
            row = rows.nth(i)
            action_cell = row.locator("td.action-cell")
            item_id = action_cell.get_attribute("data-item-id")
            category = action_cell.get_attribute("data-category")
            amount_raw = action_cell.get_attribute("data-amount")
            amount = float(amount_raw) if amount_raw not in (None, "") else None
            row_data.append({"item_id": item_id, "category": category, "amount": amount})

        for row in row_data:
            item_id, category, amount = row["item_id"], row["category"], row["amount"]
            decision = decide(category, amount)
            entry = {
                "item_id": item_id, "category": category, "amount": amount,
                "outcome": decision.outcome.value, "reason": decision.reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            if decision.outcome == Outcome.HUMAN_REVIEW:
                print(f"  item {item_id}: HUMAN_REVIEW -- {decision.reason}")
                human_review.append(entry)
                log.append(entry)
                continue

            # AUTO_CONFIRM path: perform the exact observed UI sequence.
            try:
                action_cell = page.locator(f'td.action-cell[data-item-id="{item_id}"]')
                action_cell.click()
                page.locator("#pi-note").fill(decision.note_text)
                page.locator("#btn-pi-ok").click()
                page.wait_for_timeout(150)  # let the fetch()+DOM update settle

                row_locator = page.locator(f"#row-{item_id}")
                is_confirmed = "confirmed" in (row_locator.get_attribute("class") or "")
                status_text = action_cell.inner_text()

                if is_confirmed and "確認済み" in status_text:
                    print(f"  item {item_id}: AUTO_CONFIRM -- verified confirmed in UI")
                    entry["verified"] = True
                    auto_confirmed.append(entry)
                else:
                    print(f"  item {item_id}: AUTO_CONFIRM attempted but UI did NOT show confirmed -- treating as ERROR")
                    entry["verified"] = False
                    entry["outcome"] = "ERROR"
                    errors.append(entry)
            except Exception as exc:  # noqa: BLE001
                print(f"  item {item_id}: ERROR during automation -- {exc}")
                entry["outcome"] = "ERROR"
                entry["error"] = str(exc)
                errors.append(entry)

            log.append(entry)

        screenshot_path = OUT_DIR / "final_queue_state.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"\nScreenshot of final queue state: {screenshot_path.relative_to(Path.cwd()) if screenshot_path.is_absolute() else screenshot_path}")

        browser.close()

    with open(OUT_DIR / "automation_log.json", "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)
    with open(OUT_DIR / "human_review_queue.json", "w", encoding="utf-8") as f:
        json.dump(human_review, f, indent=2, ensure_ascii=False)

    print("\n=== SUMMARY ===")
    print(f"  total items:      {len(row_data)}")
    print(f"  auto-confirmed:   {len(auto_confirmed)} (verified in UI)")
    print(f"  human review:     {len(human_review)}")
    print(f"  errors:           {len(errors)}")
    print(f"\nFull log: {OUT_DIR / 'automation_log.json'}")
    print(f"Human review queue: {OUT_DIR / 'human_review_queue.json'}")
    if started_proc:
        print(f"\nMock app left running at {APP_URL} (pid {started_proc.pid}) -- browse to it, or Ctrl+C the process when done.")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
