import pytest

from mercury.buckets.clustering import (
    centroid_similarity,
    conservative_choice,
    cosine_similarity,
    discover_clusters,
    fit_scores,
    neighbor_scores,
    representative_indices,
)


def test_sparse_mailbox_remains_unsorted():
    assert discover_clusters([[0.0] * 512 for _ in range(5)]) == [-1] * 5


def test_similarity_rejects_mixed_vector_dimensions():
    with pytest.raises(ValueError):
        cosine_similarity([1.0, 0.0], [1.0])


def test_assignment_requires_absolute_score_and_margin():
    assert conservative_choice([("a", 0.84), ("b", 0.70)], minimum=0.85, margin=0.08) is None
    assert conservative_choice([("a", 0.90), ("b", 0.86)], minimum=0.85, margin=0.08) is None
    assert conservative_choice([("a", 0.94), ("b", 0.80)], minimum=0.85, margin=0.08) == "a"


def test_representatives_are_bounded_deterministic_and_include_diversity():
    vectors = []
    for index in range(8):
        vector = [0.0] * 512
        vector[index] = 1.0
        vectors.append(vector)
    first = representative_indices(vectors)
    assert first == representative_indices(vectors)
    assert len(first) == 5
    assert len(set(first)) == 5


def _axis(index: int, weight: float = 1.0) -> list[float]:
    vector = [0.0] * 512
    vector[index] = weight
    return vector


def test_neighbor_scores_use_the_nearest_members_not_one_centroid():
    # A bucket spanning two topics (e.g. after a merge): mail near either topic scores high,
    # although it is far from the bucket's average direction.
    members = [_axis(0), _axis(0), _axis(0), _axis(1), _axis(1), _axis(1)]
    near_first, near_second, unrelated = neighbor_scores(
        [_axis(0), _axis(1), _axis(2)], members, k=3
    )
    assert near_first == pytest.approx(1.0)
    assert near_second == pytest.approx(1.0)
    assert unrelated == pytest.approx(0.0)
    assert centroid_similarity([_axis(0)], members) == pytest.approx(2**-0.5)


def test_one_stray_member_cannot_pull_unrelated_mail_in_alone():
    members = [_axis(0), _axis(0), _axis(0), _axis(2)]
    [score] = neighbor_scores([_axis(2)], members, k=3)
    assert score == pytest.approx(1 / 3)


def test_fit_scores_exclude_the_member_itself():
    scores = fit_scores([_axis(0), _axis(0), _axis(0), _axis(1)])
    assert scores[:3] == pytest.approx([2 / 3] * 3)
    assert scores[3] == pytest.approx(0.0)
    assert fit_scores([_axis(0)]) == [0.0]
