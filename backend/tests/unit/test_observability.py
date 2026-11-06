import asyncio
import datetime as dt

import pytest
from starlette.concurrency import run_in_threadpool

from app.db.models import LLMCall, RequestMetric
from app.observability.aggregation import percentile, recent, summarise, timeseries
from app.observability.metrics import (
    LLMCallRecord,
    current,
    estimate_tokens,
    record_llm_call,
    stage,
    track_request,
)
from app.observability.pricing import ModelPrice, PriceTable
from app.services.llm import endpoint_kind

NOW = dt.datetime(2026, 11, 5, 12, 0)


def _call(purpose: str = "analysis", **kw: object) -> LLMCallRecord:
    fields = {"model": "m", "prompt_tokens": 100, "completion_tokens": 20, "latency_ms": 5.0}
    return LLMCallRecord(purpose=purpose, **{**fields, **kw})  # type: ignore[arg-type]


# --- Collection ---------------------------------------------------------------------


async def test_collector_sees_calls_from_tasks_and_threads() -> None:
    with track_request() as metrics:
        await asyncio.gather(*(asyncio.to_thread(record_llm_call, _call()) for _ in range(2)))
        await run_in_threadpool(record_llm_call, _call(cached=True))
        with stage("analysis"):
            pass
        with stage("analysis"):  # repeated stages accumulate
            pass
    assert len(metrics.llm_calls) == 3
    assert metrics.prompt_tokens == 200  # cache hits cost no tokens
    assert metrics.cache_hits == 1
    assert set(metrics.stages_ms) == {"analysis"}
    assert metrics.elapsed_ms() >= 0
    assert current() is None


def test_recording_outside_a_request_is_a_no_op() -> None:
    record_llm_call(_call())
    with stage("analysis"):
        pass
    assert current() is None


def test_estimate_tokens() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("x" * 400) == 100


# --- Pricing and endpoints -------------------------------------------------------------


def test_hosted_models_use_built_in_prices() -> None:
    table = PriceTable({}, local_endpoint=False)
    assert table.cost_usd("openai/gpt-oss-120b", 1_000_000, 1_000_000) == pytest.approx(0.75)
    assert table.cost_usd("unknown-model", 1_000, 1_000) == 0.0


def test_local_models_are_free_unless_priced() -> None:
    assert PriceTable({}, local_endpoint=True).cost_usd("openai/gpt-oss-120b", 10**6, 0) == 0.0
    priced = PriceTable({"qwen": ModelPrice(input=0.01, output=0.02)}, local_endpoint=True)
    assert priced.cost_usd("qwen", 10**6, 10**6) == pytest.approx(0.03)


@pytest.mark.parametrize(
    ("url", "kind"),
    [
        ("http://localhost:11434/v1", "local"),
        ("http://127.0.0.1:8000/v1", "local"),
        ("http://192.168.1.20:8080/v1", "local"),
        ("http://ollama:11434/v1", "local"),
        ("http://host.docker.internal:8000/v1", "local"),
        ("http://gpu-box.lan/v1", "local"),
        ("https://api.groq.com/openai/v1", "remote"),
        ("https://api.openai.com/v1", "remote"),
        ("https://8.8.8.8/v1", "remote"),
        ("not a url", "remote"),
    ],
)
def test_endpoint_kind(url: str, kind: str) -> None:
    assert endpoint_kind(url) == kind


# --- Aggregation -------------------------------------------------------------------------


def _metric(minutes_ago: int, **kw: object) -> RequestMetric:
    fields: dict[str, object] = {
        "id": minutes_ago,
        "created_at": NOW - dt.timedelta(minutes=minutes_ago),
        "request_id": None,
        "query": "List companies",
        "success": True,
        "error_type": None,
        "model": "m",
        "llm_endpoint": "remote",
        "llm_calls": 2,
        "cache_hits": 0,
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "cost_usd": 0.001,
        "row_count": 3,
        "verification_status": "verified",
        "unsupported_claims": 0,
        "latency_total_ms": 1000.0,
        "latency_retrieval_ms": 50.0,
        "latency_sql_generation_ms": 400.0,
        "latency_sql_execution_ms": None,
        "latency_enrichment_ms": None,
        "latency_analysis_ms": 500.0,
        "latency_verification_ms": None,
    }
    return RequestMetric(**{**fields, **kw})


