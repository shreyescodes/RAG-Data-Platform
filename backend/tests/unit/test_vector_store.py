from pathlib import Path

import pytest

from app.rag.vector_store import FAISSVectorStore
from tests.fakes import HashingEmbedder

TEXTS = ["quarterly revenue and net income", "daily stock prices", "monthly churn rate"]
DOCS = [{"id": i} for i in range(len(TEXTS))]


def test_search_ranks_by_similarity(vector_store: FAISSVectorStore) -> None:
    vector_store.rebuild(TEXTS, DOCS)
    hits = vector_store.search("stock prices", k=3)
    assert hits[0].document == {"id": 1}
    assert hits[0].score > hits[1].score


def test_rebuild_replaces_instead_of_appending(vector_store: FAISSVectorStore) -> None:
    vector_store.rebuild(TEXTS, DOCS)
    vector_store.rebuild(TEXTS[:1], DOCS[:1])
    assert vector_store.size == 1


def test_persists_and_reloads(tmp_path: Path, embedder: HashingEmbedder) -> None:
    FAISSVectorStore(embedder, tmp_path / "idx").rebuild(TEXTS, DOCS)
    reloaded = FAISSVectorStore(embedder, tmp_path / "idx")
    assert reloaded.size == len(TEXTS)
    assert reloaded.search("churn", k=1)[0].document == {"id": 2}


def test_ignores_index_built_with_another_model(tmp_path: Path, embedder: HashingEmbedder) -> None:
    FAISSVectorStore(embedder, tmp_path / "idx").rebuild(TEXTS, DOCS)

    other = HashingEmbedder()
    other.model_name = "different-model"
    assert FAISSVectorStore(other, tmp_path / "idx").size == 0


def test_corrupt_index_starts_empty(tmp_path: Path, embedder: HashingEmbedder) -> None:
    (tmp_path / "idx.index").write_bytes(b"not a faiss index")
    (tmp_path / "idx.meta.json").write_text("{}")
    assert FAISSVectorStore(embedder, tmp_path / "idx").size == 0


def test_empty_store_and_blank_query(vector_store: FAISSVectorStore) -> None:
    assert vector_store.search("anything") == []
    vector_store.rebuild(TEXTS, DOCS)
    assert vector_store.search("   ") == []


def test_rejects_invalid_rebuild(vector_store: FAISSVectorStore) -> None:
    with pytest.raises(ValueError, match="same length"):
        vector_store.rebuild(TEXTS, DOCS[:1])
    with pytest.raises(ValueError, match="empty"):
        vector_store.rebuild([], [])


def test_stats(vector_store: FAISSVectorStore) -> None:
    vector_store.rebuild(TEXTS, DOCS)
    stats = vector_store.stats()
    assert stats["total_documents"] == 3
    assert stats["embedding_model"] == HashingEmbedder.model_name


def test_warm_up_leaves_index_unchanged(vector_store: FAISSVectorStore) -> None:
    vector_store.warm_up()
    assert vector_store.size == 0
