import numpy as np

from app.rag.schema_indexer import SchemaIndexer, build_schema_catalog
from app.rag.vector_store import FAISSVectorStore
from tests.fakes import OverlapReranker


def test_catalog_excludes_non_queryable_tables() -> None:
    catalog = build_schema_catalog()
    assert "query_logs" not in catalog
    assert {"companies", "financial_statements", "market_data"} <= catalog.keys()


def test_ddl_includes_types_keys_and_descriptions() -> None:
    ddl = build_schema_catalog()["financial_statements"].to_ddl()
    assert ddl.startswith("-- Quarterly or annual financial statements")
    assert "CREATE TABLE financial_statements (" in ddl
    assert "id INTEGER PRIMARY KEY" in ddl
    assert "company_id INTEGER NOT NULL REFERENCES companies.id" in ddl
    assert "eps FLOAT  -- Earnings per share." in ddl


def test_index_is_idempotent(indexer: SchemaIndexer) -> None:
    first = indexer.index()
    second = indexer.index()
    assert first == second


def test_finds_tables_by_meaning(indexer: SchemaIndexer) -> None:
    names = [t.name for t in indexer.find_relevant_tables("monthly churn rate and ARR", 1)]
    assert names[0] == "performance_metrics"


def test_expands_foreign_keys_transitively(indexer: SchemaIndexer) -> None:
    names = [t.name for t in indexer.find_relevant_tables("ARR churn rate customers", 1)]
    # performance_metrics -> portfolio_companies -> companies
    assert names == ["performance_metrics", "portfolio_companies", "companies"]


def test_returns_nothing_for_empty_index(vector_store) -> None:
    assert SchemaIndexer(vector_store).find_relevant_tables("revenue", 3) == []


def test_declared_relations_are_expanded(indexer: SchemaIndexer) -> None:
    # market_data has no foreign key but declares companies as related (ticker join).
    assert indexer.catalog["market_data"].referenced_tables == {"companies"}
    names = [t.name for t in indexer.find_relevant_tables("daily stock prices close volume", 1)]
    assert names == ["market_data", "companies"]


# --- Hybrid retrieval ------------------------------------------------------------


class ConstantEmbedder:
    """Uninformative dense retrieval: every text gets the same vector."""

    model_name = "test-constant-embedder"
    dimension = 8

    def encode(self, texts):
        return np.full((len(texts), self.dimension), 1 / np.sqrt(self.dimension), np.float32)


def test_modes() -> None:
    store = FAISSVectorStore(ConstantEmbedder(), "unused")
    assert SchemaIndexer(store).mode == "dense"
    assert SchemaIndexer(store, hybrid=True).mode == "hybrid"
    assert SchemaIndexer(store, reranker=OverlapReranker()).mode == "dense+rerank"
    assert SchemaIndexer(store, hybrid=True, reranker=OverlapReranker()).mode == "hybrid+rerank"


def test_bm25_recovers_identifiers_dense_retrieval_misses(tmp_path) -> None:
    store = FAISSVectorStore(ConstantEmbedder(), tmp_path / "index")
    dense = SchemaIndexer(store)
    dense.index()
    hybrid = SchemaIndexer(store, hybrid=True)

    question = "runway_months and burn_rate"
    assert "performance_metrics" not in dense.search(question, 2).table_names
    result = hybrid.search(question, 2)
    assert "performance_metrics" in result.table_names
    top_sparse = [c for c in result.candidates if c.sparse_rank in (1, 2, 3)]
    assert {c.table for c in top_sparse} == {"performance_metrics"}
    runway = next(c for c in result.candidates if c.document.endswith("runway_months"))
    assert runway.dense_rank is None  # beyond the dense search depth
    assert runway.fused_score is not None


def test_reranker_decides_the_final_order(dense_indexer: SchemaIndexer) -> None:
    class PrefersVolume:
        model_name = "prefers-volume"

        def score(self, query, documents):
            return [0.99 if "market_data.volume" in d else 0.01 for d in documents]

    dense_indexer.hybrid = True
    dense_indexer.reranker = PrefersVolume()
    result = dense_indexer.search("trading volume and revenue", 1)

    assert result.candidates[0].document == "market_data.volume"
    assert result.candidates[0].rerank_score == 0.99
    assert result.table_names == ["market_data", "companies"]
    assert result.confidence == 0.99


def test_trace_detail_reports_every_score(indexer: SchemaIndexer) -> None:
    detail = indexer.search("monthly churn rate and ARR", 1).trace_detail()

    assert detail["mode"] == "hybrid+rerank"
    assert detail["tables"] == ["performance_metrics", "portfolio_companies", "companies"]
    first = detail["candidates"][0]
    assert set(first) >= {
        "document",
        "dense_score",
        "dense_rank",
        "sparse_score",
        "sparse_rank",
        "fused_score",
        "fused_rank",
        "rerank_score",
        "final_rank",
    }
    assert first["final_rank"] == 1
    scores = detail["table_scores"]
    assert [s["via"] for s in scores] == ["retrieved", "foreign_key", "foreign_key"]
    assert "churn_rate" in scores[0]["matched_columns"]
    assert set(detail["timings_ms"]) == {"dense", "sparse", "rerank"}


def test_reranker_failure_degrades_to_fused_ranking(
    indexer: SchemaIndexer, reranker: OverlapReranker
) -> None:
    reranker.error = OSError("model weights not found")
    result = indexer.search("monthly churn rate and ARR", 1)

    assert result.table_names[0] == "performance_metrics"
    assert result.degraded == "reranker unavailable (OSError)"
    assert result.trace_detail()["degraded"] == result.degraded
    assert all(c.rerank_score is None for c in result.candidates)
    assert result.confidence is None


def test_sparse_index_follows_reindexing(indexer: SchemaIndexer) -> None:
    indexer.search("revenue", 1)
    first = indexer._sparse
    indexer.index()
    indexer.search("revenue", 1)
    assert indexer._sparse is not first


def test_empty_index_returns_empty_result(vector_store) -> None:
    result = SchemaIndexer(vector_store, hybrid=True).search("revenue", 3)
    assert result.tables == []
    assert result.confidence is None


def test_identifies_rows_uses_keys_and_declared_natural_keys() -> None:
    catalog = build_schema_catalog()
    assert catalog["companies"].identifies_rows("ticker")  # unique
    assert catalog["companies"].identifies_rows("id")  # primary key
    assert catalog["market_data"].identifies_rows("date")  # natural key
    assert not catalog["companies"].identifies_rows("sector")
