import pytest

from app.rag.fusion import max_rrf_score, reciprocal_rank_fusion


def test_documents_ranked_well_by_both_lists_win() -> None:
    fused = reciprocal_rank_fusion({"dense": ["a", "b", "c"], "sparse": ["b", "d", "a"]})
    assert [key for key, _ in fused] == ["b", "a", "d", "c"]


def test_scores_follow_the_formula() -> None:
    fused = dict(reciprocal_rank_fusion({"x": ["a", "b"], "y": ["a"]}, k=10))
    assert fused["a"] == pytest.approx(1 / 11 + 1 / 11)
    assert fused["b"] == pytest.approx(1 / 12)
    assert fused["a"] == pytest.approx(max_rrf_score(2, k=10))


def test_ties_keep_first_seen_order() -> None:
    fused = reciprocal_rank_fusion({"x": ["a", "b"], "y": ["b", "a"]})
    assert [key for key, _ in fused] == ["a", "b"]


def test_duplicates_within_a_ranking_count_once() -> None:
    fused = dict(reciprocal_rank_fusion({"x": ["a", "a", "b"]}, k=1))
    assert fused == {"a": pytest.approx(1 / 2), "b": pytest.approx(1 / 3)}


def test_empty_rankings() -> None:
    assert reciprocal_rank_fusion({"x": [], "y": []}) == []


def test_k_must_be_positive() -> None:
    with pytest.raises(ValueError, match="k must be"):
        reciprocal_rank_fusion({"x": ["a"]}, k=0)
