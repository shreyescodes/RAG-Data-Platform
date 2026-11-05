import json
from typing import Any

import pytest
from pydantic import BaseModel, Field

from app.core.exceptions import LLMError
from app.services.structured_output import (
    Extraction,
    OutputRejected,
    StructuredOutputError,
    StructuredOutputExtractor,
    extract_json_text,
    json_schema_for,
)
from tests.fakes import FakeChatModel


class Summary(BaseModel):
    headline: str = Field(min_length=3)
    score: int = Field(ge=0, le=10)


def _llm(*replies: str) -> FakeChatModel:
    return FakeChatModel(replies={"test": list(replies)})


async def _extract(llm: FakeChatModel, **kwargs: Any) -> Extraction[Summary]:
    return await StructuredOutputExtractor(llm, **kwargs).extract(
        Summary, system="Summarise.", user="Data: 1", purpose="test"
    )


@pytest.mark.parametrize(
    "completion",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        'Here you go: {"a": 1} hope that helps',
        '<think>reasoning {not json}</think>\n{"a": 1}',
    ],
)
def test_extract_json_text_tolerates_wrappers(completion: str) -> None:
    assert json.loads(extract_json_text(completion)) == {"a": 1}


def test_schema_drops_generated_titles() -> None:
    schema = json_schema_for(Summary)
    assert "title" not in schema
    assert "title" not in schema["properties"]["headline"]
    assert schema["required"] == ["headline", "score"]


async def test_valid_first_reply() -> None:
    llm = _llm('{"headline": "All good", "score": 7}')
    result = await _extract(llm)
    assert result.value == Summary(headline="All good", score=7)
    assert result.retries == 0
    call = llm.calls[0]
    assert '"headline"' in call["system"]
    assert call["json_mode"] is True
    assert call["json_schema"] is None


async def test_retries_until_valid_and_reports_each_error() -> None:
    llm = _llm("not json", '{"headline": "ok", "score": 11}', '{"headline": "Fine", "score": 3}')

    result = await _extract(llm)

    assert result.value.score == 3
    assert [a.ok for a in result.attempts] == [False, False, True]
    assert result.attempts[1].errors == (
        "headline: String should have at least 3 characters",
        "score: Input should be less than or equal to 10",
    )
    assert "score: Input should be less than or equal to 10" in llm.calls[2]["user"]


async def test_gives_up_after_max_attempts() -> None:
    llm = _llm("x", "y")
    with pytest.raises(StructuredOutputError) as info:
        await _extract(llm, max_attempts=2)
    assert len(info.value.attempts) == 2
    assert info.value.last_raw == "y"
    assert info.value.last_value is None
    assert "no valid Summary after 2 attempts" in str(info.value)


async def test_semantic_validator_rejections_are_retried() -> None:
    llm = _llm('{"headline": "Bad news", "score": 1}', '{"headline": "Good news", "score": 9}')

    def no_bad_news(value: Summary) -> None:
        if "Bad" in value.headline:
            raise OutputRejected("headline must be upbeat")

    result = await StructuredOutputExtractor(llm).extract(
        Summary, system="s", user="u", purpose="test", validate=no_bad_news
    )
    assert result.value.headline == "Good news"
    assert result.attempts[0].errors == ("headline must be upbeat",)


async def test_final_rejection_is_exposed() -> None:
    llm = _llm('{"headline": "Bad news", "score": 1}')
    cause = ValueError("root cause")

    def reject(value: Summary) -> None:
        raise OutputRejected("never", cause=cause)

    with pytest.raises(StructuredOutputError) as info:
        await StructuredOutputExtractor(llm, max_attempts=1).extract(
            Summary, system="s", user="u", purpose="test", validate=reject
        )
    assert info.value.last_value == Summary(headline="Bad news", score=1)
    assert info.value.last_rejection is not None
    assert info.value.last_rejection.cause is cause


async def test_json_schema_mode_requests_constrained_decoding() -> None:
    llm = _llm('{"headline": "Fine", "score": 3}')
    await _extract(llm, mode="json_schema")
    schema = llm.calls[0]["json_schema"]
    assert schema["name"] == "Summary"
    assert schema["schema"]["required"] == ["headline", "score"]


async def test_prompt_mode_sends_no_response_format() -> None:
    llm = _llm('{"headline": "Fine", "score": 3}')
    await _extract(llm, mode="prompt")
    assert llm.calls[0]["json_mode"] is False


async def test_transport_errors_are_not_retried() -> None:
    llm = FakeChatModel(fail_with=LLMError("down"))
    with pytest.raises(LLMError, match="down"):
        await _extract(llm)
    assert len(llm.calls) == 1


def test_max_attempts_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        StructuredOutputExtractor(FakeChatModel(), max_attempts=0)
