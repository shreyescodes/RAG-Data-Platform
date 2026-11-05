"""Turns stored request metrics into dashboard summaries.

Aggregation runs in Python over the rows of one time window rather than in
SQL, so it is identical on PostgreSQL and SQLite and percentiles are exact.
The window is bounded (`MAX_WINDOW_ROWS`), which keeps this cheap at the
traffic a single deployment of this service handles.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from typing import TypeVar

from app.db.models import LLMCall, RequestMetric
from app.observability.metrics import STAGES
from app.schemas import (
    ExpensiveQuery,
    FailingQuery,
    LatencyStats,
    MetricsSummary,
    MetricsWindow,
    ModelUsage,
    PurposeUsage,
    RecentRequest,
    TimeseriesPoint,
    TokenUsage,
    VerificationStats,
)

WINDOWS: dict[MetricsWindow, dt.timedelta] = {
    "1h": dt.timedelta(hours=1),
    "6h": dt.timedelta(hours=6),
    "24h": dt.timedelta(hours=24),
    "7d": dt.timedelta(days=7),
    "30d": dt.timedelta(days=30),
}
BUCKETS: dict[MetricsWindow, dt.timedelta] = {
    "1h": dt.timedelta(minutes=5),
    "6h": dt.timedelta(minutes=15),
    "24h": dt.timedelta(hours=1),
    "7d": dt.timedelta(hours=6),
    "30d": dt.timedelta(days=1),
}
MAX_WINDOW_ROWS = 50_000
TOP_N = 5

T = TypeVar("T")
_WHITESPACE = re.compile(r"\s+")


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile; None for no data."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return round(ordered[rank - 1], 2)


def latency_stats(values: Sequence[float]) -> LatencyStats:
    if not values:
        return LatencyStats()
    return LatencyStats(
        p50=percentile(values, 50),
        p95=percentile(values, 95),
        p99=percentile(values, 99),
        mean=round(statistics.fmean(values), 2),
    )


def stage_latencies(metric: RequestMetric) -> dict[str, float]:
    found = {stage: getattr(metric, f"latency_{stage}_ms") for stage in STAGES}
    return {stage: ms for stage, ms in found.items() if ms is not None}


def _group(items: Iterable[T], key: Callable[[T], str]) -> dict[str, list[T]]:
    groups: dict[str, list[T]] = defaultdict(list)
    for item in items:
        groups[key(item)].append(item)
    return groups


def _normalise(query: str) -> str:
    return _WHITESPACE.sub(" ", query.strip().lower())


def summarise(
    window: MetricsWindow,
    since: dt.datetime,
    metrics: Sequence[RequestMetric],
    calls: Sequence[LLMCall],
) -> MetricsSummary:
    requests = len(metrics)
    failures = [m for m in metrics if not m.success]
    prompt = sum(m.prompt_tokens for m in metrics)
    completion = sum(m.completion_tokens for m in metrics)
    cost = math.fsum(m.cost_usd for m in metrics)
    llm_calls = sum(m.llm_calls for m in metrics)
    cache_hits = sum(m.cache_hits for m in metrics)

    stage_values: dict[str, list[float]] = defaultdict(list)
    for m in metrics:
        for stage, ms in stage_latencies(m).items():
            stage_values[stage].append(ms)

    errors: dict[str, int] = defaultdict(int)
    for m in failures:
        errors[m.error_type or "unknown"] += 1

    verified = [m for m in metrics if m.verification_status in ("verified", "flagged")]
    requests_by_model = {k: len(v) for k, v in _group(metrics, lambda m: m.model).items()}
    models = [
        ModelUsage(
            model=model,
            requests=requests_by_model.get(model, 0),
            llm_calls=len(group),
            failed_calls=sum(not c.success for c in group),
            cache_hits=sum(c.cached for c in group),
            prompt_tokens=sum(c.prompt_tokens for c in group if not c.cached),
            completion_tokens=sum(c.completion_tokens for c in group if not c.cached),
            cost_usd=round(math.fsum(c.cost_usd for c in group), 6),
            avg_latency_ms=(
                round(statistics.fmean(c.latency_ms for c in live), 2)
                if (live := [c for c in group if not c.cached])
                else None
            ),
        )
        for model, group in _group(calls, lambda c: c.model).items()
    ]
    purposes = [
        PurposeUsage(
            purpose=purpose,
            llm_calls=len(group),
            prompt_tokens=sum(c.prompt_tokens for c in group if not c.cached),
            completion_tokens=sum(c.completion_tokens for c in group if not c.cached),
            cost_usd=round(math.fsum(c.cost_usd for c in group), 6),
        )
        for purpose, group in _group(calls, lambda c: c.purpose).items()
    ]

    failing = []
    for group in _group(failures, lambda m: _normalise(m.query)).values():
        last = max(group, key=lambda m: m.created_at)
        failing.append(
            FailingQuery(
                query=last.query,
                failures=len(group),
                last_error=last.error_type,
                last_seen=last.created_at,
            )
        )
    failing.sort(key=lambda f: (-f.failures, -f.last_seen.timestamp()))

    expensive = sorted(
        metrics, key=lambda m: (m.cost_usd, m.prompt_tokens + m.completion_tokens), reverse=True
    )

    return MetricsSummary(
        window=window,
        since=since,
        requests=requests,
        successes=requests - len(failures),
        failures=len(failures),
        error_rate=round(len(failures) / requests, 4) if requests else 0.0,
        llm_calls=llm_calls,
        cache_hits=cache_hits,
        cache_hit_rate=round(cache_hits / llm_calls, 4) if llm_calls else 0.0,
        tokens=TokenUsage(prompt=prompt, completion=completion, total=prompt + completion),
        cost_usd=round(cost, 6),
        avg_cost_per_request_usd=round(cost / requests, 6) if requests else 0.0,
        latency_ms=latency_stats([m.latency_total_ms for m in metrics]),
        stage_latency_ms={s: latency_stats(stage_values[s]) for s in STAGES if stage_values[s]},
        verification=VerificationStats(
            checked=len(verified),
            flagged=sum(m.verification_status == "flagged" for m in verified),
            unsupported_claims=sum(m.unsupported_claims or 0 for m in verified),
        ),
        errors_by_type=dict(sorted(errors.items(), key=lambda kv: -kv[1])),
        models=sorted(models, key=lambda u: -u.llm_calls),
        purposes=sorted(purposes, key=lambda u: -(u.prompt_tokens + u.completion_tokens)),
        top_failing_queries=failing[:TOP_N],
        most_expensive_queries=[
            ExpensiveQuery(
                query=m.query,
                cost_usd=round(m.cost_usd, 6),
                total_tokens=m.prompt_tokens + m.completion_tokens,
                latency_ms=m.latency_total_ms,
                created_at=m.created_at,
            )
            for m in expensive[:TOP_N]
            if m.prompt_tokens + m.completion_tokens > 0
        ],
    )


def timeseries(
    metrics: Sequence[RequestMetric],
    *,
    since: dt.datetime,
    until: dt.datetime,
    bucket: dt.timedelta,
) -> list[TimeseriesPoint]:
    """Fixed-width buckets from `since` to `until`, empty buckets included."""
    size = bucket.total_seconds()
    count = max(1, math.ceil((until - since).total_seconds() / size))
    buckets: list[list[RequestMetric]] = [[] for _ in range(count)]
    for m in metrics:
        index = int((m.created_at - since).total_seconds() // size)
        if 0 <= index < count:
            buckets[index].append(m)
    points = []
    for i, group in enumerate(buckets):
        latencies = [m.latency_total_ms for m in group]
        points.append(
            TimeseriesPoint(
                start=since + bucket * i,
                requests=len(group),
                failures=sum(not m.success for m in group),
                prompt_tokens=sum(m.prompt_tokens for m in group),
                completion_tokens=sum(m.completion_tokens for m in group),
                cost_usd=round(math.fsum(m.cost_usd for m in group), 6),
                latency_p50_ms=percentile(latencies, 50),
                latency_p95_ms=percentile(latencies, 95),
            )
        )
    return points


def recent(metric: RequestMetric) -> RecentRequest:
    return RecentRequest(
        id=metric.id,
        created_at=metric.created_at,
        request_id=metric.request_id,
        query=metric.query,
        success=metric.success,
        error_type=metric.error_type,
        model=metric.model,
        llm_endpoint=metric.llm_endpoint,
        llm_calls=metric.llm_calls,
        cache_hits=metric.cache_hits,
        prompt_tokens=metric.prompt_tokens,
        completion_tokens=metric.completion_tokens,
        cost_usd=round(metric.cost_usd, 6),
        latency_ms=metric.latency_total_ms,
        stage_latency_ms=stage_latencies(metric),
        verification_status=metric.verification_status,
        unsupported_claims=metric.unsupported_claims,
    )
