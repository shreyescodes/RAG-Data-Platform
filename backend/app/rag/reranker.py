"""Cross-encoder reranking.

A bi-encoder (the embedder) scores query and document independently; a
cross-encoder reads them together, which is slower but markedly more precise.
It is therefore only applied to the short list that fused retrieval returns.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder


def sigmoid(x: float) -> float:
    # Split by sign so large magnitudes cannot overflow math.exp.
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


class Reranker(Protocol):
    """Scores (query, document) pairs; higher is more relevant."""

    @property
    def model_name(self) -> str: ...

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        """Relevance in [0, 1] for each document, in input order."""
        ...


class CrossEncoderReranker:
    """Local `sentence-transformers` cross-encoder, loaded on first use.

    The default `cross-encoder/ms-marco-MiniLM-L6-v2` is ~90 MB and scores a
    20-document shortlist in tens of milliseconds on a laptop CPU.
    """

    def __init__(self, model_name: str, *, max_length: int = 256) -> None:
        self._model_name = model_name
        self._max_length = max_length
        self._model: CrossEncoder | None = None
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    def _get_model(self) -> CrossEncoder:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import CrossEncoder

                    self._model = CrossEncoder(self._model_name, max_length=self._max_length)
        return self._model

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        import torch

        # Ask for raw logits and squash them here, so the score is a probability
        # whatever activation the model's saved config declares.
        logits = self._get_model().predict(
            [(query, doc) for doc in documents],
            activation_fn=torch.nn.Identity(),
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [sigmoid(float(x)) for x in logits]

    def warm_up(self) -> None:
        self.score("warm-up", ["warm-up"])
