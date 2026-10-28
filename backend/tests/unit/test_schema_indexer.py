from app.rag.schema_indexer import SchemaIndexer, build_schema_catalog


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
