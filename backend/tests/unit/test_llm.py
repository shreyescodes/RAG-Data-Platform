from types import SimpleNamespace
from typing import Any

import openai
import pytest

from app.core.exceptions import LLMError, LLMNotConfiguredError
from app.services.llm import OpenAICompatibleChatModel


def _model(api_key: str = "k") -> OpenAICompatibleChatModel:
    return OpenAICompatibleChatModel(
        api_key=api_key,
        base_url="https://llm.test/v1",
        model="test-model",
        timeout_seconds=5,
        max_retries=0,
    )


def _stub_create(
    monkeypatch: pytest.MonkeyPatch,
    model: OpenAICompatibleChatModel,
    *,
    content: str | None = "ok",
    error: Exception | None = None,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def create(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        if error is not None:
            raise error
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    assert model._client is not None
    monkeypatch.setattr(model._client.chat.completions, "create", create)
    return calls


async def test_sends_prompt_and_returns_content(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _model()
    calls = _stub_create(monkeypatch, model, content="SELECT 1")

    result = await model.complete(system="sys", user="usr", json_mode=True, max_tokens=50)

    assert result == "SELECT 1"
    sent = calls[0]
    assert sent["model"] == "test-model"
    assert sent["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["max_tokens"] == 50
    await model.aclose()


async def test_omits_response_format_without_json_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _model()
    calls = _stub_create(monkeypatch, model)
    await model.complete(system="s", user="u")
    assert calls[0]["response_format"] is openai.omit


async def test_sdk_errors_become_llm_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _model()
    _stub_create(monkeypatch, model, error=openai.OpenAIError("rate limited"))
    with pytest.raises(LLMError, match="rate limited"):
        await model.complete(system="s", user="u")


async def test_empty_completion_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _model()
    _stub_create(monkeypatch, model, content=None)
    with pytest.raises(LLMError, match="empty"):
        await model.complete(system="s", user="u")


async def test_missing_api_key() -> None:
    model = _model(api_key="")
    with pytest.raises(LLMNotConfiguredError):
        await model.complete(system="s", user="u")
    await model.aclose()  # no-op without a client
