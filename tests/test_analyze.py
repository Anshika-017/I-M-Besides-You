"""Unit tests for Step 2 analysis logic, against small synthetic data (no
dataset needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np  # noqa: E402

from procmine.analyze import (  # noqa: E402
    machine_from_session_id, iso_to_dt, describe, cluster_centroids,
)


def test_machine_from_session_id():
    assert machine_from_session_id("ses_20260701-164424-CHAITANYA0BCF") == "CHAITANYA0BCF"
    assert machine_from_session_id("ses_20260701-183232-LAPTOP-76QMG9DE") == "LAPTOP-76QMG9DE"


def test_iso_to_dt_roundtrip_duration():
    a = iso_to_dt("2026-07-01T18:32:32Z")
    b = iso_to_dt("2026-07-01T18:35:41Z")
    assert (b - a).total_seconds() == 189


def test_describe_basic_stats():
    d = describe([10, 20, 30, 40, 50])
    assert d["n"] == 5
    assert d["min"] == 10
    assert d["max"] == 50
    assert d["median"] == 30
    assert d["mean"] == 30


def test_describe_empty():
    assert describe([]) == {}


def test_cluster_centroids_does_not_chain_everything_together():
    # Three tight, well-separated clusters of centroids (as if from three
    # genuinely different processes) plus one clear outlier. A sane
    # clustering should recover ~4 groups, not collapse into 1 (the
    # single-linkage/union-find failure mode documented in WORKLOG.md).
    centroids = {
        "a1": np.array([1.0, 0.0, 0.0, 0.0]),
        "a2": np.array([0.95, 0.05, 0.0, 0.0]),
        "b1": np.array([0.0, 1.0, 0.0, 0.0]),
        "b2": np.array([0.0, 0.95, 0.05, 0.0]),
        "c1": np.array([0.0, 0.0, 1.0, 0.0]),
        "c2": np.array([0.0, 0.0, 0.95, 0.05]),
        "outlier": np.array([0.0, 0.0, 0.0, 1.0]),
    }
    groups = cluster_centroids(centroids, distance_threshold=0.2)
    sizes = sorted(len(m) for m in groups.values())
    assert len(groups) == 4, f"expected 4 groups (a,b,c,outlier), got {len(groups)}: {groups}"
    assert sizes == [1, 2, 2, 2]


def test_cluster_centroids_single_label():
    groups = cluster_centroids({"only": np.array([1.0, 0.0])}, distance_threshold=0.3)
    assert groups == {"group_000": ["only"]}
