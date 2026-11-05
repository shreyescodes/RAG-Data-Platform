from typing import Any

import numpy as np
import pytest

from app.rag.reranker import CrossEncoderReranker, sigmoid


@pytest.mark.parametrize(("x", "expected"), [(0.0, 0.5), (1000.0, 1.0), (-1000.0, 0.0)])
def test_sigmoid_is_stable_at_extremes(x: float, expected: float) -> None:
    assert sigmoid(x) == pytest.approx(expected)


class _FakeCrossEncoder:
    def __init__(self) -> None:
        self.pairs: list[tuple[str, str]] = []
        self.kwargs: dict[str, Any] = {}

    def predict(self, pairs: list[tuple[str, str]], **kwargs: Any) -> Any:
        self.pairs = pairs
        self.kwargs = kwargs
        return np.array([2.0, -2.0], dtype=np.float32)


def test_scores_are_probabilities_of_raw_logits() -> None:
    reranker = CrossEncoderReranker("test-model")
    fake = _FakeCrossEncoder()
    reranker._model = fake  # type: ignore[assignment]

    scores = reranker.score("q", ["relevant", "irrelevant"])

    assert scores == pytest.approx([sigmoid(2.0), sigmoid(-2.0)])
    assert fake.pairs == [("q", "relevant"), ("q", "irrelevant")]
    # Raw logits are requested so the model config's activation cannot double-apply.
    assert type(fake.kwargs["activation_fn"]).__name__ == "Identity"
    assert reranker.model_name == "test-model"


def test_no_documents_does_not_load_the_model() -> None:
    reranker = CrossEncoderReranker("never-loaded")
    assert reranker.score("q", []) == []
    assert reranker._model is None


def test_warm_up_scores_once() -> None:
    reranker = CrossEncoderReranker("test-model")
    fake = _FakeCrossEncoder()
    fake.predict = lambda pairs, **_: np.array([0.0])  # type: ignore[method-assign]
    reranker._model = fake  # type: ignore[assignment]
    reranker.warm_up()
