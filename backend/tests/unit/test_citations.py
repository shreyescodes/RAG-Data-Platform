import pytest

from app.rag.citations import OutputColumn, SqlLineage, build_citations, sql_lineage
from app.rag.schema_indexer import SchemaIndexer, build_schema_catalog
from app.rag.sql_generator import SQLGenerationOutput

CATALOG = build_schema_catalog()


def _by_name(lineage: SqlLineage) -> dict[str, OutputColumn]:
    return {o.name: o for o in lineage.output}


def test_join_lineage_resolves_aliases_to_tables() -> None:
    lineage = sql_lineage(
        "SELECT c.name, m.arr FROM companies c "
        "JOIN portfolio_companies p ON p.company_id = c.id "
        "JOIN performance_metrics m ON m.portfolio_company_id = p.id "
        "ORDER BY m.arr DESC LIMIT 5",
        CATALOG,
    )
    assert set(lineage.tables) == {"companies", "portfolio_companies", "performance_metrics"}
    assert "portfolio_companies.company_id" in lineage.columns  # join keys count too
    out = _by_name(lineage)
    assert out["name"].sources == ("companies.name",)
    assert out["name"].derivation == "column"
    assert out["arr"].sources == ("performance_metrics.arr",)
    assert lineage.aggregated is False
    assert lineage.key_columns == ("name",)  # companies.name is unique


def test_group_by_marks_group_keys_and_aggregates() -> None:
    lineage = sql_lineage(
        "SELECT p.investment_stage, AVG(m.churn_rate) AS avg_churn "
        "FROM performance_metrics m JOIN portfolio_companies p ON p.id = m.portfolio_company_id "
        "GROUP BY p.investment_stage",
        CATALOG,
    )
    out = _by_name(lineage)
    assert out["avg_churn"].derivation == "aggregate"
    assert out["avg_churn"].sources == ("performance_metrics.churn_rate",)
    assert lineage.aggregated is True
    assert lineage.key_columns == ("investment_stage",)


def test_result_names_are_paired_by_position() -> None:
    lineage = sql_lineage("SELECT count(*) FROM companies", CATALOG, ["count"])
    (count,) = lineage.output
    assert count.name == "count"
    assert count.derivation == "aggregate"
    assert count.sources == ("companies.*",)


def test_expressions_literals_and_ctes() -> None:
    lineage = sql_lineage(
        "WITH latest AS (SELECT portfolio_company_id, MAX(metric_date) AS d "
        "FROM performance_metrics GROUP BY 1) "
        "SELECT pm.arr * 12 AS x, 'k' AS lit FROM latest l "
        "JOIN performance_metrics pm ON pm.portfolio_company_id = l.portfolio_company_id "
        "AND pm.metric_date = l.d",
        CATALOG,
    )
    out = _by_name(lineage)
    assert out["x"].derivation == "expression"
    assert out["x"].sources == ("performance_metrics.arr",)
    assert out["lit"].derivation == "literal"
    assert lineage.tables == ("performance_metrics",)


def test_window_functions_are_expressions_not_aggregates() -> None:
    lineage = sql_lineage(
        "SELECT date, AVG(close_price) OVER (ORDER BY date ROWS 49 PRECEDING) AS ma "
        "FROM market_data WHERE ticker = 'NVDA'",
        CATALOG,
    )
    out = _by_name(lineage)
    assert out["ma"].derivation == "expression"
    assert lineage.aggregated is False
    assert lineage.key_columns == ("date",)  # part of market_data's natural key


def test_star_is_expanded() -> None:
    lineage = sql_lineage("SELECT * FROM companies", CATALOG)
    assert [o.name for o in lineage.output][:3] == ["id", "name", "ticker"]
    assert set(lineage.key_columns) == {"id", "name", "ticker"}


@pytest.mark.parametrize("sql", ["SELEC nonsense FROM", "DELETE FROM companies", ""])
def test_unresolvable_sql_yields_empty_lineage(sql: str) -> None:
    lineage = sql_lineage(sql, CATALOG)
    assert lineage.output == ()
    assert lineage.tables == ()


def test_build_citations_marks_tables_used_and_unretrieved(indexer: SchemaIndexer) -> None:
    search = indexer.search("monthly churn rate and ARR", 1)
    lineage = sql_lineage(
        "SELECT m.arr, d.close_price FROM performance_metrics m, market_data d", CATALOG
    )
    citations = build_citations(
        search=search,
        sql="SELECT ...",
        lineage_info=lineage,
        row_count=2,
        enrichment={
            "market_data": [{"ticker": "AAPL", "current_price": 1.0}],
            "sec_filings": [
                {"ticker": "AAPL", "form": "10-K", "filing_date": "2026-01-01", "url": "https://x"}
            ],
        },
        generation=SQLGenerationOutput(
            answerable=True,
            sql="SELECT 1",
            explanation="Joins metrics to prices.",
            tables_used=["performance_metrics"],
            confidence=0.8,
        ),
    )

    by_table = {t.table: t for t in citations.tables}
    assert by_table["performance_metrics"].used_in_sql is True
    assert by_table["performance_metrics"].via == "retrieved"
    assert by_table["performance_metrics"].rerank_score is not None
    assert by_table["companies"].used_in_sql is False
    assert by_table["market_data"].via == "sql_only"
    assert citations.retrieval_mode == "hybrid+rerank"
    assert citations.retrieval_confidence == by_table["performance_metrics"].rerank_score
    assert citations.generation_confidence == 0.8
    assert citations.sql_explanation == "Joins metrics to prices."
    assert citations.row_count == 2
    assert [s.label for s in citations.live_sources] == [
        "AAPL quote (Yahoo Finance)",
        "AAPL 10-K (2026-01-01)",
    ]
    assert citations.live_sources[0].url == "https://finance.yahoo.com/quote/AAPL"


def test_build_citations_without_retrieval() -> None:
    citations = build_citations(search=None, sql="", lineage_info=None, row_count=0, enrichment={})
    assert citations.tables == []
    assert citations.sql is None
    assert citations.retrieval_mode is None
