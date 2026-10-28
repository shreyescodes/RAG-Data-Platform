"""FAISS-backed vector store with on-disk persistence."""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from app.rag.embeddings import Embedder

logger = logging.getLogger(__name__)

Document = dict[str, Any]


@dataclass(frozen=True, slots=True)
class SearchHit:
    document: Document
    score: float  # cosine similarity in [-1, 1]; higher is closer


class FAISSVectorStore:
    """Exact inner-product index over normalised embeddings (cosine similarity).

    The index is rebuilt wholesale rather than appended to, which keeps it
    consistent with its source (the schema) and makes re-indexing idempotent.
    Writes are atomic: files are written to a temporary path and renamed.
    """

    def __init__(self, embedder: Embedder, index_path: str | Path) -> None:
        self._embedder = embedder
        self._base_path = Path(index_path)
        self._lock = threading.RLock()
        self._index: Any | None = None
        self._documents: list[Document] = []
        self._load()

    # -- paths ---------------------------------------------------------------
    @property
    def _index_file(self) -> Path:
        return self._base_path.with_name(self._base_path.name + ".index")

    @property
    def _manifest_file(self) -> Path:
        return self._base_path.with_name(self._base_path.name + ".meta.json")

    # -- public API ------------------------------------------------------------
    @property
    def size(self) -> int:
        with self._lock:
            return len(self._documents)

    def rebuild(self, texts: Sequence[str], documents: Sequence[Document]) -> int:
        """Replace the index contents with `texts` and their `documents`."""
        if len(texts) != len(documents):
            raise ValueError("texts and documents must have the same length")
        if not texts:
            raise ValueError("cannot build an empty index")

        vectors = np.ascontiguousarray(self._embedder.encode(texts), dtype=np.float32)
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)

        with self._lock:
            self._index = index
            self._documents = list(documents)
            self._persist(index, self._documents)
        logger.info("Vector index rebuilt with %d documents", len(documents))
        return len(documents)

    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        with self._lock:
            index, documents = self._index, self._documents
        if index is None or not documents or not query.strip():
            return []

        vector = np.ascontiguousarray(self._embedder.encode([query]), dtype=np.float32)
        scores, ids = index.search(vector, min(k, len(documents)))
        return [
            SearchHit(document=documents[i], score=float(s))
            for i, s in zip(ids[0], scores[0], strict=True)
            if 0 <= i < len(documents)
        ]

    def stats(self) -> dict[str, Any]:
        return {
            "total_documents": self.size,
            "embedding_model": self._embedder.model_name,
        }

    def warm_up(self) -> None:
        """Load the embedding model now rather than on the first query."""
        self._embedder.encode(["warm-up"])

    # -- persistence -----------------------------------------------------------
    def _persist(self, index: Any, documents: list[Document]) -> None:
        self._base_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {"embedding_model": self._embedder.model_name, "documents": documents}
        tmp_index = self._index_file.with_suffix(".index.tmp")
        tmp_manifest = self._manifest_file.with_suffix(".json.tmp")
        faiss.write_index(index, str(tmp_index))
        tmp_manifest.write_text(json.dumps(manifest), encoding="utf-8")
        os.replace(tmp_index, self._index_file)
        os.replace(tmp_manifest, self._manifest_file)

    def _load(self) -> None:
        if not (self._index_file.exists() and self._manifest_file.exists()):
            logger.info("No vector index at %s; starting empty", self._index_file)
            return
        try:
            manifest = json.loads(self._manifest_file.read_text(encoding="utf-8"))
            index = faiss.read_index(str(self._index_file))
        except (OSError, ValueError, RuntimeError):
            logger.exception("Failed to load vector index; starting empty")
            return

        documents = manifest.get("documents", [])
        if manifest.get("embedding_model") != self._embedder.model_name:
            logger.warning(
                "Vector index was built with %r but %r is configured; re-index required",
                manifest.get("embedding_model"),
                self._embedder.model_name,
            )
            return
        if index.ntotal != len(documents):
            logger.warning("Vector index and manifest disagree; re-index required")
            return

        self._index = index
        self._documents = documents
        logger.info("Loaded vector index with %d documents", len(documents))
