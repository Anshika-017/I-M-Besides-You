"""Labeling: given a set of (already-cut) segments, assign each one a
label such that segments belonging to the same real business process get
the same label — across sessions, not just within one.

Approach: turn each segment into a feature vector (see `features.py`),
then group segments with unsupervised clustering. Clustering, not
supervised classification, because dataset_b's processes and applications
are different from dataset_a's (per the README) — there is no fixed set of
classes to train a classifier against that would transfer. The label
itself is arbitrary (the assignment says so explicitly); what matters is
that the same process consistently gets the same cluster.

`AgglomerativeClustering` with `distance_threshold` (not a fixed
`n_clusters`) is used deliberately: we don't know in advance how many
distinct processes exist in a new dataset, so a method that discovers the
number of clusters from a similarity threshold is the only kind that can
actually run on dataset_b without peeking at an answer we're not given.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from .features import SegmentFeatures


@dataclass
class LabelingConfig:
    """Defaults are the configuration chosen by
    `scripts/evaluate_labeling.py` after comparing 3 feature-set variants
    across a threshold sweep on dataset_a's oracle (ground-truth) segments,
    then refining the threshold grid once a plateau was found between 0.25
    and 0.32 (V-measure ~0.567-0.570 throughout, vs a sharp collapse to a
    single cluster by 0.7) -- 0.30 sits in the middle of that plateau
    rather than at either edge, since a value from the middle of a stable
    region is more likely to still work on a dataset with different
    vocabulary (dataset_b) than a value picked at the plateau's edge.
    See WORKLOG.md and reports/step1/labeling_results.json for the full
    comparison, including why this config's quality (V-measure ~0.57-0.62
    depending on split) is real but imperfect -- same-domain processes
    (e.g. several HR processes that share HR-portal vocabulary) are the
    main source of confusion, documented in the top-confused-pairs output.
    """
    distance_threshold: float = 0.30
    categorical_weight: float = 1.0
    text_weight: float = 1.0
    use_text: bool = True
    text_min_df: int = 2


def _categorical_dict(feats: SegmentFeatures) -> dict:
    d = {f"app::{k}": v for k, v in feats.app_counts.items()}
    d.update({f"route::{k}": v for k, v in feats.route_counts.items()})
    return d


def build_feature_matrix(segments: list[SegmentFeatures], config: LabelingConfig):
    """Returns a single combined, row-normalized sparse matrix (one row
    per segment). Categorical (app/route) and text blocks are each
    L2-normalized *separately* before combining, so neither block
    dominates purely because it happens to have more distinct feature
    columns or larger raw counts."""
    dict_vec = DictVectorizer(sparse=True)
    X_cat = dict_vec.fit_transform([_categorical_dict(f) for f in segments])
    X_cat = normalize(X_cat) * config.categorical_weight

    if config.use_text:
        tfidf = TfidfVectorizer(analyzer="char", ngram_range=(2, 3), min_df=config.text_min_df, max_features=3000)
        texts = [f.text or "" for f in segments]
        X_text = tfidf.fit_transform(texts) * config.text_weight
        X = sp.hstack([X_cat, X_text]).tocsr()
    else:
        X = X_cat.tocsr()

    # A handful of segments have no app/route/text data at all (very short
    # or context-sparse), leaving an all-zero row. Cosine distance is
    # undefined for a zero vector, so give every row a tiny constant
    # "bias" component -- negligible for any row that already has real
    # features (barely nudges its direction), but keeps all-zero rows
    # well-defined (they end up maximally similar to each other, which is
    # the sensible default when we have no evidence about a segment).
    bias = sp.csr_matrix(np.full((X.shape[0], 1), 1e-6))
    X = sp.hstack([X, bias]).tocsr()

    return X


def cluster_segments(X, config: LabelingConfig) -> np.ndarray:
    """Returns an integer cluster id per row of X. Uses cosine distance
    (feature magnitude shouldn't matter, direction/composition should) via
    average linkage, since 'ward' linkage (the sklearn default) requires
    Euclidean distance."""
    n = X.shape[0]
    if n <= 1:
        return np.zeros(n, dtype=int)
    model = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=config.distance_threshold,
        metric="cosine",
        linkage="average",
    )
    dense = X.toarray() if sp.issparse(X) else X
    return model.fit_predict(dense)
