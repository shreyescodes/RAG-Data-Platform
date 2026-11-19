"""Retrieval agent: question -> relevant schema -> validated SQL -> rows."""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass
from functools import partial
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.agents.base import Agent, Trace
from app.core.exceptions import (
    QueryExecutionError,
    RestrictedQueryError,
    SchemaNotIndexedError,
    UnsafeSQLError,
)
from app.db.readonly import execute_readonly
from app.observability.metrics import stage
from app.rag.citations import SqlLineage, sql_lineage
from app.rag.schema_indexer import SchemaIndexer, SchemaSearchResult
from app.rag.sql_generator import GeneratedSQL, SQLGenerator
from app.services.structured_output import Attempt, StructuredOutputError

logger = logging.getLogger(__name__)

_DATA_STORE = r"(?:database|dataset|data set|db|tables?|system|platform)"
_ASKS_DATASET_SIZE = re.compile(
    rf"\b(?:how many|number of|count of)\b[^?.]*\b(?:in|inside|within|across|stored|loaded)\b"
    rf"[^?.]*\b{_DATA_STORE}\b"
    rf"|\bhow many\b[^?.]*\b(?:do|does)\s+(?:you|it|this)\s+(?:have|hold|store|track|cover)\b"
    rf"|\b(?:size|row counts?)\s+of\s+(?:the|your|this)\s+(?:\w+\s+)?{_DATA_STORE}\b"
    rf"|\bhow (?:big|large) is\s+(?:the|your|this)\s+(?:\w+\s+)?{_DATA_STORE}\b"
    r"|\bhow much data\b|\brow counts?\b",
    re.IGNORECASE,
)


def asks_dataset_size(question: str) -> bool:
    """Whether the question is about how much data is stored."""
    return bool(_ASKS_DATASET_SIZE.search(question))


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    sql: str
    rows: list[dict[str, Any]]
    tables: list[str]
    search: SchemaSearchResult | None = None
    lineage: SqlLineage | None = None
    generation: GeneratedSQL | None = None


def _database_error(exc: SQLAlchemyError) -> str:
    """The driver's message, without SQLAlchemy's SQL echo and help links."""
    return str(getattr(exc, "orig", None) or exc)


class RetrievalAgent(Agent):
    name = "retrieval"

    def __init__(
        self,
        *,
        indexer: SchemaIndexer,
        sql_generator: SQLGenerator,
        engine: Engine,
        max_tables: int,
        statement_timeout_ms: int,
        repair_attempts: int = 1,
        block_dataset_size: bool = False,
    ) -> None:
        self._block_dataset_size = block_dataset_size
        self._indexer = indexer
        self._generator = sql_generator
        self._engine = engine
        self._max_tables = max_tables
        self._timeout_ms = statement_timeout_ms
        self._repair_attempts = repair_attempts

    @property
    def allowed_tables(self) -> Collection[str]:
        return self._indexer.catalog.keys()

    async def run(
        self, question: str, trace: Trace, *, context: str = "", search_hint: str = ""
    ) -> RetrievalResult:
        if self._block_dataset_size and asks_dataset_size(question):
            self._record(trace, "dataset_size_refused")
            raise RestrictedQueryError("question asks how much data is stored")
        # Embedding and reranking are CPU-bound; keep them off the event loop.
        with stage("retrieval"):
            search = await run_in_threadpool(
                self._indexer.search, f"{search_hint} {question}".strip(), self._max_tables
            )
        if not search.tables:
            raise SchemaNotIndexedError("schema search returned no tables")
        self._record(trace, "schema_retrieved", search.trace_detail())

        generated = await self._generate(
            trace, lambda: self._generator.generate(question, search.tables, context=context)
        )
        repairs = 0
        while True:
            try:
                with stage("sql_execution"):
                    rows = await run_in_threadpool(
                        execute_readonly, self._engine, generated.sql, timeout_ms=self._timeout_ms
                    )
                break
            except SQLAlchemyError as exc:
                logger.warning("Generated SQL failed: %s", exc)
                self._record(trace, "sql_failed", {"error": type(exc).__name__})
                if repairs >= self._repair_attempts:
                    raise QueryExecutionError(str(exc), sql=generated.sql) from exc
                repairs += 1
                repair = partial(
                    self._generator.repair,
                    question,
                    search.tables,
                    generated.sql,
                    _database_error(exc),
                    context=context,
                )
                generated = await self._generate(trace, repair, step="sql_repaired")

        columns = list(rows[0]) if rows else []
        self._record(trace, "sql_executed", {"rows": len(rows), "columns": columns})
        lineage = await run_in_threadpool(
            sql_lineage, generated.sql, self._indexer.catalog, columns
        )
        return RetrievalResult(
            sql=generated.sql,
            rows=rows,
            tables=search.table_names,
            search=search,
            lineage=lineage,
            generation=generated,
        )

    async def _generate(
        self,
        trace: Trace,
        call: Callable[[], Awaitable[GeneratedSQL]],
        *,
        step: str = "sql_generated",
    ) -> GeneratedSQL:
        try:
            with stage("sql_generation"):
                generated = await call()
        except StructuredOutputError as exc:
            self._record_rejections(trace, exc.attempts)
            self._record(trace, "sql_generation_failed", f"{len(exc.attempts)} invalid replies")
            raise
        except UnsafeSQLError as exc:
            if isinstance(exc.__cause__, StructuredOutputError):
                self._record_rejections(trace, exc.__cause__.attempts)
            self._record(trace, "sql_rejected", str(exc))
            raise

        self._record_rejections(trace, generated.attempts)
        out = generated.output
        self._record(
            trace,
            step,
            {
                "sql": generated.raw_sql,
                "explanation": out.explanation,
                "tables_used": out.tables_used,
                "confidence": out.confidence,
                "attempts": len(generated.attempts),
                "cache": generated.cache,
                **({"cache_source": generated.cache_source} if generated.cache_source else {}),
            },
        )
        if generated.sql != generated.raw_sql:
            self._record(trace, "sql_normalized", generated.sql)
        return generated

    def _record_rejections(self, trace: Trace, attempts: tuple[Attempt, ...]) -> None:
        for attempt in attempts:
            if not attempt.ok:
                self._record(trace, "sql_attempt_rejected", attempt.as_dict())
