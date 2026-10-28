"""Retrieval agent: question -> relevant schema -> validated SQL -> rows."""

from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.agents.base import Agent, Trace
from app.core.exceptions import QueryExecutionError, SchemaNotIndexedError, UnsafeSQLError
from app.db.readonly import execute_readonly
from app.rag.schema_indexer import SchemaIndexer
from app.rag.sql_generator import SQLGenerator
from app.rag.sql_validator import validate_and_limit

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    sql: str
    rows: list[dict[str, Any]]
    tables: list[str]


class RetrievalAgent(Agent):
    name = "retrieval"

    def __init__(
        self,
        *,
        indexer: SchemaIndexer,
        sql_generator: SQLGenerator,
        engine: Engine,
        max_tables: int,
        max_rows: int,
        statement_timeout_ms: int,
    ) -> None:
        self._indexer = indexer
        self._generator = sql_generator
        self._engine = engine
        self._max_tables = max_tables
        self._max_rows = max_rows
        self._timeout_ms = statement_timeout_ms

    @property
    def allowed_tables(self) -> Collection[str]:
        return self._indexer.catalog.keys()

    async def run(self, question: str, trace: Trace) -> RetrievalResult:
        # Embedding the question is CPU-bound; keep it off the event loop.
        tables = await run_in_threadpool(
            self._indexer.find_relevant_tables, question, self._max_tables
        )
        if not tables:
            raise SchemaNotIndexedError("vector search returned no tables")
        table_names = [t.name for t in tables]
        self._record(trace, "schema_retrieved", {"tables": table_names})

        raw_sql = await self._generator.generate(question, tables)
        self._record(trace, "sql_generated", raw_sql)

        try:
            sql = validate_and_limit(
                raw_sql, allowed_tables=self.allowed_tables, max_rows=self._max_rows
            )
        except UnsafeSQLError as exc:
            self._record(trace, "sql_rejected", str(exc))
            exc.sql = raw_sql
            raise
        if sql != raw_sql:
            self._record(trace, "sql_normalized", sql)

        try:
            rows = await run_in_threadpool(
                execute_readonly, self._engine, sql, timeout_ms=self._timeout_ms
            )
        except SQLAlchemyError as exc:
            logger.warning("Generated SQL failed: %s", exc)
            self._record(trace, "sql_failed", type(exc).__name__)
            raise QueryExecutionError(str(exc), sql=sql) from exc

        self._record(
            trace,
            "sql_executed",
            {"rows": len(rows), "columns": list(rows[0]) if rows else []},
        )
        return RetrievalResult(sql=sql, rows=rows, tables=table_names)