def test_percentile_is_nearest_rank() -> None:
    assert percentile([], 50) is None
    assert percentile([5.0], 95) == 5.0
    values = [float(v) for v in range(1, 101)]
    assert (percentile(values, 50), percentile(values, 95), percentile(values, 99)) == (
        50.0,
        95.0,
        99.0,
    )


def test_summary_totals_rates_and_rankings() -> None:
    metrics = [
        _metric(1, latency_total_ms=100.0, cost_usd=0.002, prompt_tokens=300),
        _metric(2, latency_total_ms=900.0, cache_hits=1),
        _metric(3, success=False, error_type="UnsafeSQLError", query="Drop it", cost_usd=0.0),
        _metric(4, success=False, error_type="UnsafeSQLError", query="drop  IT", cost_usd=0.0),
        _metric(5, success=False, error_type="LLMError", query="Other", cost_usd=0.0),
        _metric(6, verification_status="flagged", unsupported_claims=2),
    ]
    calls = [
        LLMCall(
            purpose="sql_generation",
            model="m",
            prompt_tokens=80,
            completion_tokens=10,
            cost_usd=0.0005,
            latency_ms=10.0,
            success=True,
            cached=False,
        ),
        LLMCall(
            purpose="analysis",
            model="m",
            prompt_tokens=50,
            completion_tokens=40,
            cost_usd=0.0,
            latency_ms=0.0,
            success=True,
            cached=True,
        ),
        LLMCall(
            purpose="analysis",
            model="other",
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=0.0,
            latency_ms=30.0,
            success=False,
            cached=False,
        ),
    ]

    s = summarise("24h", NOW - dt.timedelta(days=1), metrics, calls)

    assert (s.requests, s.successes, s.failures) == (6, 3, 3)
    assert s.error_rate == 0.5
    assert s.llm_calls == 12
    assert s.cache_hit_rate == pytest.approx(1 / 12, abs=1e-4)
    assert s.tokens.prompt == 800
    assert s.cost_usd == pytest.approx(0.004)
    assert s.latency_ms.p50 == 1000.0
    assert s.latency_ms.p95 == 1000.0
    assert set(s.stage_latency_ms) == {"retrieval", "sql_generation", "analysis"}
    assert s.errors_by_type == {"UnsafeSQLError": 2, "LLMError": 1}
    assert s.top_failing_queries[0].failures == 2  # case and whitespace insensitive
    assert s.top_failing_queries[0].last_error == "UnsafeSQLError"
    assert s.most_expensive_queries[0].cost_usd == 0.002
    assert s.verification.flagged == 1
    assert s.verification.unsupported_claims == 2
    by_model = {m.model: m for m in s.models}
    assert by_model["m"].cache_hits == 1
    assert by_model["m"].prompt_tokens == 80  # cached tokens are not billed
    assert by_model["m"].requests == 6
    assert by_model["other"].failed_calls == 1
    assert s.purposes[0].purpose == "sql_generation"


def test_empty_summary() -> None:
    s = summarise("1h", NOW, [], [])
    assert (s.requests, s.error_rate, s.cache_hit_rate) == (0, 0.0, 0.0)
    assert s.latency_ms.p50 is None
    assert s.models == []


def test_timeseries_buckets_include_empty_ones() -> None:
    since = NOW - dt.timedelta(hours=1)
    metrics = [_metric(1, latency_total_ms=200.0), _metric(2), _metric(50, success=False)]

    points = timeseries(metrics, since=since, until=NOW, bucket=dt.timedelta(minutes=15))

    assert len(points) == 4
    assert [p.requests for p in points] == [1, 0, 0, 2]
    assert points[0].failures == 1
    assert points[3].latency_p50_ms == 200.0
    assert points[1].latency_p50_ms is None
    assert points[1].start == since + dt.timedelta(minutes=15)


def test_recent_exposes_stage_latencies() -> None:
    row = recent(_metric(1))
    assert row.stage_latency_ms == {"retrieval": 50.0, "sql_generation": 400.0, "analysis": 500.0}
    assert row.latency_ms == 1000.0
