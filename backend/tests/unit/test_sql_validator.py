import pytest

from app.core.exceptions import UnsafeSQLError
from app.rag.sql_validator import validate_and_limit

ALLOWED = {"companies", "financial_statements", "market_data"}


def _validate(sql: str, max_rows: int = 500) -> str:
    return validate_and_limit(sql, allowed_tables=ALLOWED, max_rows=max_rows)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT name FROM companies",
        "select c.name, avg(f.revenue) from companies c "
        "join financial_statements f on f.company_id = c.id group by c.name",
        "WITH recent AS (SELECT * FROM market_data) SELECT ticker FROM recent",
        "SELECT ticker FROM companies UNION SELECT ticker FROM market_data",
        "SELECT name FROM public.companies",
        "SELECT name FROM companies;",
    ],
)
def test_accepts_read_only_queries(sql: str) -> None:
    assert _validate(sql).upper().startswith(("SELECT", "WITH"))


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("DELETE FROM companies", "only SELECT"),
        ("UPDATE companies SET name = 'x'", "only SELECT"),
        ("DROP TABLE companies", "only SELECT"),
        ("COPY companies TO '/tmp/out'", "only SELECT"),
        ("SELECT 1; DROP TABLE companies", "exactly one statement"),
        ("WITH d AS (DELETE FROM companies RETURNING *) SELECT * FROM d", "forbidden construct"),
        ("SELECT * INTO backup FROM companies", "forbidden construct"),
        ("SELECT * FROM companies FOR UPDATE", "forbidden construct"),
        ("SELECT pg_sleep(30)", "forbidden function"),
        ("SELECT pg_read_file('/etc/passwd')", "forbidden function"),
        ("SELECT current_setting('is_superuser')", "forbidden function"),
        ("SELECT * FROM query_logs", "table not allowed"),
        ("SELECT * FROM pg_catalog.pg_user", "schema-qualified"),
        ("SELECT * FROM information_schema.tables", "schema-qualified"),
        ("this is not sql", "unparseable|only SELECT"),
        ("SELECT FROM WHERE (", "unparseable"),
        ("   ", "empty"),
    ],
)
def test_rejects_unsafe_queries(sql: str, reason: str) -> None:
    with pytest.raises(UnsafeSQLError, match=reason):
        _validate(sql)


def test_adds_limit_when_missing() -> None:
    assert _validate("SELECT name FROM companies", max_rows=50).endswith("LIMIT 50")


def test_keeps_smaller_limit() -> None:
    assert _validate("SELECT name FROM companies LIMIT 5", max_rows=50).endswith("LIMIT 5")


def test_clamps_excessive_limit() -> None:
    assert _validate("SELECT name FROM companies LIMIT 100000", max_rows=50).endswith("LIMIT 50")


def test_cte_name_does_not_need_allow_listing() -> None:
    sql = "WITH totals AS (SELECT company_id FROM financial_statements) SELECT * FROM totals"
    assert "totals" in _validate(sql)
