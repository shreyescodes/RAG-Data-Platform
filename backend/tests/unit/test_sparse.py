import pytest

from app.rag.sparse import BM25Index, tokenize


def test_tokenize_splits_identifiers_and_keeps_the_whole() -> None:
    assert tokenize("ma_50 trend") == ["ma_50", "ma", "50", "trend"]


def test_tokenize_drops_stopwords_and_folds_plurals() -> None:
    assert tokenize("What are the churn rates of companies?") == ["churn", "rate", "company"]


@pytest.mark.parametrize("word", ["status", "analysis", "class"])
def test_tokenize_keeps_words_that_only_look_plural(word: str) -> None:
    assert tokenize(word) == [word]


def test_exact_identifier_ranks_first() -> None:
    index = BM25Index(
        [
            "Column market_data.close_price: closing price",
            "Column market_data.ma_50: 50-day moving average of close",
            "Column market_data.ma_200: 200-day moving average of close",
        ]
    )
    hits = index.search("show ma_50 for NVDA")
    assert hits[0].index == 1
    assert all(h.score > 0 for h in hits)


def test_rare_terms_outweigh_common_ones() -> None:
    index = BM25Index(["revenue total", "revenue eps", "revenue margin", "revenue growth"])
    scores = index.scores("revenue eps")
    assert scores.index(max(scores)) == 1


def test_no_matching_terms_returns_nothing() -> None:
    index = BM25Index(["alpha beta", "gamma"])
    assert index.search("delta") == []
    assert index.scores("") == [0.0, 0.0]


def test_empty_corpus() -> None:
    index = BM25Index([])
    assert index.size == 0
    assert index.search("anything") == []


def test_search_respects_k_and_breaks_ties_by_position() -> None:
    index = BM25Index(["churn", "churn", "churn"])
    assert [h.index for h in index.search("churn", k=2)] == [0, 1]
