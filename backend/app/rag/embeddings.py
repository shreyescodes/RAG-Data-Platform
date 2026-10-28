"""Text embedding backends."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

Matrix = npt.NDArray[np.float32]


class Embedder(Protocol):
    """Maps texts to L2-normalised float32 vectors of a fixed dimension."""

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def encode(self, texts: Sequence[str]) -> Matrix: ...


class SentenceTransformerEmbedder:
    """Local, in-process embeddings via `sentence-transformers`.

    The model is loaded on first use so that importing the application (for
    tests, migrations or the CLI) does not pull model weights.
    """

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: SentenceTransformer | None = None
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(self._model_name)
        return self._model

    @property
    def dimension(self) -> int:
        dim = self._get_model().get_sentence_embedding_dimension()
        if dim is None:  # pragma: no cover - only for exotic models
            raise RuntimeError(f"Model {self._model_name} has no fixed dimension")
        return int(dim)

    def encode(self, texts: Sequence[str]) -> Matrix:
        vectors = self._get_model().encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)
