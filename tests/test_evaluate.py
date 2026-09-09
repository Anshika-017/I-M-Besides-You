"""Unit tests for the boundary-matching evaluator, against small synthetic
boundary lists (no dataset needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.evaluate import match_boundaries, precision_recall_f1, _dedupe  # noqa: E402


def test_perfect_match():
    m = match_boundaries(true_ts=[1000, 5000, 9000], pred_ts=[1000, 5000, 9000], tolerance_ms=500)
    assert (m.tp, m.fp, m.fn) == (3, 0, 0)
    p, r, f1 = precision_recall_f1(m)
    assert p == r == f1 == 1.0


def test_one_missed_and_one_spurious():
    m = match_boundaries(true_ts=[1000, 5000], pred_ts=[1000, 9000], tolerance_ms=500)
    assert m.tp == 1
    assert m.fn == 1  # 5000 was never predicted
    assert m.fp == 1  # 9000 doesn't match anything


def test_tolerance_respected():
    m = match_boundaries(true_ts=[1000], pred_ts=[1600], tolerance_ms=500)
    assert (m.tp, m.fp, m.fn) == (0, 1, 1)
    m2 = match_boundaries(true_ts=[1000], pred_ts=[1600], tolerance_ms=1000)
    assert (m2.tp, m2.fp, m2.fn) == (1, 0, 0)


def test_matching_is_one_to_one_not_many_to_many():
    # two predicted boundaries both close to the same single true boundary:
    # only one may match it, the other must count as a false positive.
    m = match_boundaries(true_ts=[1000], pred_ts=[900, 1100], tolerance_ms=500)
    assert m.tp == 1
    assert m.fp == 1
    assert m.fn == 0


def test_dedupe_collapses_near_duplicates():
    assert _dedupe([1000, 1200, 5000, 5100, 9000], eps_ms=500) == [1000, 5000, 9000]
