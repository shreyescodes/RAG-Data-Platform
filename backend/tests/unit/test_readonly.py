import datetime as dt
from decimal import Decimal

from sqlalchemy import Engine

from app.db.readonly import _to_jsonable, execute_readonly


def test_converts_values_to_json_types() -> None:
    assert _to_jsonable(Decimal("1.50")) == 1.5
    assert _to_jsonable(dt.date(2026, 1, 2)) == "2026-01-02"
    assert _to_jsonable(dt.datetime(2026, 1, 2, 3, 4)) == "2026-01-02T03:04:00"
    assert _to_jsonable("text") == "text"


def test_returns_rows_as_dicts(engine: Engine) -> None:
    rows = execute_readonly(
        engine, "SELECT ticker, name FROM companies WHERE ticker = 'AAPL'", timeout_ms=1000
    )
    assert rows == [{"ticker": "AAPL", "name": "Apple Inc."}]
