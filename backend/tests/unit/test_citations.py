import pytest

from app.rag.citations import OutputColumn, SqlLineage, build_citations, sql_lineage
from app.rag.schema_indexer import SchemaIndexer, build_schema_catalog
from app.rag.sql_generator import SQLGenerationOutput

CATALOG = build_schema_catalog()


def _by_name(lineage: SqlLineage) -> dict[str, OutputColumn]:
    return {o.name: o for o in lineage.output}


def test_join_lineage_resolves_aliases_to_tables() -> None:
    lineage = sql_lineage(
        "SELECT f.name, c.sector, h.value_usd FROM funds f "
        "JOIN fund_holdings h ON h.fund_id = f.id "
        "JOIN companies c ON c.ticker = h.ticker "
        "ORDER BY h.value_usd DESC LIMIT 5",
        CATALOG,
    )
    assert set(lineage.tables) == {"funds", "fund_holdings", "companies"}
    assert "fund_holdings.fund_id" in lineage.columns  # join keys count too
    out = _by_name(lineage)
    assert out["name"].sources == ("funds.name",)
    assert out["name"].derivation == "column"
    assert out["value_usd"].sources == ("fund_holdings.value_usd",)
    assert lineage.aggregated is False
    assert lineage.key_columns == ("name",)  # funds.name is unique


def test_group_by_marks_group_keys_and_aggregates() -> None:
    lineage = sql_lineage(
        "SELECT h.report_date, SUM(h.value_usd) AS total_value "
        "FROM fund_holdings h JOIN funds f ON f.id = h.fund_id "
        "GROUP BY h.report_date",
        CATALOG,
    )
    out = _by_name(lineage)
    assert out["total_value"].derivation == "aggregate"
    assert out["total_value"].sources == ("fund_holdings.value_usd",)
    assert lineage.aggregated is True
    assert lineage.key_columns == ("report_date",)


def test_result_names_are_paired_by_position() -> None:
    lineage = sql_lineage("SELECT count(*) FROM companies", CATALOG, ["count"])
    (count,) = lineage.output
    assert count.name == "count"
    assert count.derivation == "aggregate"
    assert count.sources == ("companies.*",)


def test_expressions_literals_and_ctes() -> None:
    lineage = sql_lineage(
        "WITH latest AS (SELECT fund_id, MAX(report_date) AS d "
        "FROM fund_holdings GROUP BY 1) "
        "SELECT fh.value_usd / 1000000000 AS x, 'k' AS lit FROM latest l "
        "JOIN fund_holdings fh ON fh.fund_id = l.fund_id "
        "AND fh.report_date = l.d",
        CATALOG,
    )
    out = _by_name(lineage)
    assert out["x"].derivation == "expression"
    assert out["x"].sources == ("fund_holdings.value_usd",)
    assert out["lit"].derivation == "literal"
    assert lineage.tables == ("fund_holdings",)


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
    search = indexer.search("which stocks does each fund hold, shares and portfolio weight", 1)
    lineage = sql_lineage(
        "SELECT h.value_usd, d.close_price FROM fund_holdings h, market_data d", CATALOG
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
            explanation="Joins holdings to prices.",
            tables_used=["fund_holdings"],
            confidence=0.8,
        ),
    )

    by_table = {t.table: t for t in citations.tables}
    assert by_table["fund_holdings"].used_in_sql is True
    assert by_table["fund_holdings"].via == "retrieved"
    assert by_table["fund_holdings"].rerank_score is not None
    assert by_table["companies"].used_in_sql is False
    assert by_table["market_data"].via == "sql_only"
    assert citations.retrieval_mode == "hybrid+rerank"
    assert citations.retrieval_confidence == by_table["fund_holdings"].rerank_score
    assert citations.generation_confidence == 0.8
    assert citations.sql_explanation == "Joins holdings to prices."
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
