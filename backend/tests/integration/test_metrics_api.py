from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LLMCall, RequestMetric
from tests.fakes import FakeChatModel


def _ask(client: TestClient, headers: dict[str, str], query: str) -> dict[str, Any]:
    response = client.post("/api/query", json={"query": query}, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


@pytest.mark.parametrize(
    "path", ["/api/metrics/summary", "/api/metrics/timeseries", "/api/metrics/recent"]
)
def test_metrics_require_api_key(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401


def test_each_query_records_usage_cost_and_stage_latency(
    client: TestClient, auth_headers: dict[str, str], db: Session
) -> None:
    body = _ask(client, auth_headers, "List all companies")

    usage = body["usage"]
    # SQL generation, analysis, and the judge for the name-only summary claim.
    assert usage["llm_calls"] == 3
    assert usage["prompt_tokens"] > 0
    assert usage["cost_usd"] > 0
    assert usage["model"] == "openai/gpt-oss-120b"
    assert usage["llm_endpoint"] == "remote"
    assert {"retrieval", "sql_generation", "sql_execution", "analysis"} <= set(
        usage["stage_latency_ms"]
    )

    metric = db.scalars(select(RequestMetric)).one()
    assert metric.success is True
    assert metric.prompt_tokens == usage["prompt_tokens"]
    assert metric.retrieval_mode == "hybrid+rerank"
    assert metric.request_id is not None
    calls = db.scalars(select(LLMCall).order_by(LLMCall.id)).all()
    assert [c.purpose for c in calls] == ["sql_generation", "analysis", "verification"]
    assert sum(c.cost_usd for c in calls) == pytest.approx(metric.cost_usd)


def test_dashboard_endpoints_aggregate_requests(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeChatModel
) -> None:
    _ask(client, auth_headers, "List all companies")
    _ask(client, auth_headers, "List all companies again")
    fake_llm.sql = "DELETE FROM companies"
    _ask(client, auth_headers, "Delete everything")

    summary = client.get("/api/metrics/summary?window=1h", headers=auth_headers).json()
    assert (summary["requests"], summary["failures"]) == (3, 1)
    assert summary["error_rate"] == pytest.approx(1 / 3, abs=1e-3)
    assert summary["errors_by_type"] == {"UnsafeSQLError": 1}
    assert summary["top_failing_queries"][0]["query"] == "Delete everything"
    assert summary["latency_ms"]["p95"] is not None
    assert summary["tokens"]["total"] > 0
    assert summary["models"][0]["model"] == "openai/gpt-oss-120b"
    assert {p["purpose"] for p in summary["purposes"]} == {
        "sql_generation",
        "analysis",
        "verification",
    }

    series = client.get("/api/metrics/timeseries?window=1h", headers=auth_headers).json()
    assert series["bucket_seconds"] == 300
    assert sum(p["requests"] for p in series["points"]) == 3
    assert sum(p["failures"] for p in series["points"]) == 1

    recent = client.get("/api/metrics/recent?limit=2", headers=auth_headers).json()["requests"]
    assert [r["query"] for r in recent] == ["Delete everything", "List all companies again"]
    assert recent[0]["error_type"] == "UnsafeSQLError"
    assert recent[1]["stage_latency_ms"]["analysis"] >= 0


@pytest.mark.parametrize("query", ["window=2h", "window=", "limit=0"])
def test_metrics_validate_parameters(
    client: TestClient, auth_headers: dict[str, str], query: str
) -> None:
    path = "/api/metrics/recent" if query.startswith("limit") else "/api/metrics/summary"
    assert client.get(f"{path}?{query}", headers=auth_headers).status_code == 422
