"""Schema-validated LLM output with feedback-driven retries.

`StructuredOutputExtractor.extract(Model, ...)` asks the model for JSON that
conforms to a Pydantic model, validates it, optionally applies a semantic
check (e.g. "the SQL must pass the safety validator"), and on any failure
retries with the errors fed back to the model, up to `max_attempts` times.

Three layers keep the output well-formed, strongest first:

1. `json_schema` mode: the server constrains decoding to the schema
   (OpenAI, vLLM, Ollama, llama.cpp support it);
2. `json_object` mode: the server guarantees syntactically valid JSON;
3. the schema is always embedded in the prompt, and replies are parsed
   leniently (code fences, `<think>` blocks and surrounding prose are
   stripped), so plain-text endpoints work too.

Transport failures (`LLMError`) are not retried here: the HTTP client already
retries those with backoff. The exception is `InvalidJSONReplyError`, a server
that rejected the model's reply as invalid JSON: that is a bad reply, so it is
retried with feedback like any other.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.exceptions import LLMError
from app.observability.metrics import LLMCallRecord, estimate_tokens, record_llm_call
from app.services.cache import ResponseCache, stable_key
from app.services.llm import ChatModel, InvalidJSONReplyError

T = TypeVar("T", bound=BaseModel)

StructuredMode = Literal["json_schema", "json_object", "prompt"]
CacheKind = Literal["exact", "semantic"]

DEFAULT_MAX_ATTEMPTS = 3
# How much of a rejected reply is echoed back to the model.
_FEEDBACK_EXCERPT_CHARS = 1_500
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class OutputRejected(ValueError):
    """Raised by a semantic validator to reject a schema-valid value and retry."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause


@dataclass(frozen=True, slots=True)
class Attempt:
    number: int
    ok: bool
    errors: tuple[str, ...] = ()
    excerpt: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"attempt": self.number, "ok": self.ok, "errors": list(self.errors)}


@dataclass(frozen=True, slots=True)
class Extraction(Generic[T]):
    value: T
    raw: str
    attempts: tuple[Attempt, ...]
    cached: CacheKind | None = None

    @property
    def retries(self) -> int:
        return len(self.attempts) - 1


class StructuredOutputError(LLMError):
    user_message = (
        "The language model did not return a valid structured response after "
        "several attempts. Please rephrase the question or try again."
    )

    def __init__(
        self,
        detail: str,
        *,
        attempts: tuple[Attempt, ...],
        last_raw: str | None = None,
        last_value: BaseModel | None = None,
        last_rejection: OutputRejected | None = None,
    ) -> None:
        super().__init__(detail)
        self.attempts = attempts
        self.last_raw = last_raw
        # Set when the final reply was schema-valid but semantically rejected.
        self.last_value = last_value
        self.last_rejection = last_rejection


def extract_json_text(completion: str) -> str:
    """The JSON object inside a completion, tolerating fences, prose and think blocks."""
    text = _THINK_BLOCK.sub("", completion).strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    if text.startswith("{"):
        return text
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else text


def _strip_titles(node: Any) -> Any:
    """Drop Pydantic's auto-generated `title` keys: tokens with no information."""
    if isinstance(node, dict):
        return {
            k: _strip_titles(v)
            for k, v in node.items()
            if not (k == "title" and isinstance(v, str))
        }
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


def json_schema_for(model: type[BaseModel]) -> dict[str, Any]:
    schema: dict[str, Any] = _strip_titles(model.model_json_schema())
    return schema


def _format_validation_error(exc: ValidationError) -> list[str]:
    messages = []
    for err in exc.errors(include_url=False):
        location = ".".join(str(part) for part in err["loc"]) or "(root)"
        messages.append(f"{location}: {err['msg']}")
    return messages


