"""A compact view of a query result that stays faithful to every row.

The LLM cannot read a long result in full. These helpers summarise each column
over all rows and pick the rows that best represent the whole result, so an
answer covers it from start to finish instead of only its first rows.
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Mapping, Sequence
from datetime import date
from itertools import combinations, pairwise
from typing import Any

# Upper bound on the rows summarised and fact-checked for one answer.
MAX_SCANNED_ROWS = 1_000

_MAX_ROW_LABELS = 3
_MAX_LISTED_VALUES = 10
_MAX_PATTERN_COLUMNS = 6
_MAX_COMPARISONS = 5
_MAX_TRENDS = 4
_MAX_LISTED_CROSSINGS = 5
# Columns on a similar scale can be compared (a price and its moving average).
_COMPARABLE_RATIO = 2.0
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

Row = Mapping[str, Any]


def is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _numeric_columns(rows: Sequence[Row]) -> dict[str, list[tuple[int, float]]]:
    columns: dict[str, list[tuple[int, float]]] = {}
    for i, row in enumerate(rows):
        for column, value in row.items():
            if is_number(value):
                columns.setdefault(column, []).append((i, float(value)))
    return columns


def representative_indices(rows: Sequence[Row], limit: int) -> list[int]:
    """Up to `limit` row positions, in order, that represent the whole result.

    Keeps the first and last rows, then each numeric column's highest and lowest
    rows, and spaces the remaining picks evenly between.
    """
    total = len(rows)
    if total <= limit:
        return list(range(total))

    chosen = {0, total - 1}
    for values in _numeric_columns(rows).values():
        for index, _ in (min(values, key=lambda v: v[1]), max(values, key=lambda v: v[1])):
            if len(chosen) < limit:
                chosen.add(index)

    remaining = limit - len(chosen)
    chosen.update(round((k + 1) * (total - 1) / (remaining + 1)) for k in range(remaining))
    return sorted(chosen)


def _row_label(row: Row) -> dict[str, Any]:
    """The cells that identify a row, such as its date or company."""
    cells = [(k, v) for k, v in row.items() if v is not None and not is_number(v)]
    return dict(cells[:_MAX_ROW_LABELS])


def _point(rows: Sequence[Row], index: int, value: float) -> dict[str, Any]:
    label = _row_label(rows[index])
    return {"value": value, "row": label} if label else {"value": value}


def column_overview(rows: Sequence[Row]) -> dict[str, dict[str, Any]]:
    """Per-column facts computed from every row in `rows`."""
    numeric = _numeric_columns(rows)
    overview: dict[str, dict[str, Any]] = {}
    for column in dict.fromkeys(column for row in rows for column in row):
        if column in numeric:
            values = numeric[column]
            lowest = min(values, key=lambda v: v[1])
            highest = max(values, key=lambda v: v[1])
            overview[column] = {
                "first": _point(rows, *values[0]),
                "last": _point(rows, *values[-1]),
                "lowest": _point(rows, *lowest),
                "highest": _point(rows, *highest),
                "average": math.fsum(v for _, v in values) / len(values),
            }
            continue
        present = [row[column] for row in rows if row.get(column) is not None]
        if not present:
            continue
        distinct = list(dict.fromkeys(str(value) for value in present))
        summary: dict[str, Any] = {
            "first": present[0],
            "last": present[-1],
            "distinct": len(distinct),
        }
        if len(distinct) <= _MAX_LISTED_VALUES:
            summary["values"] = distinct
        overview[column] = summary
    return overview


def _date_key(value: Any) -> str | None:
    if isinstance(value, date):
        return value.isoformat()[:10]
    if isinstance(value, str) and _ISO_DATE.match(value):
        return value[:10]
    return None


def _chronological(rows: Sequence[Row]) -> list[tuple[str, Row]] | None:
    """Rows oldest first, when they form one series with a single row per date."""
    if not rows:
        return None
    for column in rows[0]:
        keys = [_date_key(row.get(column)) for row in rows]
        if all(keys) and len(set(keys)) == len(rows):
            return sorted(
                ((str(k), r) for k, r in zip(keys, rows, strict=True)), key=lambda p: p[0]
            )
    return None


def _comparison(a: str, b: str, series: Sequence[tuple[str, Row]]) -> str:
    above = below = 0
    state = 0
    crossings: list[tuple[str, str]] = []
    for day, row in series:
        difference = float(row[a]) - float(row[b])
        current = (difference > 0) - (difference < 0)
        above += current > 0
        below += current < 0
        if current and state and current != state:
            crossings.append((day, "above" if current > 0 else "below"))
        state = current or state

    line = f"{a} was above {b} on {above} of {len(series)} rows and below it on {below}."
    if not crossings:
        return f"{line} It never crossed {b}."
    latest = ", ".join(
        f"{day} (moved {side})" for day, side in reversed(crossings[-_MAX_LISTED_CROSSINGS:])
    )
    day, side = crossings[-1]
    return (
        f"{line} It crossed {b} {len(crossings)} times; latest crossings: {latest}. "
        f"It stayed {side} {b} from {day} through {series[-1][0]}."
    )


def _trend(column: str, series: Sequence[tuple[str, Row]]) -> str:
    values = [float(row[column]) for _, row in series]
    changes = [after - before for before, after in pairwise(values)]
    rose = sum(change > 0 for change in changes)
    fell = sum(change < 0 for change in changes)
    return (
        f"{column} rose on {rose} of {len(changes)} row-to-row changes and fell on {fell}, "
        f"going from {values[0]:,.2f} on {series[0][0]} to {values[-1]:,.2f} on {series[-1][0]}."
    )


def series_patterns(rows: Sequence[Row]) -> list[str]:
    """How a dated series moved, computed from every row.

    Empty unless the rows form a single series, because crossings between
    different companies' rows would mean nothing.
    """
    series = _chronological(rows)
    if series is None or len(series) < 3:
        return []
    columns = [
        column for column in series[0][1] if all(is_number(row.get(column)) for _, row in series)
    ][:_MAX_PATTERN_COLUMNS]
    typical = {c: abs(statistics.median(float(r[c]) for _, r in series)) for c in columns}
    pairs = [
        (a, b)
        for a, b in combinations(columns, 2)
        if typical[a]
        and typical[b]
        and max(typical[a], typical[b]) / min(typical[a], typical[b]) <= _COMPARABLE_RATIO
    ]
    return [
        *(_comparison(a, b, series) for a, b in pairs[:_MAX_COMPARISONS]),
        *(_trend(column, series) for column in columns[:_MAX_TRENDS]),
    ]
