"""Natural language to SQL via an LLM, grounded on retrieved schema.

The model must reply with a `SQLGenerationOutput` JSON object. Each reply is
validated twice inside the retry loop: structurally (Pydantic) and
semantically (the SQL safety validator and the table allow-list), and every
rejection is fed back to the model for the next attempt. The SQL returned is
the validated, row-limited rendering, so it is exactly what will execute.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.exceptions import UnanswerableQueryError, UnsafeSQLError
from app.rag.schema_indexer import TableInfo
from app.rag.sql_validator import validate_and_limit
from app.services.cache import SemanticCache, schema_namespace
from app.services.structured_output import (
    Attempt,
    CacheKind,
    Extraction,
    OutputRejected,
    StructuredOutputError,
    StructuredOutputExtractor,
)

# Kept for clients of the pre-JSON protocol; the model no longer emits it.
CANNOT_ANSWER = "CANNOT_ANSWER"

PURPOSE = "sql_generation"
REPAIR_PURPOSE = "sql_repair"
# Database error text echoed back to the model when repairing a query.
_MAX_ERROR_CHARS = 300

_SYSTEM_PROMPT = """\
You translate questions about a financial database into one PostgreSQL query.

Rules:
- Use only the tables and columns defined in the schema. Never invent tables, \
columns or literal values that are not implied by the question.
- If the schema can answer only part of the question, write SQL for that part.
- If the schema cannot answer any part of it, set "answerable" to false and \
"sql" to null.
- Write a single read-only SELECT statement (CTEs are allowed). No DDL, DML \
or comments.
- Join only on the documented REFERENCES keys, or companies.ticker = \
market_data.ticker. Qualify columns with table aliases when joining.
- Upper-case symbols such as NVDA or AAPL are stock tickers: filter on a \
ticker column with equality, e.g. market_data.ticker = 'NVDA'.
- Match company names (e.g. "Apple") case-insensitively with ILIKE and \
wildcards, e.g. c.name ILIKE '%apple%'.
- Return at most {max_rows} rows and order results meaningfully.
- "tables_used" lists the tables the SQL reads; "confidence" (0 to 1) is how \
sure you are that the SQL answers the question as asked."""


class SQLGenerationOutput(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    answerable: bool = Field(description="False when the schema cannot answer any part.")
    # Required (though nullable): with constrained decoding an optional key is
    # one a small model may simply leave out.
    sql: str | None = Field(description="One read-only PostgreSQL SELECT; null if not answerable.")
    explanation: str = Field(
        max_length=1_000, description="One or two sentences on how the SQL answers it."
    )
    tables_used: list[str] = Field(description="Tables the SQL reads.")
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _sql_when_answerable(self) -> SQLGenerationOutput:
        if self.answerable and not self.sql:
            raise ValueError('"sql" is required when "answerable" is true')
        return self


@dataclass(frozen=True, slots=True)
class GeneratedSQL:
    sql: str  # validated and row-limited: exactly what will run
    raw_sql: str  # as the model wrote it
    output: SQLGenerationOutput
    attempts: tuple[Attempt, ...]
    cache: CacheKind | None = None
    # The earlier question whose SQL was reused, on a semantic cache hit.
    cache_source: str | None = None


def _schema_prompt(question: str, tables: Sequence[TableInfo]) -> str:
    schema = "\n\n".join(table.to_ddl() for table in tables)
    return f"Schema:\n{schema}\n\nQuestion: {question}"


class SQLGenerator:
    def __init__(
        self,
        extractor: StructuredOutputExtractor,
        *,
        max_rows: int,
        allowed_tables: Collection[str],
        semantic_cache: SemanticCache | None = None,
    ) -> None:
        self._extractor = extractor
        self._max_rows = max_rows
        self._allowed = {t.lower() for t in allowed_tables}
        self._semantic = semantic_cache

    async def generate(self, question: str, tables: Sequence[TableInfo]) -> GeneratedSQL:
        user = _schema_prompt(question, tables)
        namespace = schema_namespace(
            self._extractor.model, self._system, [t.to_ddl() for t in tables]
        )
        if self._semantic is not None:
            hit = self._semantic.lookup(namespace, question)
            reused = self._replay(user, hit.value) if hit is not None else None
            if reused is not None and hit is not None:
                return replace(reused, cache="semantic", cache_source=hit.question)
        generated = await self._run(user, purpose=PURPOSE)
        if self._semantic is not None:
            self._semantic.store(namespace, question, generated.output.model_dump_json())
        return generated

    async def repair(
        self, question: str, tables: Sequence[TableInfo], failed_sql: str, error: str
    ) -> GeneratedSQL:
        """Ask for a corrected query after `failed_sql` errored in the database."""
        detail = " ".join(error.split())[:_MAX_ERROR_CHARS]
        user = (
            f"{_schema_prompt(question, tables)}\n\n"
            f"This query failed in PostgreSQL:\n{failed_sql}\n\nError: {detail}\n\n"
            "Write a corrected query."
        )
        return await self._run(user, purpose=REPAIR_PURPOSE)

    @property
    def _system(self) -> str:
        return _SYSTEM_PROMPT.format(max_rows=self._max_rows)

    def _checker(self) -> tuple[dict[str, str], Callable[[SQLGenerationOutput], None]]:
        """A semantic validator that records each SQL's safe, row-limited form."""
        validated: dict[str, str] = {}

        def check(output: SQLGenerationOutput) -> None:
            if not output.answerable or not output.sql:
                return
            try:
                validated[output.sql] = validate_and_limit(
                    output.sql, allowed_tables=self._allowed, max_rows=self._max_rows
                )
            except UnsafeSQLError as exc:
                raise OutputRejected(f"SQL rejected by safety checks: {exc}", cause=exc) from exc

        return validated, check

    def _replay(self, user: str, reply: str) -> GeneratedSQL | None:
        """Reuse a cached reply if it still validates; None means regenerate."""
        validated, check = self._checker()
        extraction = self._extractor.replay(
            SQLGenerationOutput, reply, check, purpose=PURPOSE, prompt=user, kind="semantic"
        )
        if extraction is None or not extraction.value.answerable or not extraction.value.sql:
            return None
        return self._result(extraction, validated)

    async def _run(self, user: str, *, purpose: str) -> GeneratedSQL:
        validated, check = self._checker()
        try:
            extraction = await self._extractor.extract(
                SQLGenerationOutput,
                system=self._system,
                user=user,
                purpose=purpose,
                temperature=0.0,
                # Generous: reasoning models spend part of the budget thinking.
                max_tokens=2_000,
                validate=check,
            )
        except StructuredOutputError as exc:
            cause = exc.last_rejection.cause if exc.last_rejection else None
            last = exc.last_value
            if isinstance(cause, UnsafeSQLError) and isinstance(last, SQLGenerationOutput):
                # Keep the established contract: unsafe SQL is a safety rejection.
                raise UnsafeSQLError(str(cause), sql=last.sql) from exc
            raise

        output = extraction.value
        if not output.answerable or not output.sql:
            raise UnanswerableQueryError(
                f"model reported the schema cannot answer: {output.explanation}"
            )
        return self._result(extraction, validated)

    def _result(
        self, extraction: Extraction[SQLGenerationOutput], validated: dict[str, str]
    ) -> GeneratedSQL:
        output = extraction.value
        raw_sql = output.sql or ""
        # Self-reported metadata: keep only real tables (CTE aliases are not).
        output = output.model_copy(
            update={"tables_used": [t for t in output.tables_used if t.lower() in self._allowed]}
        )
        return GeneratedSQL(
            sql=validated[raw_sql],
            raw_sql=raw_sql,
            output=output,
            attempts=extraction.attempts,
            cache=extraction.cached,
        )
