from types import SimpleNamespace
from typing import Any

import openai
import pytest

from app.core.exceptions import LLMError, LLMNotConfiguredError
from app.observability.metrics import track_request
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
    usage: SimpleNamespace | None = None,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def create(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        if error is not None:
            raise error
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)

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


async def test_json_schema_requests_constrained_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _model()
    calls = _stub_create(monkeypatch, model, content="{}")
    schema = {"name": "Out", "schema": {"type": "object"}}
    await model.complete(system="s", user="u", json_schema=schema, purpose="test")
    assert calls[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "Out", "schema": {"type": "object"}, "strict": False},
    }


def test_local_endpoints_need_no_key() -> None:
    local = OpenAICompatibleChatModel(
        api_key="",
        base_url="http://localhost:11434/v1",
        model="m",
        timeout_seconds=5,
        max_retries=0,
    )
    remote = _model(api_key="")
    assert (local.endpoint, local.configured) == ("local", True)
    assert (remote.endpoint, remote.configured) == ("remote", False)


async def test_usage_is_recorded_and_estimated_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model()
    _stub_create(
        monkeypatch,
        model,
        content="x" * 40,
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
    )
    with track_request() as metrics:
        await model.complete(system="s", user="u", purpose="analysis")
    (call,) = metrics.llm_calls
    assert (call.purpose, call.prompt_tokens, call.completion_tokens) == ("analysis", 11, 7)
    assert call.estimated is False

    _stub_create(monkeypatch, model, content="x" * 40)
    with track_request() as metrics:
        await model.complete(system="s" * 8, user="u" * 8)
    assert metrics.llm_calls[0].completion_tokens == 10
    assert metrics.llm_calls[0].estimated is True


async def test_failed_calls_are_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _model()
    _stub_create(monkeypatch, model, error=openai.OpenAIError("boom"))
    with track_request() as metrics, pytest.raises(LLMError):
        await model.complete(system="s", user="u")
    assert metrics.llm_calls[0].success is False


async def test_probe_lists_models(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _model()
    assert model._client is not None

    class Models:
        async def list(self) -> SimpleNamespace:
            return SimpleNamespace(data=[SimpleNamespace(id="test-model"), SimpleNamespace(id="x")])

    monkeypatch.setattr(model._client, "with_options", lambda **_: SimpleNamespace(models=Models()))
    result = await model.probe()
    assert (result.reachable, result.model_available) == (True, True)
    assert result.models == ["test-model", "x"]


async def test_probe_reports_unreachable_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _model()
    assert model._client is not None

    class Models:
        async def list(self) -> None:
            raise openai.OpenAIError("connection refused")

    monkeypatch.setattr(model._client, "with_options", lambda **_: SimpleNamespace(models=Models()))
    result = await model.probe()
    assert (result.reachable, result.error) == (False, "OpenAIError")
    assert (await _model(api_key="").probe()).error == "not configured"
