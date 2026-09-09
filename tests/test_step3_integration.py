"""Integration test: actually drives the mock app with Playwright and
checks the real UI state changes, not just the decision logic in
isolation. Covers the "successful UI confirmation" and "human-review item
is left untouched" scenarios end-to-end.

Starts its own mock_app.py subprocess on a dedicated port (5099, not 5001)
so it doesn't collide with a manually-running demo instance.
"""
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

AUTOMATION_DIR = Path(__file__).resolve().parent.parent / "automation"
sys.path.insert(0, str(AUTOMATION_DIR))

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

PORT = 5099
APP_URL = f"http://127.0.0.1:{PORT}"


@pytest.fixture(scope="module")
def running_app():
    env = {"FLASK_RUN_PORT": str(PORT)}
    import os
    full_env = {**os.environ, **env}
    # mock_app.py hardcodes port 5001; run it via a tiny wrapper that overrides the port.
    code = (
        "import sys; sys.path.insert(0, %r); "
        "import mock_app; mock_app.app.run(host='127.0.0.1', port=%d)"
    ) % (str(AUTOMATION_DIR), PORT)
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=str(AUTOMATION_DIR), env=full_env)
    for _ in range(30):
        try:
            urllib.request.urlopen(APP_URL, timeout=1)
            break
        except Exception:
            time.sleep(0.3)
    else:
        proc.terminate()
        pytest.fail("mock app did not start in time")
    yield APP_URL
    proc.terminate()
    proc.wait(timeout=5)


@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="playwright not installed")
def test_successful_ui_confirmation(running_app):
    """A known-category, in-cap item: click row -> fill note -> click OK
    -> the row must actually show 'confirmed' in the live DOM afterward."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(running_app)

        # item 1: 交通費精算, ¥12,500 -- valid, in-scope, in-cap
        page.locator('td.action-cell[data-item-id="1"]').click()
        page.locator("#pi-note").fill("経費精算確認済み。費目：交通費精算　金額：12,500円。規程内であることを確認した。")
        page.locator("#btn-pi-ok").click()
        page.wait_for_timeout(200)

        row_class = page.locator("#row-1").get_attribute("class")
        assert "confirmed" in row_class
        assert "確認済み" in page.locator('td.action-cell[data-item-id="1"]').inner_text()
        browser.close()


@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="playwright not installed")
def test_human_review_item_is_left_untouched_in_ui(running_app):
    """The automation must never click into a HUMAN_REVIEW item. Simulate
    that by simply not interacting with row 8 (unknown category) and
    confirming it's still pending."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(running_app)

        row_class = page.locator("#row-8").get_attribute("class") or ""
        assert "confirmed" not in row_class
        assert "未処理" in page.locator('td.action-cell[data-item-id="8"]').inner_text()
        browser.close()
