"""Execution of untrusted (LLM-generated) SQL.

SQL reaching this module has already passed `app.rag.sql_validator`. This is
the second line of defence: on PostgreSQL the statement runs inside a
`READ ONLY` transaction with a statement timeout, and the transaction is
always rolled back.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, text

Row = dict[str, Any]


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    return value


def execute_readonly(engine: Engine, sql: str, *, timeout_ms: int) -> list[Row]:
    with engine.connect() as conn, conn.begin() as tx:
        if conn.dialect.name == "postgresql":
            conn.execute(text("SET TRANSACTION READ ONLY"))
            # SET LOCAL cannot be parameterised; timeout_ms is a validated int.
            conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
        result = conn.execute(text(sql))
        columns = list(result.keys())
        rows = [
            {col: _to_jsonable(val) for col, val in zip(columns, row, strict=True)}
            for row in result.fetchall()
        ]
        tx.rollback()
    return rows
