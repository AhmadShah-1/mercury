"""Pure, bounded clustering helpers."""

from __future__ import annotations

import numpy as np
from sklearn.cluster import HDBSCAN
from sklearn.decomposition import PCA
from sklearn.preprocessing import normalize


def discover_clusters(vectors: list[list[float]], *, min_cluster_size: int = 8) -> list[int]:
    if len(vectors) < min_cluster_size * 2:
        return [-1] * len(vectors)
    matrix = np.asarray(vectors, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != 512 or not np.isfinite(matrix).all():
        raise ValueError("invalid embedding matrix")
    matrix = normalize(matrix, norm="l2")
    components = min(32, matrix.shape[0] - 1, matrix.shape[1])
    reduced = PCA(n_components=components, svd_solver="full").fit_transform(matrix)
    return HDBSCAN(min_cluster_size=min_cluster_size, min_samples=3).fit_predict(reduced).tolist()


def cosine_similarity(left: list[float], right: list[float]) -> float:
    a, b = np.asarray(left), np.asarray(right)
    if a.shape != b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("incompatible embeddings")
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator else 0.0


def conservative_choice(
    scores: list[tuple[str, float]], *, minimum: float, margin: float
) -> str | None:
    """Return the best bucket only when both measured thresholds are satisfied."""
    if not scores:
        return None
    ranked = sorted(scores, key=lambda item: (-item[1], item[0]))
    best_id, best_score = ranked[0]
    next_score = ranked[1][1] if len(ranked) > 1 else -1.0
    if best_score < minimum or best_score - next_score < margin:
        return None
    return best_id
