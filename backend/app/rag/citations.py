"""Answer provenance: what was retrieved, the SQL that ran and where rows came from.

Column lineage is derived statically from the executed SQL with sqlglot, so
it costs no database round-trip and no LLM call. It is best-effort: any SQL
sqlglot cannot resolve yields `derivation="unknown"` rather than an error.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import sqlglot
from sqlglot import exp
from sqlglot.lineage import lineage
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import build_scope

from app.rag.schema_indexer import SchemaSearchResult, TableInfo
from app.rag.sql_generator import SQLGenerationOutput
from app.schemas import Citations, ColumnCitation, LiveSourceCitation, TableCitation

logger = logging.getLogger(__name__)

_DIALECT = "postgres"
YAHOO_QUOTE_URL = "https://finance.yahoo.com/quote/{ticker}"

Derivation = Literal["column", "aggregate", "expression", "literal", "unknown"]


@dataclass(frozen=True, slots=True)
class OutputColumn:
    name: str
    sources: tuple[str, ...]  # "table.column"
    derivation: Derivation


@dataclass(frozen=True, slots=True)
class SqlLineage:
    tables: tuple[str, ...] = ()
    columns: tuple[str, ...] = ()  # every physical column the query reads
    output: tuple[OutputColumn, ...] = ()
    aggregated: bool = False
    key_columns: tuple[str, ...] = ()


def _schema(catalog: Mapping[str, TableInfo]) -> dict[str, object]:
    return {name: {c.name: c.type for c in t.columns} for name, t in catalog.items()}


def _leaf_sources(name: str, qualified: exp.Query, schema: dict[str, object]) -> list[str]:
    root = lineage(name, qualified, schema=schema, dialect=_DIALECT)
    found: list[str] = []
    for node in root.walk():
        if isinstance(node.expression, exp.Table):
            source = f"{node.expression.name}.{node.name.rsplit('.', 1)[-1]}"
            if source not in found:
                found.append(source)
    return found


def _derivation(select: exp.Expr, sources: Sequence[str]) -> Derivation:
    expr = select.unalias()
    if isinstance(expr, exp.Column) and sources:
        return "column"
    if expr.find(exp.Window):
        return "expression"
    if expr.find(exp.AggFunc):
        return "aggregate"
    if sources:
        return "expression"
    return "literal"


def sql_lineage(
    sql: str, catalog: Mapping[str, TableInfo], result_columns: Sequence[str] = ()
) -> SqlLineage:
    """Static lineage of `sql`. `result_columns` are the executed result's names.

    Output columns are paired with `result_columns` by position (the database
    names unaliased expressions itself, e.g. `count`), falling back to the
    names sqlglot assigns when the counts differ.
    """
    schema = _schema(catalog)
    try:
        parsed = sqlglot.parse_one(sql, read=_DIALECT)
        if not isinstance(parsed, exp.Query):
            return SqlLineage()
        qualified = qualify(
            parsed,
            schema=schema,
            dialect=_DIALECT,
            quote_identifiers=False,
            validate_qualify_columns=False,
        )
        scope = build_scope(qualified)
    except Exception as exc:  # provenance is best-effort and must never fail a query
        logger.debug("Lineage unavailable: %r", exc)
        return SqlLineage()

    tables: list[str] = []
    columns: list[str] = []
    if scope is not None:
        for sub in scope.traverse():
            for source in sub.sources.values():
                if isinstance(source, exp.Table) and source.name not in tables:
                    tables.append(source.name)
            for col in sub.columns:
                origin = sub.sources.get(col.table)
                if isinstance(origin, exp.Table):
                    ref = f"{origin.name}.{col.name}"
                    if ref not in columns:
                        columns.append(ref)

    selects = qualified.selects
    names = (
        list(result_columns)
        if len(result_columns) == len(selects)
        else [s.alias_or_name for s in selects]
    )
    output: list[OutputColumn] = []
    for name, select in zip(names, selects, strict=True):
        try:
            sources = _leaf_sources(select.alias_or_name, qualified, schema)
        except Exception as exc:  # see above
            logger.debug("Lineage of %s unavailable: %r", name, exc)
            output.append(OutputColumn(name=name, sources=(), derivation="unknown"))
            continue
        derivation = _derivation(select, sources)
        if derivation == "aggregate" and not sources:
            sources = [f"{t}.*" for t in tables]  # COUNT(*) and friends
        output.append(OutputColumn(name=name, sources=tuple(sources), derivation=derivation))

    grouped = isinstance(qualified, exp.Select) and qualified.args.get("group") is not None
    aggregated = grouped or any(o.derivation == "aggregate" for o in output)
    if aggregated:
        keys = [o.name for o in output if o.derivation in ("column", "expression")]
    else:
        keys = [
            o.name
            for o in output
            if o.derivation == "column"
            and len(o.sources) == 1
            and _identifies_rows(o.sources[0], catalog)
        ]
    return SqlLineage(
        tables=tuple(tables),
        columns=tuple(columns),
        output=tuple(output),
        aggregated=aggregated,
        key_columns=tuple(keys),
    )


def _identifies_rows(source: str, catalog: Mapping[str, TableInfo]) -> bool:
    table, _, column = source.partition(".")
    info = catalog.get(table)
    return info is not None and info.identifies_rows(column)


def _live_sources(enrichment: Mapping[str, Any]) -> list[LiveSourceCitation]:
    sources: list[LiveSourceCitation] = []
    for quote in enrichment.get("market_data", []):
        ticker = str(quote.get("ticker", ""))
        if ticker:
            sources.append(
                LiveSourceCitation(
                    kind="market_data",
                    ticker=ticker,
                    label=f"{ticker} quote (Yahoo Finance)",
                    url=YAHOO_QUOTE_URL.format(ticker=ticker),
                )
            )
    for filing in enrichment.get("sec_filings", []):
        ticker = str(filing.get("ticker", ""))
        label = f"{ticker} {filing.get('form', 'filing')} ({filing.get('filing_date', '?')})"
        url = filing.get("url")
        sources.append(
            LiveSourceCitation(
                kind="sec_filing", ticker=ticker, label=label, url=str(url) if url else None
            )
        )
    return sources


def build_citations(
    *,
    search: SchemaSearchResult | None,
    sql: str | None,
    lineage_info: SqlLineage | None,
    row_count: int,
    enrichment: Mapping[str, Any],
    generation: SQLGenerationOutput | None = None,
) -> Citations:
    used = set(lineage_info.tables) if lineage_info else set()
    tables: list[TableCitation] = []
    if search is not None:
        for score in search.table_scores:
            tables.append(
                TableCitation(
                    table=score.table,
                    rank=score.rank,
                    via=score.via,
                    used_in_sql=score.table in used,
                    score=_round(score.score),
                    dense_score=_round(score.dense_score),
                    sparse_score=_round(score.sparse_score),
                    fused_score=_round(score.fused_score),
                    rerank_score=_round(score.rerank_score),
                    best_document=score.best_document,
                    matched_columns=list(score.matched_columns),
                )
            )
    shown = {t.table for t in tables}
    for extra in sorted(used - shown):
        # Allow-listed, but not among the tables the generator was shown.
        tables.append(
            TableCitation(table=extra, rank=len(tables) + 1, via="sql_only", used_in_sql=True)
        )

    return Citations(
        retrieval_mode=search.mode if search is not None else None,
        retrieval_confidence=_round(search.confidence) if search is not None else None,
        generation_confidence=_round(generation.confidence) if generation else None,
        sql=sql or None,
        sql_explanation=generation.explanation if generation else None,
        tables=tables,
        columns_referenced=list(lineage_info.columns) if lineage_info else [],
        output_columns=[
            ColumnCitation(output_column=o.name, sources=list(o.sources), derivation=o.derivation)
            for o in (lineage_info.output if lineage_info else ())
        ],
        key_columns=list(lineage_info.key_columns) if lineage_info else [],
        aggregated=lineage_info.aggregated if lineage_info else False,
        row_count=row_count,
        live_sources=_live_sources(enrichment),
    )


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 4)
