from typing import Any

from fastapi.testclient import TestClient

from app.container import ServiceContainer
from app.services.cache import ResponseCache, SemanticCache
from app.services.llm import LLMProbe
from tests.fakes import FakeChatModel, HashingEmbedder


def _ask(client: TestClient, headers: dict[str, str], query: str) -> dict[str, Any]:
    response = client.post("/api/query", json={"query": query}, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_llm_health_reports_endpoint_probe_and_caches(
    client: TestClient,
    auth_headers: dict[str, str],
    services: ServiceContainer,
    fake_llm: FakeChatModel,
) -> None:
    async def probe() -> LLMProbe:
        return LLMProbe(reachable=True, latency_ms=3.2, model_available=False, models=["other"])

    fake_llm.probe = probe  # type: ignore[attr-defined]
    services.response_cache = ResponseCache()

    body = client.get("/api/health/llm", headers=auth_headers).json()

    assert body["endpoint"] == "remote"
    assert body["host"] == "api.groq.com"
    assert body["reachable"] is True
    assert body["model_available"] is False
    assert body["retrieval_mode"] == "hybrid+rerank"
    assert body["verification_mode"] == "hybrid"
    assert body["caches"]["response"]["enabled"] is True
    assert body["caches"]["semantic"] == {"enabled": False}


def test_llm_health_without_a_probe(client: TestClient, auth_headers: dict[str, str]) -> None:
    body = client.get("/api/health/llm", headers=auth_headers).json()
    assert body["reachable"] is None
    assert body["configured"] is True


def test_repeated_and_similar_questions_hit_the_caches(
    client: TestClient,
    auth_headers: dict[str, str],
    services: ServiceContainer,
    fake_llm: FakeChatModel,
) -> None:
    services.response_cache = ResponseCache()
    services.semantic_cache = SemanticCache(HashingEmbedder(), threshold=0.8)

    first = _ask(client, auth_headers, "List all companies")
    calls_after_first = len(fake_llm.calls)
    again = _ask(client, auth_headers, "List all companies")

    assert first["usage"]["cache_hits"] == 0
    # Identical question: every LLM step is replayed from the caches.
    assert again["usage"]["cache_hits"] == again["usage"]["llm_calls"] == 3
    assert again["usage"]["cost_usd"] == 0
    assert len(fake_llm.calls) == calls_after_first

    # Same retrieved schema as the first question, so the same cache scope.
    similar = _ask(client, auth_headers, "please list all companies")
    # Similar question: the SQL is reused; the analysis is fresh text, so new calls.
    generated = next(s for s in similar["trace"] if s["step"] == "sql_generated")["detail"]
    assert generated["cache"] == "semantic"
    assert generated["cache_source"] == "List all companies"
    assert similar["data"] == first["data"]  # re-executed against the database

    summary = client.get("/api/metrics/summary?window=1h", headers=auth_headers).json()
    assert summary["cache_hits"] >= 4
    assert summary["cache_hit_rate"] > 0
