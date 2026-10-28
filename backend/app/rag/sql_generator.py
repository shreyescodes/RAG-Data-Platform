"""Natural language to SQL via an LLM, grounded on retrieved schema."""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.core.exceptions import LLMError, UnanswerableQueryError
from app.rag.schema_indexer import TableInfo
from app.services.llm import ChatModel

CANNOT_ANSWER = "CANNOT_ANSWER"

_SYSTEM_PROMPT = f"""\
You translate questions about a financial database into one PostgreSQL query.

Rules:
- Use only the tables and columns defined in the schema. Never invent tables, \
columns or literal values that are not implied by the question.
- If the schema can answer only part of the question, write SQL for that part.
- If the schema cannot answer any part of it, reply with exactly {CANNOT_ANSWER}.
- Write a single read-only SELECT statement (CTEs are allowed). No DDL, DML, \
comments or explanations.
- Join only on the documented REFERENCES keys, or companies.ticker = \
market_data.ticker. Qualify columns with table aliases when joining.
- Upper-case symbols such as NVDA or AAPL are stock tickers: filter on a \
ticker column with equality, e.g. market_data.ticker = 'NVDA'.
- Match company names (e.g. "Apple") case-insensitively with ILIKE and \
wildcards, e.g. c.name ILIKE '%apple%'.
- Return at most {{max_rows}} rows and order results meaningfully.

Reply with the SQL only, without markdown fences."""

_FENCE_RE = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def extract_sql(completion: str) -> str:
    """Strip markdown fences or surrounding prose from a completion."""
    match = _FENCE_RE.search(completion)
    sql = match.group(1) if match else completion
    return sql.strip()


class SQLGenerator:
    def __init__(self, chat_model: ChatModel, *, max_rows: int) -> None:
        self._chat = chat_model
        self._max_rows = max_rows

    async def generate(self, question: str, tables: Sequence[TableInfo]) -> str:
        schema = "\n\n".join(table.to_ddl() for table in tables)
        completion = await self._chat.complete(
            system=_SYSTEM_PROMPT.format(max_rows=self._max_rows),
            user=f"Schema:\n{schema}\n\nQuestion: {question}",
            temperature=0.0,
            # Generous: reasoning models spend part of the budget thinking.
            max_tokens=2000,
        )
        sql = extract_sql(completion)
        if CANNOT_ANSWER in sql.upper():
            raise UnanswerableQueryError("model reported the schema cannot answer")
        if not sql:
            raise LLMError("model returned no SQL")
        return sql
