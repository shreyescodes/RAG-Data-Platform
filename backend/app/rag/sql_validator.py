"""Static safety checks for LLM-generated SQL.

The generated statement must be a single read-only query over allow-listed
tables. Anything else is rejected before it reaches the database. The result
is re-rendered by sqlglot with an enforced row limit, so the executed SQL is
exactly what was validated.
"""

from __future__ import annotations

from collections.abc import Collection

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.core.exceptions import UnsafeSQLError

_DIALECT = "postgres"

# Node types that write, change schema or escape the query sandbox.
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,
    exp.Into,  # SELECT ... INTO new_table
    exp.Lock,  # SELECT ... FOR UPDATE
)

# Functions with side effects or access to the server, files or other DBs.
_FORBIDDEN_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink", "current_setting", "set_config")


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def _is_unfiltered(select: exp.Select, ctes: dict[str, exp.Expression]) -> bool:
    """Whether `select` reads every row of its source."""
    if any(select.args.get(key) for key in ("where", "group", "having")):
        return False
    source = select.find(exp.From)
    node = source.this if source is not None else None
    if isinstance(node, exp.Table) and node.name.lower() in ctes:
        node = ctes[node.name.lower()]
    if isinstance(node, exp.Subquery):
        node = node.this
    return _is_unfiltered(node, ctes) if isinstance(node, exp.Select) else True


def _counts_whole_table(statement: exp.Query) -> bool:
    ctes = {cte.alias_or_name.lower(): cte.this for cte in statement.find_all(exp.CTE)}
    return any(
        _is_unfiltered(select, ctes)
        for select in statement.find_all(exp.Select)
        if any(column.find(exp.Count) for column in select.expressions)
    )


def validate_and_limit(
    sql: str,
    *,
    allowed_tables: Collection[str],
    max_rows: int,
    block_dataset_size: bool = False,
) -> str:
    """Return a safe, row-limited rendering of `sql` or raise `UnsafeSQLError`."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise UnsafeSQLError("empty statement")

    try:
        statements = [s for s in sqlglot.parse(cleaned, read=_DIALECT) if s is not None]
    except ParseError as exc:
        raise UnsafeSQLError(f"unparseable SQL: {exc}") from exc

    if len(statements) != 1:
        raise UnsafeSQLError(f"expected exactly one statement, got {len(statements)}")
    statement = statements[0]

    if not isinstance(statement, exp.Query):
        raise UnsafeSQLError(f"only SELECT queries are allowed, got {statement.key}")

    for node in statement.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise UnsafeSQLError(f"forbidden construct: {node.key}")
        if isinstance(node, exp.Func):
            name = _function_name(node)
            if name.startswith(_FORBIDDEN_FUNCTION_PREFIXES):
                raise UnsafeSQLError(f"forbidden function: {name}")

    _check_tables(statement, allowed_tables)
    if block_dataset_size and _counts_whole_table(statement):
        raise UnsafeSQLError("counting every row of a table is not allowed; filter the rows")
    return _apply_limit(statement, max_rows).sql(dialect=_DIALECT)


def _check_tables(statement: exp.Query, allowed_tables: Collection[str]) -> None:
    allowed = {t.lower() for t in allowed_tables}
    cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}

    for table in statement.find_all(exp.Table):
        name = table.name.lower()
        schema = table.db.lower()
        if table.catalog or schema not in ("", "public"):
            raise UnsafeSQLError(f"schema-qualified table not allowed: {table.sql()}")
        if name in cte_names and not schema:
            continue
        if name not in allowed:
            raise UnsafeSQLError(f"table not allowed: {name}")


def _apply_limit(statement: exp.Query, max_rows: int) -> exp.Query:
    limit = statement.args.get("limit")
    if limit is None:
        return statement.limit(max_rows)

    value = limit.expression
    if isinstance(value, exp.Literal) and value.is_int and int(value.this) <= max_rows:
        return statement
    # Non-literal or excessive limits are clamped.
    return statement.limit(max_rows)
