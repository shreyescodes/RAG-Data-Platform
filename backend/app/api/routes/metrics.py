"""Observability endpoints: usage, cost, latency and failures over time."""

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import require_api_key
from app.db.models import utcnow
from app.db.repositories import MetricsRepository
from app.db.session import get_db
from app.observability.aggregation import (
    BUCKETS,
    MAX_WINDOW_ROWS,
    WINDOWS,
    recent,
    summarise,
    timeseries,
)
from app.schemas import MetricsSummary, MetricsWindow, RecentResponse, TimeseriesResponse

router = APIRouter(prefix="/metrics", tags=["metrics"], dependencies=[Depends(require_api_key)])

_WINDOW = Query(default="24h", description="Look-back window.")
_HIDDEN_QUERY = "Hidden"


@router.get("/summary", response_model=MetricsSummary)
def metrics_summary(
    window: MetricsWindow = _WINDOW,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MetricsSummary:
    """Totals, latency percentiles, model usage and the worst queries in the window."""
    since = utcnow() - WINDOWS[window]
    repo = MetricsRepository(db)
    summary = summarise(
        window,
        since,
        repo.requests_since(since, limit=MAX_WINDOW_ROWS),
        repo.calls_since(since, limit=MAX_WINDOW_ROWS * 8),
    )
    if settings.hide_metric_queries:
        for failing in summary.top_failing_queries:
            failing.query = _HIDDEN_QUERY
        for expensive in summary.most_expensive_queries:
            expensive.query = _HIDDEN_QUERY
    return summary


@router.get("/timeseries", response_model=TimeseriesResponse)
def metrics_timeseries(
    window: MetricsWindow = _WINDOW, db: Session = Depends(get_db)
) -> TimeseriesResponse:
    """Requests, failures, tokens, cost and latency per time bucket."""
    bucket = BUCKETS[window]
    now = utcnow()
    # Align buckets to round boundaries so charts read cleanly.
    seconds = bucket.total_seconds()
    since = dt.datetime.fromtimestamp(
        ((now - WINDOWS[window]).replace(tzinfo=dt.UTC).timestamp() // seconds) * seconds,
        tz=dt.UTC,
    ).replace(tzinfo=None)
    rows = MetricsRepository(db).requests_since(since, limit=MAX_WINDOW_ROWS)
    return TimeseriesResponse(
        window=window,
        bucket_seconds=int(seconds),
        points=timeseries(rows, since=since, until=now, bucket=bucket),
    )


@router.get("/recent", response_model=RecentResponse)
def metrics_recent(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RecentResponse:
    """The most recent requests with their usage and stage latencies."""
    requests = [recent(m) for m in MetricsRepository(db).recent(limit=limit)]
    if settings.hide_metric_queries:
        for item in requests:
            item.query = _HIDDEN_QUERY
    return RecentResponse(requests=requests)
