"""Pure, bounded clustering helpers."""

from __future__ import annotations

import numpy as np
from sklearn.cluster import HDBSCAN
from sklearn.decomposition import PCA
from sklearn.preprocessing import normalize

# How many nearest bucket members a thread is compared against.
NEIGHBOR_K = 3


def _unit_matrix(vectors) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != 512 or not np.isfinite(matrix).all():
        raise ValueError("invalid embedding matrix")
    return normalize(matrix, norm="l2")


def _top_k_mean(similarities: np.ndarray, k: int) -> np.ndarray:
    k = max(1, min(k, similarities.shape[1]))
    return -np.partition(-similarities, k - 1, axis=1)[:, :k].mean(axis=1)


def neighbor_scores(
    queries: list[list[float]], members: list[list[float]], *, k: int = NEIGHBOR_K
) -> list[float]:
    """Mean cosine similarity of each query to its ``k`` nearest members.

    Several nearest members, rather than one centroid, keep a broad or merged bucket reachable
    from each of its topics, while a single stray member cannot pull unrelated mail in alone.
    """
    if not queries or not members:
        return [0.0] * len(queries)
    return _top_k_mean(_unit_matrix(queries) @ _unit_matrix(members).T, k).tolist()


def fit_scores(members: list[list[float]], *, k: int = NEIGHBOR_K) -> list[float]:
    """Score each member against the rest of its group (leave-one-out ``neighbor_scores``)."""
    if len(members) < 2:
        return [0.0] * len(members)
    matrix = _unit_matrix(members)
    similarities = matrix @ matrix.T
    np.fill_diagonal(similarities, -np.inf)
    return _top_k_mean(similarities, min(k, len(members) - 1)).tolist()


def centroid_similarity(left: list[list[float]], right: list[list[float]]) -> float:
    """Cosine similarity between two groups' mean directions."""
    return cosine_similarity(
        _unit_matrix(left).mean(axis=0).tolist(), _unit_matrix(right).mean(axis=0).tolist()
    )


def discover_clusters(vectors: list[list[float]], *, min_cluster_size: int = 8) -> list[int]:
    if len(vectors) < min_cluster_size * 2:
        return [-1] * len(vectors)
    matrix = _unit_matrix(vectors)
    components = min(32, matrix.shape[0] - 1, matrix.shape[1])
    reduced = PCA(n_components=components, svd_solver="full").fit_transform(matrix)
    return (
        HDBSCAN(min_cluster_size=min_cluster_size, min_samples=3, copy=False)
        .fit_predict(reduced)
        .tolist()
    )


def representative_indices(vectors: list[list[float]], *, limit: int = 5) -> list[int]:
    """Select central examples plus one deterministic diversity example."""
    if not vectors or limit < 1:
        return []
    matrix = _unit_matrix(vectors)
    center = matrix.mean(axis=0)
    center_norm = np.linalg.norm(center)
    centrality = matrix @ (center / center_norm) if center_norm else np.zeros(len(matrix))
    central = sorted(range(len(matrix)), key=lambda index: (-centrality[index], index))
    selected = central[: min(limit, len(central))]
    if len(matrix) > 1 and limit > 1:
        # Reserve the final slot for the member least similar to the most central exemplar.
        selected = central[: min(limit - 1, len(central) - 1)]
        remaining = [index for index in range(len(matrix)) if index not in selected]
        diverse = min(
            remaining,
            key=lambda index: (float(matrix[index] @ matrix[central[0]]), index),
        )
        selected.append(diverse)
    return selected[:limit]


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
