"""Unit tests for automation/decision.py -- the one piece of business
logic the Step 3 prototype automates. No Playwright/browser needed.

Covers the required scenarios: a valid in-scope expense, the boundary/
threshold case the observed regulation actually supports, an unknown
category, invalid/missing data, and confirms the human-review fallback
never produces a note (i.e. never guesses what to say)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "automation"))

from decision import decide, Outcome, ENTERTAINMENT_APPROVAL_CAP_YEN, KNOWN_CATEGORIES  # noqa: E402


def test_valid_in_scope_expense_auto_confirms():
    d = decide("交通費精算", 12_500)
    assert d.outcome == Outcome.AUTO_CONFIRM
    assert d.note_text == "経費精算確認済み。費目：交通費精算　金額：12,500円。規程内であることを確認した。"


def test_valid_in_scope_expense_all_five_known_categories():
    for cat in KNOWN_CATEGORIES:
        if cat == "接待交際費":
            continue  # has its own cap, tested separately below
        d = decide(cat, 20_000)
        assert d.outcome == Outcome.AUTO_CONFIRM, f"{cat} should auto-confirm at a modest amount"


def test_boundary_threshold_case_entertainment_expense():
    # Just under the confirmed ¥50,000 department-head cap -> auto-confirm
    below = decide("接待交際費", ENTERTAINMENT_APPROVAL_CAP_YEN - 1)
    assert below.outcome == Outcome.AUTO_CONFIRM

    # Exactly at the cap -> human review (the regulation says "5万円以上"
    # i.e. >= 50,000 requires executive approval)
    at_cap = decide("接待交際費", ENTERTAINMENT_APPROVAL_CAP_YEN)
    assert at_cap.outcome == Outcome.HUMAN_REVIEW
    assert "50,000" in at_cap.reason or "cap" in at_cap.reason

    # Above the cap -> human review
    above = decide("接待交際費", ENTERTAINMENT_APPROVAL_CAP_YEN + 1)
    assert above.outcome == Outcome.HUMAN_REVIEW


def test_unknown_unconfirmed_category_routes_to_human():
    d = decide("福利厚生費", 15_000)  # a plausible category never observed in this queue
    assert d.outcome == Outcome.HUMAN_REVIEW
    assert d.note_text is None
    assert "not one of the" in d.reason


def test_missing_amount_routes_to_human():
    d = decide("交通費精算", None)
    assert d.outcome == Outcome.HUMAN_REVIEW
    assert d.note_text is None


def test_non_numeric_amount_routes_to_human():
    d = decide("交通費精算", "十二万円")  # a string, not a number
    assert d.outcome == Outcome.HUMAN_REVIEW


def test_negative_or_zero_amount_routes_to_human():
    assert decide("交通費精算", 0).outcome == Outcome.HUMAN_REVIEW
    assert decide("交通費精算", -500).outcome == Outcome.HUMAN_REVIEW


def test_missing_category_routes_to_human():
    assert decide(None, 10_000).outcome == Outcome.HUMAN_REVIEW
    assert decide("", 10_000).outcome == Outcome.HUMAN_REVIEW
    assert decide("   ", 10_000).outcome == Outcome.HUMAN_REVIEW


def test_human_review_never_produces_a_note():
    # The bot must never compose a note for something it isn't confident
    # about -- human-review outcomes should carry no note_text at all.
    for category, amount in [(None, 100), ("unknown_cat", 100), ("交通費精算", None), ("接待交際費", 999_999)]:
        d = decide(category, amount)
        if d.outcome == Outcome.HUMAN_REVIEW:
            assert d.note_text is None
