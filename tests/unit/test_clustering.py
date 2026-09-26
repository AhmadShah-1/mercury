import pytest

from mercury.buckets.clustering import conservative_choice, cosine_similarity, discover_clusters


def test_sparse_mailbox_remains_unsorted():
    assert discover_clusters([[0.0] * 512 for _ in range(5)]) == [-1] * 5


def test_similarity_rejects_mixed_vector_dimensions():
    with pytest.raises(ValueError):
        cosine_similarity([1.0, 0.0], [1.0])


def test_assignment_requires_absolute_score_and_margin():
    assert conservative_choice([("a", 0.84), ("b", 0.70)], minimum=0.85, margin=0.08) is None
    assert conservative_choice([("a", 0.90), ("b", 0.86)], minimum=0.85, margin=0.08) is None
    assert conservative_choice([("a", 0.94), ("b", 0.80)], minimum=0.85, margin=0.08) == "a"
