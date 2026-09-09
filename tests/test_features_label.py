"""Unit tests for feature extraction and clustering, against small
synthetic data (no dataset needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.features import _coarse_route, extract_segment_features  # noqa: E402
from procmine.label import LabelingConfig, build_feature_matrix, cluster_segments  # noqa: E402


def test_coarse_route_collapses_ids():
    a = _coarse_route("http://127.0.0.1:5123/#/cases/482?tab=info")
    b = _coarse_route("http://127.0.0.1:5123/#/cases/119")
    assert a == b == "#/cases/<id>"


def test_coarse_route_keeps_distinct_pages_distinct():
    a = _coarse_route("http://x/#/payroll-items")
    b = _coarse_route("http://x/#/leave-applications")
    assert a != b


def test_coarse_route_handles_missing_url():
    assert _coarse_route("") is None
    assert _coarse_route(None) is None


def test_extract_segment_features_collects_apps_and_text():
    events = [
        {"event_type": "app_switch", "timestamp_ms": 0,
         "context": {"active_app": {"app_name": "Google Chrome"},
                     "active_browser_tab": {"url": "http://x/#/invoices/55"},
                     "extracted_text": {"text": "invoice approval"}}},
        {"event_type": "keystroke", "timestamp_ms": 100,
         "context": {"active_app": {"app_name": "Google Chrome"}}},
    ]
    feats = extract_segment_features("ses_1", 0, 100, events)
    assert feats.app_counts["Google Chrome"] == 2
    assert feats.route_counts["#/invoices/<id>"] == 1
    assert "invoice approval" in feats.text


def test_build_feature_matrix_handles_empty_segment_without_crashing():
    from procmine.features import SegmentFeatures
    empty = SegmentFeatures(session_id="s", start_ms=0, end_ms=1)
    normal = SegmentFeatures(session_id="s", start_ms=1, end_ms=2)
    normal.app_counts["chrome"] = 3
    cfg = LabelingConfig(use_text=False)
    X = build_feature_matrix([empty, normal], cfg)
    assert X.shape[0] == 2  # no crash on the all-zero row


def test_cluster_segments_single_row():
    cfg = LabelingConfig()
    import scipy.sparse as sp
    X = sp.csr_matrix([[1.0, 0.0]])
    labels = cluster_segments(X, cfg)
    assert len(labels) == 1
