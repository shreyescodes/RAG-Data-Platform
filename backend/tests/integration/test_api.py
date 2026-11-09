import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes import query as query_routes
from app.container import ServiceContainer
from app.core.config import get_settings
from app.core.exceptions import LLMNotConfiguredError
from app.db.models import QueryLog
from app.rag.sql_generator import CANNOT_ANSWER
from tests.fakes import FakeChatModel, FakeMarketData, sql_reply

PROTECTED = [
    ("get", "/api/history"),
    ("get", "/api/stats"),
    ("post", "/api/query"),
    ("post", "/api/index-schema"),
    ("get", "/api/health/llm"),
]


def _ask(client: TestClient, headers: dict[str, str], query: str) -> dict[str, Any]:
    response = client.post("/api/query", json={"query": query}, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# --- Public endpoints -------------------------------------------------------


def test_root(client: TestClient) -> None:
    body = client.get("/").json()
    assert body["name"] == "RAG Data Platform API"
    assert body["version"]


def test_health_reports_database_and_index(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "status": "healthy",
        "database": "connected",
        "vector_store_documents": body["vector_store_documents"],
        "llm_endpoint": "remote",
        "llm_configured": True,
    }
    assert body["vector_store_documents"] > 0


def test_responses_carry_security_and_request_id_headers(client: TestClient) -> None:
    response = client.get("/api/health", headers={"X-Request-ID": "trace-123"})
    assert response.headers["X-Request-ID"] == "trace-123"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"

    generated = client.get("/api/health").headers["X-Request-ID"]
    assert len(generated) == 32


# --- Authentication ---------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_protected_endpoints_require_api_key(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, path).status_code == 401
    wrong = client.request(method, path, headers={"X-API-Key": "wrong"})
    assert wrong.status_code == 401
    assert wrong.json() == {"detail": "Invalid or missing API key"}


# --- Query pipeline ---------------------------------------------------------


def test_query_success(client: TestClient, auth_headers: dict[str, str]) -> None:
    body = _ask(client, auth_headers, "List all companies")

    assert body["success"] is True
    assert body["sql"] == "SELECT name, ticker FROM companies ORDER BY name LIMIT 500"
    assert body["row_count"] == 3
    assert body["data"][0] == {"name": "Apple Inc.", "ticker": "AAPL"}
    assert body["answer"] == "There are three companies."
    assert body["agent_flow"] == {
        "retrieval": "completed",
        "enrichment": "skipped",
        "analysis": "completed",
        "verification": "completed",
    }
    assert "companies" in body["relevant_tables"]
    steps = [(s["agent"], s["step"]) for s in body["trace"]]
    assert ("retrieval", "sql_executed") in steps
    assert ("analysis", "analysis_completed") in steps


def test_query_cites_tables_columns_and_scores(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    body = _ask(client, auth_headers, "List all companies")

    citations = body["citations"]
    assert citations["sql"] == body["sql"]
    assert citations["retrieval_mode"] == "hybrid+rerank"
    companies = next(t for t in citations["tables"] if t["table"] == "companies")
    assert companies["used_in_sql"] is True
    assert companies["rerank_score"] is not None
    assert citations["output_columns"] == [
        {"output_column": "name", "sources": ["companies.name"], "derivation": "column"},
        {"output_column": "ticker", "sources": ["companies.ticker"], "derivation": "column"},
    ]
    assert citations["columns_referenced"] == ["companies.name", "companies.ticker"]
    assert citations["key_columns"] == ["name", "ticker"]
    assert citations["row_count"] == 3

    step = next(s for s in body["trace"] if s["step"] == "schema_retrieved")
    candidate = step["detail"]["candidates"][0]
    assert {"dense_score", "sparse_score", "fused_rank", "rerank_score"} <= set(candidate)


def test_failed_query_has_no_citations(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeChatModel
) -> None:
    fake_llm.sql = "DELETE FROM companies"
    assert _ask(client, auth_headers, "Delete everything please")["citations"] is None


def test_invalid_structured_reply_is_retried_and_traced(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeChatModel
) -> None:
    fake_llm.replies["sql_generation"] = ["SELECT name FROM companies"]  # not JSON

    body = _ask(client, auth_headers, "List all companies")

    assert body["success"] is True
    steps = {s["step"]: s["detail"] for s in body["trace"]}
    assert steps["sql_attempt_rejected"]["attempt"] == 1
    assert steps["sql_generated"]["attempts"] == 2
    assert steps["sql_generated"]["explanation"] == "Scripted by the test."
    assert body["citations"]["generation_confidence"] == 0.9
    assert body["citations"]["sql_explanation"] == "Scripted by the test."


def test_failed_sql_is_repaired_with_the_database_error(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeChatModel
) -> None:
    fake_llm.replies["sql_generation"] = [sql_reply("SELECT nam FROM companies")]

    body = _ask(client, auth_headers, "List all companies")

    assert body["success"] is True
    assert body["row_count"] == 3
    steps = [s["step"] for s in body["trace"]]
    assert steps.index("sql_failed") < steps.index("sql_repaired") < steps.index("sql_executed")
    repair_prompt = fake_llm.calls_for("sql_repair")[0]["user"]
    assert "SELECT nam FROM companies LIMIT 500" in repair_prompt
    assert "nam" in repair_prompt.split("Error:", 1)[1]


def test_persistently_invalid_output_fails_cleanly(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeChatModel, db: Session
) -> None:
    fake_llm.replies["sql_generation"] = ["no", "still no", "nope"]

    body = _ask(client, auth_headers, "List all companies")

    assert body["success"] is False
    assert "did not return a valid structured response" in body["error"]
    rejected = [s for s in body["trace"] if s["step"] == "sql_attempt_rejected"]
    assert len(rejected) == 3
    log = db.scalars(select(QueryLog)).one()
    assert "no valid SQLGenerationOutput after 3 attempts" in (log.error_message or "")


def test_hallucinated_claims_are_flagged(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeChatModel
) -> None:
    fake_llm.sql = (
        "SELECT c.name, f.revenue FROM companies c "
        "JOIN financial_statements f ON f.company_id = c.id"
    )
    fake_llm.analysis = {
        "answer": "Apple Inc. reported revenue of $94.0B.",
        "summary": "Microsoft Corporation reported $120B, the highest of the group.",
        "insights": [],
    }

    body = _ask(client, auth_headers, "Revenue by company")

    assert body["success"] is True
    report = body["verification"]
    assert report["status"] == "flagged"
    assert report["mode"] == "hybrid"
    supported, flagged = report["claims"]
    assert supported["verdict"] == "supported"
    assert supported["evidence"][0] == {
        "id": "row:0",
        "kind": "row",
        "label": "Row 1 · name: Apple Inc., revenue: 94,000,000,000",
        "row_index": 0,
        "column": None,
        "value": None,
    }
    assert flagged["verdict"] == "unsupported"
    assert flagged["unsupported_values"] == ["$120B"]
    assert body["agent_flow"]["verification"] == "completed"
    # The judge was consulted only for the claim the checks could not clear.
    (judge_call,) = fake_llm.calls_for("verification")
    assert "[c2]" in judge_call["user"]
    assert "[c1]" not in judge_call["user"]


def test_verification_crash_never_fails_the_answer(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("checker bug")

    monkeypatch.setattr("app.agents.verification.check_claim", boom)
    body = _ask(client, auth_headers, "List all companies")
    assert body["success"] is True
    assert body["verification"] is None
    assert body["agent_flow"]["verification"] == "failed"


def test_query_redacts_pii_before_llm_and_audit(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeChatModel, db: Session
) -> None:
    body = _ask(client, auth_headers, "Companies for jane@example.com, SSN 123-45-6789")

    assert body["query"] == "Companies for [EMAIL], SSN [SSN]"
    assert all("jane@example.com" not in call["user"] for call in fake_llm.calls)
    logged = db.scalars(select(QueryLog)).one()
    assert logged.user_query == "Companies for [EMAIL], SSN [SSN]"
    assert body["trace"][0]["step"] == "pii_redacted"


def test_unsafe_sql_is_rejected(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeChatModel, db: Session
) -> None:
    fake_llm.sql = "DELETE FROM companies"
    body = _ask(client, auth_headers, "Delete everything please")

    assert body["success"] is False
    assert body["error"] == "The generated query was rejected by the SQL safety checks."
    assert body["agent_flow"]["retrieval"] == "failed"
    log = db.scalars(select(QueryLog)).one()
    assert log.success is False
    assert log.generated_sql == "DELETE FROM companies"
    # The companies table is untouched.
    fake_llm.sql = "SELECT name FROM companies"
    assert _ask(client, auth_headers, "List all companies")["row_count"] == 3


def test_query_logs_table_is_not_queryable(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeChatModel
) -> None:
    fake_llm.sql = "SELECT user_query FROM query_logs"
    body = _ask(client, auth_headers, "Show other users' questions")
    assert body["success"] is False


def test_unanswerable_question(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeChatModel
) -> None:
    fake_llm.sql = CANNOT_ANSWER
    body = _ask(client, auth_headers, "What is the weather in Paris?")
    assert body["success"] is False
    assert "cannot be answered" in body["error"]


def test_sql_runtime_error_is_reported_cleanly(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeChatModel
) -> None:
    fake_llm.sql = "SELECT no_such_column FROM companies"
    body = _ask(client, auth_headers, "Show the missing column")
    assert body["success"] is False
    assert body["error"] == "The generated query failed to execute against the database."
    assert "no_such_column" in body["sql"]


def test_llm_not_configured(
    client: TestClient, auth_headers: dict[str, str], fake_llm: FakeChatModel
) -> None:
    fake_llm.fail_with = LLMNotConfiguredError()
    body = _ask(client, auth_headers, "List all companies")
    assert body["success"] is False
    assert body["error"] == "No LLM API key is configured on the server."


def test_query_validation(client: TestClient, auth_headers: dict[str, str]) -> None:
    assert client.post("/api/query", json={"query": " a "}, headers=auth_headers).status_code == 422
    too_long = {"query": "x" * 1001}
    assert client.post("/api/query", json=too_long, headers=auth_headers).status_code == 422


def test_query_rate_limit(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tight = get_settings().model_copy(update={"rate_limit_query": "2/minute"})
    monkeypatch.setattr(query_routes, "get_settings", lambda: tight)

    codes = [
        client.post(
            "/api/query", json={"query": "List companies"}, headers=auth_headers
        ).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


# --- History, stats, admin --------------------------------------------------


def test_history_lists_recent_queries_first(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    for q in ("first question", "second question", "third question"):
        _ask(client, auth_headers, q)

    body = client.get("/api/history?limit=2", headers=auth_headers).json()
    assert body["total"] == 3
    assert [h["query"] for h in body["history"]] == ["third question", "second question"]
    assert body["history"][0]["success"] is True

    page_two = client.get("/api/history?limit=2&offset=2", headers=auth_headers).json()
    assert [h["query"] for h in page_two["history"]] == ["first question"]


@pytest.mark.parametrize("params", ["limit=0", "limit=101", "offset=-1"])
def test_history_validates_pagination(
    client: TestClient, auth_headers: dict[str, str], params: str
) -> None:
    assert client.get(f"/api/history?{params}", headers=auth_headers).status_code == 422


def test_stats(client: TestClient, auth_headers: dict[str, str], fake_llm: FakeChatModel) -> None:
    _ask(client, auth_headers, "List all companies")
    fake_llm.sql = "DROP TABLE companies"
    _ask(client, auth_headers, "Drop it")

    body = client.get("/api/stats", headers=auth_headers).json()
    assert body["queries"] == {"total": 2, "successful": 1, "success_rate": 50.0}
    assert body["database"]["companies"] == 3
    assert body["database"]["fund_holdings"] == 1
    assert body["vector_store"]["total_documents"] > 0


def test_index_schema(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post("/api/index-schema", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["documents_indexed"] > 0
    assert "query_logs" not in body["tables"]


def test_audit_log_stores_trace_and_sample(
    client: TestClient, auth_headers: dict[str, str], db: Session
) -> None:
    _ask(client, auth_headers, "List all companies")
    log = db.scalars(select(QueryLog)).one()
    assert json.loads(log.sql_result or "[]")[0]["ticker"] == "AAPL"
    assert any(step["step"] == "sql_executed" for step in json.loads(log.agent_reasoning or "[]"))


# --- Live-data fallback ------------------------------------------------------


def test_unanswerable_from_db_falls_back_to_live_data(
    client: TestClient,
    auth_headers: dict[str, str],
    fake_llm: FakeChatModel,
    services: ServiceContainer,
) -> None:
    # Market cap is not stored, so SQL generation refuses; Yahoo can answer it.
    fake_llm.sql = CANNOT_ANSWER
    fake_llm.analysis = {"answer": "AAPL trades at $251.30.", "summary": "", "insights": []}
    services.market_data = FakeMarketData(
        quotes={"AAPL": {"ticker": "AAPL", "current_price": 251.3, "market_cap": 3.8e12}}
    )

    body = _ask(client, auth_headers, "What is AAPL's current stock price and market cap?")

    assert body["success"] is True
    assert body["sql"] is None
    assert body["row_count"] == 0
    assert body["answer"] == "AAPL trades at $251.30."
    assert body["enriched_data"]["market_data"][0]["market_cap"] == 3.8e12
    assert body["agent_flow"] == {
        "retrieval": "skipped",
        "enrichment": "completed",
        "analysis": "completed",
        "verification": "completed",
    }
    assert body["verification"]["status"] == "verified"
    assert body["verification"]["claims"][0]["evidence"][0]["id"] == "market:AAPL"
    assert ("orchestrator", "fallback_to_live_data") in [
        (s["agent"], s["step"]) for s in body["trace"]
    ]
    assert "Live data:" in fake_llm.calls[-1]["user"]


def test_live_data_fallback_still_fails_without_data(
    client: TestClient,
    auth_headers: dict[str, str],
    fake_llm: FakeChatModel,
    services: ServiceContainer,
) -> None:
    fake_llm.sql = CANNOT_ANSWER
    services.market_data = FakeMarketData()  # Yahoo has nothing for the ticker

    body = _ask(client, auth_headers, "What is AAPL's current stock price and market cap?")

    assert body["success"] is False
    assert "cannot be answered" in body["error"]
