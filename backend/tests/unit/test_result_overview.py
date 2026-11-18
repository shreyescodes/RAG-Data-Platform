import itertools
from datetime import date, timedelta
from typing import Any

from app.agents.result_overview import (
    column_overview,
    representative_indices,
    series_patterns,
)


def _series(closes: list[float]) -> list[dict[str, Any]]:
    start = date(2026, 1, 1)
    return [
        {"date": (start + timedelta(days=i)).isoformat(), "close": close}
        for i, close in enumerate(closes)
    ]


def test_short_results_keep_every_row() -> None:
    rows = _series([1.0, 2.0, 3.0])
    assert representative_indices(rows, 25) == [0, 1, 2]


def test_long_results_span_the_first_and_last_rows_within_the_limit() -> None:
    rows = _series([float(i) for i in range(120)])

    picked = representative_indices(rows, 25)

    assert picked == sorted(set(picked))
    assert len(picked) <= 25
    assert picked[0] == 0
    assert picked[-1] == 119
    assert max(b - a for a, b in itertools.pairwise(picked)) <= 10


def test_long_results_keep_the_highest_and_lowest_rows() -> None:
    closes = [100.0] * 120
    closes[37] = 500.0
    closes[83] = 5.0

    picked = representative_indices(_series(closes), 10)

    assert {37, 83} <= set(picked)


def test_overview_describes_numbers_across_every_row() -> None:
    rows = _series([10.0, 40.0, 5.0, 25.0])

    close = column_overview(rows)["close"]

    assert close["first"] == {"value": 10.0, "row": {"date": "2026-01-01"}}
    assert close["last"] == {"value": 25.0, "row": {"date": "2026-01-04"}}
    assert close["highest"] == {"value": 40.0, "row": {"date": "2026-01-02"}}
    assert close["lowest"] == {"value": 5.0, "row": {"date": "2026-01-03"}}
    assert close["average"] == 20.0


def test_overview_describes_text_columns_and_skips_empty_ones() -> None:
    rows: list[dict[str, Any]] = [
        {"ticker": "AAPL", "note": None},
        {"ticker": None, "note": None},
        {"ticker": "MSFT", "note": None},
    ]

    overview = column_overview(rows)

    assert overview["ticker"] == {
        "first": "AAPL",
        "last": "MSFT",
        "distinct": 2,
        "values": ["AAPL", "MSFT"],
    }
    assert "note" not in overview


def test_overview_does_not_list_every_value_of_a_long_text_column() -> None:
    rows = [{"name": f"Fund {i}"} for i in range(40)]

    name = column_overview(rows)["name"]

    assert name["distinct"] == 40
    assert "values" not in name


def _price_and_average(pairs: list[tuple[float, float]]) -> list[dict[str, Any]]:
    start = date(2026, 1, 1)
    return [
        {"date": (start + timedelta(days=i)).isoformat(), "close": close, "ma_50": average}
        for i, (close, average) in enumerate(pairs)
    ]


def test_patterns_report_every_crossing_and_the_latest_state() -> None:
    rows = _price_and_average([(11.0, 10.0), (9.0, 10.0), (12.0, 10.0), (8.0, 10.0), (7.0, 10.0)])

    comparison = series_patterns(rows)[0]

    assert "close was above ma_50 on 2 of 5 rows and below it on 3." in comparison
    assert "crossed ma_50 3 times" in comparison
    assert "2026-01-04 (moved below), 2026-01-03 (moved above)" in comparison
    assert "stayed below ma_50 from 2026-01-04 through 2026-01-05" in comparison


def test_patterns_do_not_depend_on_query_order() -> None:
    rows = _price_and_average([(11.0, 10.0), (9.0, 10.0), (12.0, 10.0), (8.0, 10.0)])

    assert series_patterns(list(reversed(rows))) == series_patterns(rows)


def test_patterns_say_when_columns_never_cross() -> None:
    rows = _price_and_average([(12.0, 10.0), (13.0, 10.0), (14.0, 10.0)])

    assert "It never crossed ma_50." in series_patterns(rows)[0]


def test_patterns_count_rises_and_falls() -> None:
    rows = _series([10.0, 12.0, 11.0, 15.0])

    assert series_patterns(rows) == [
        "close rose on 2 of 3 row-to-row changes and fell on 1, "
        "going from 10.00 on 2026-01-01 to 15.00 on 2026-01-04."
    ]


def test_patterns_do_not_compare_columns_on_different_scales() -> None:
    rows = [
        {"date": f"2026-01-0{i + 1}", "close": 100.0 + i, "volume": 5_000_000.0 + i}
        for i in range(4)
    ]

    assert not any(
        "volume was above" in line or "close was above" in line for line in series_patterns(rows)
    )


def test_patterns_are_empty_when_rows_mix_several_series() -> None:
    rows = [
        {"date": "2026-01-01", "ticker": "AAPL", "close": 10.0},
        {"date": "2026-01-01", "ticker": "MSFT", "close": 20.0},
        {"date": "2026-01-02", "ticker": "AAPL", "close": 11.0},
        {"date": "2026-01-02", "ticker": "MSFT", "close": 21.0},
    ]

    assert series_patterns(rows) == []
