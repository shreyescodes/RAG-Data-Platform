import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.retrieval import asks_dataset_size
from app.core.config import Settings, get_settings
from app.core.exceptions import LLMRateLimitError
from tests.fakes import FakeChatModel

VISITOR = "visitor-0123456789abcdef"
OTHER_VISITOR = "visitor-fedcba9876543210"
CONVERSATION = "conversation-1"


@pytest.fixture
def visitor(auth_headers: dict[str, str]) -> dict[str, str]:
    return {**auth_headers, "X-Visitor-Id": VISITOR}


@pytest.fixture
def other(auth_headers: dict[str, str]) -> dict[str, str]:
    return {**auth_headers, "X-Visitor-Id": OTHER_VISITOR}


def _ask(client: TestClient, headers: dict[str, str], query: str) -> dict[str, Any]:
    response = client.post(
        "/api/query", json={"query": query, "conversation_id": CONVERSATION}, headers=headers
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _override(app: FastAPI, **values: Any) -> None:
    settings: Settings = get_settings().model_copy(update=values)
    app.dependency_overrides[get_settings] = lambda: settings


def test_history_only_shows_the_visitors_own_questions(
    client: TestClient, visitor: dict[str, str], other: dict[str, str], auth_headers: dict[str, str]
) -> None:
    _ask(client, visitor, "mine alone")
    _ask(client, other, "somebody else's question")

    body = client.get("/api/history", headers=visitor).json()

    assert [item["query"] for item in body["history"]] == ["mine alone"]
    assert body["total"] == 1
    assert body["history"][0]["conversation_id"] == CONVERSATION
    assert client.get("/api/history", headers=auth_headers).json()["history"] == []


def test_malformed_visitor_ids_see_nothing(
    client: TestClient, visitor: dict[str, str], auth_headers: dict[str, str]
) -> None:
    _ask(client, visitor, "mine alone")
    headers = {**auth_headers, "X-Visitor-Id": "../../etc/passwd"}
    assert client.get("/api/history", headers=headers).json()["history"] == []


def test_a_saved_conversation_reopens_without_calling_the_llm(
    client: TestClient, visitor: dict[str, str], fake_llm: FakeChatModel
) -> None:
    first = _ask(client, visitor, "List all companies")
    calls = len(fake_llm.calls)

    response = client.get(f"/api/conversations/{CONVERSATION}", headers=visitor)

    assert response.status_code == 200
    turns = response.json()["turns"]
    assert [turn["answer"] for turn in turns] == [first["answer"]]
    assert turns[0]["data"] == first["data"]
    assert turns[0]["usage"]["llm_calls"] > 0
    assert len(fake_llm.calls) == calls


def test_a_conversation_is_private_to_its_visitor(
    client: TestClient, visitor: dict[str, str], other: dict[str, str]
) -> None:
    _ask(client, visitor, "List all companies")

    assert client.get(f"/api/conversations/{CONVERSATION}", headers=other).status_code == 404
    assert client.get("/api/conversations/unknown-id", headers=visitor).status_code == 404


def test_follow_ups_see_the_earlier_turns(
    client: TestClient, visitor: dict[str, str], fake_llm: FakeChatModel
) -> None:
    _ask(client, visitor, "Show Apple revenue")
    fake_llm.calls.clear()

    _ask(client, visitor, "What about its net income?")

    prompts = {call["purpose"]: call["user"] for call in fake_llm.calls}
    assert "Q: Show Apple revenue" in prompts["sql_generation"]
    assert "A: There are three companies." in prompts["analysis"]


def test_separate_conversations_do_not_share_context(
    client: TestClient, visitor: dict[str, str], fake_llm: FakeChatModel
) -> None:
    _ask(client, visitor, "Show Apple revenue")
    fake_llm.calls.clear()

    client.post(
        "/api/query",
        json={"query": "Show Microsoft revenue", "conversation_id": "conversation-2"},
        headers=visitor,
    )

    assert all("Show Apple revenue" not in call["user"] for call in fake_llm.calls)


def test_stream_reports_each_stage_then_the_answer(
    client: TestClient, visitor: dict[str, str]
) -> None:
    response = client.post(
        "/api/query/stream",
        json={"query": "List all companies", "conversation_id": CONVERSATION},
        headers=visitor,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [
        (lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: ")))
        for chunk in response.text.strip().split("\n\n")
        if (lines := chunk.split("\n"))
    ]
    stages = [data["stage"] for name, data in events if name == "stage"]
    assert stages[:2] == ["retrieval", "retrieval"]
    assert "analysis" in stages
    assert events[-1][0] == "result"
    assert events[-1][1]["success"] is True
    assert events[-1][1]["conversation_id"] == CONVERSATION


def test_stream_requires_the_api_key(client: TestClient) -> None:
    assert client.post("/api/query/stream", json={"query": "hello"}).status_code == 401


def test_daily_limit_per_visitor(app: FastAPI, client: TestClient, visitor: dict[str, str]) -> None:
    _override(app, daily_visitor_query_limit=1)
    _ask(client, visitor, "List all companies")

    response = client.post("/api/query", json={"query": "One more"}, headers=visitor)

    assert response.status_code == 429
    assert "come back tomorrow" in response.json()["detail"]
    app.dependency_overrides.clear()


def test_daily_limit_for_everyone(
    app: FastAPI, client: TestClient, visitor: dict[str, str], other: dict[str, str]
) -> None:
    _override(app, daily_query_limit=1)
    _ask(client, visitor, "List all companies")

    response = client.post("/api/query/stream", json={"query": "One more"}, headers=other)

    assert response.status_code == 429
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "question",
    [
        "How many companies are in the database?",
        "How many rows are stored in the fund_holdings table?",
        "how many funds do you have",
        "What is the size of the dataset?",
        "How big is your database?",
        "Show me the row counts",
    ],
)
def test_dataset_size_questions_are_recognised(question: str) -> None:
    assert asks_dataset_size(question)


@pytest.mark.parametrize(
    "question",
    [
        "How many funds held NVIDIA in the most recent quarter?",
        "How many positions did Berkshire Hathaway report in its latest filing?",
        "How many shares of Apple did Soros hold?",
        "What was Apple's revenue?",
    ],
)
def test_ordinary_counting_questions_are_allowed(question: str) -> None:
    assert not asks_dataset_size(question)


def test_dataset_size_questions_are_refused_before_the_llm(
    client: TestClient, visitor: dict[str, str], fake_llm: FakeChatModel
) -> None:
    body = _ask(client, visitor, "How many companies are in the database?")

    assert body["success"] is False
    assert "size of the dataset" in body["error"]
    assert fake_llm.calls == []


def test_sql_counting_a_whole_table_is_rejected(
    client: TestClient, visitor: dict[str, str], fake_llm: FakeChatModel
) -> None:
    fake_llm.sql = "SELECT count(*) FROM companies"

    body = _ask(client, visitor, "Total listings please")

    assert body["success"] is False
    assert body["data"] == []


def test_rate_limits_reach_the_user_as_a_clear_message(
    client: TestClient, visitor: dict[str, str], fake_llm: FakeChatModel
) -> None:
    fake_llm.fail_with = LLMRateLimitError("429", retry_after_seconds=540)

    body = _ask(client, visitor, "List all companies")

    assert body["success"] is False
    assert body["error"].endswith("try again in about 9 minutes.")


@pytest.mark.parametrize("show", [True, False])
def test_metrics_can_hide_question_text(
    app: FastAPI, client: TestClient, visitor: dict[str, str], show: bool
) -> None:
    _override(app, metrics_show_queries=show)
    fake = "List all companies"
    _ask(client, visitor, fake)

    recent = client.get("/api/metrics/recent", headers=visitor).json()["requests"]
    summary = client.get("/api/metrics/summary", headers=visitor).json()

    expected = fake if show else "Hidden"
    assert recent[0]["query"] == expected
    assert summary["most_expensive_queries"][0]["query"] == expected
    app.dependency_overrides.clear()