class StructuredOutputExtractor:
    def __init__(
        self,
        chat_model: ChatModel,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        mode: StructuredMode = "json_object",
        cache: ResponseCache | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._chat = chat_model
        self.max_attempts = max_attempts
        self.mode = mode
        self._cache = cache

    @property
    def model(self) -> str:
        return str(getattr(self._chat, "model", ""))

    async def extract(
        self,
        schema: type[T],
        *,
        system: str,
        user: str,
        purpose: str,
        temperature: float = 0.0,
        max_tokens: int = 1_000,
        validate: Callable[[T], None] | None = None,
    ) -> Extraction[T]:
        """Return a validated `schema` instance or raise `StructuredOutputError`."""
        json_schema = json_schema_for(schema)
        instructions = (
            f"{system}\n\nRespond with a single JSON object that conforms to this JSON "
            f"Schema, with no prose and no markdown:\n{json.dumps(json_schema)}"
        )
        response_schema: Mapping[str, Any] | None = (
            {"name": schema.__name__, "schema": json_schema} if self.mode == "json_schema" else None
        )

        cache_key = stable_key(
            self.model, schema.__name__, self.mode, instructions, user, temperature, max_tokens
        )
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                hit = self.replay(schema, cached, validate, purpose=purpose, prompt=user)
                if hit is not None:
                    return hit

        attempts: list[Attempt] = []
        prompt = user
        raw = ""
        value: T | None = None
        rejection: OutputRejected | None = None
        for number in range(1, self.max_attempts + 1):
            value, rejection = None, None
            try:
                raw = await self._chat.complete(
                    system=instructions,
                    user=prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=self.mode != "prompt",
                    json_schema=response_schema,
                    purpose=purpose,
                )
            except InvalidJSONReplyError as exc:
                # The server rejected the reply itself (Groq: json_validate_failed).
                raw = exc.failed_generation
                errors = ["the reply was not valid JSON"]
                attempts.append(
                    Attempt(number=number, ok=False, errors=tuple(errors), excerpt=raw[:200])
                )
                prompt = self._feedback(user, raw, errors)
                continue
            try:
                value = schema.model_validate_json(extract_json_text(raw))
                if validate is not None:
                    validate(value)
            except ValidationError as exc:
                errors = _format_validation_error(exc)
            except OutputRejected as exc:
                errors, rejection = [str(exc)], exc
            else:
                attempts.append(Attempt(number=number, ok=True))
                if self._cache is not None:
                    self._cache.put(cache_key, raw)
                return Extraction(value=value, raw=raw, attempts=tuple(attempts))

            attempts.append(
                Attempt(number=number, ok=False, errors=tuple(errors), excerpt=raw[:200])
            )
            prompt = self._feedback(user, raw, errors)

        raise StructuredOutputError(
            f"no valid {schema.__name__} after {self.max_attempts} attempts: "
            + "; ".join(attempts[-1].errors),
            attempts=tuple(attempts),
            last_raw=raw,
            last_value=value,
            last_rejection=rejection,
        )

    def replay(
        self,
        schema: type[T],
        raw: str,
        validate: Callable[[T], None] | None,
        *,
        purpose: str,
        prompt: str,
        kind: CacheKind = "exact",
    ) -> Extraction[T] | None:
        """Re-validate a cached reply; None if it no longer passes."""
        try:
            value = schema.model_validate_json(extract_json_text(raw))
            if validate is not None:
                validate(value)
        except (ValidationError, OutputRejected):
            return None
        record_llm_call(
            LLMCallRecord(
                purpose=purpose,
                model=self.model,
                prompt_tokens=estimate_tokens(prompt),
                completion_tokens=estimate_tokens(raw),
                latency_ms=0.0,
                cached=True,
                estimated=True,
            )
        )
        return Extraction(value=value, raw=raw, attempts=(Attempt(1, ok=True),), cached=kind)

    @staticmethod
    def _feedback(user: str, raw: str, errors: list[str]) -> str:
        bullet_list = "\n".join(f"- {e}" for e in errors)
        excerpt = raw[:_FEEDBACK_EXCERPT_CHARS]
        return (
            f"{user}\n\nYour previous reply was rejected:\n{bullet_list}\n\n"
            f"Previous reply:\n{excerpt}\n\n"
            "Reply again with only a corrected JSON object."
        )
