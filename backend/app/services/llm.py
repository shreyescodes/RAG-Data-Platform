"""Chat-completion client for any OpenAI-compatible endpoint.

Hosted APIs (Groq by default, OpenAI, ...) and self-hosted servers (Ollama,
vLLM, llama.cpp) speak the same protocol. A local endpoint needs no API key.
Every call reports its token usage and latency to the request's metrics.
"""

from __future__ import annotations

import ipaddress
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

import openai

from app.core.exceptions import LLMError, LLMNotConfiguredError
from app.observability.metrics import LLMCallRecord, estimate_tokens, record_llm_call

logger = logging.getLogger(__name__)

EndpointKind = Literal["local", "remote"]
# The OpenAI SDK insists on a key; self-hosted servers ignore it.
LOCAL_PLACEHOLDER_KEY = "not-needed"


def endpoint_kind(base_url: str) -> EndpointKind:
    """Whether `base_url` points at your own infrastructure or a hosted API.

    Local: loopback and private addresses, single-label hosts (Docker Compose
    service names such as `ollama`) and `.local` / `.internal` / `.lan` names.
    """
    host = (urlsplit(base_url).hostname or "").lower()
    if not host:
        return "remote"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        is_local_name = (
            host == "localhost"
            or "." not in host
            or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa"))
        )
        return "local" if is_local_name else "remote"
    return "local" if address.is_private or address.is_loopback else "remote"


class ChatModel(Protocol):
    async def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        json_mode: bool = False,
        json_schema: Mapping[str, Any] | None = None,
        purpose: str = "general",
    ) -> str:
        """Return the completion text.

        `json_schema` ({"name": ..., "schema": ...}) requests constrained
        decoding and implies `json_mode`. `purpose` labels the call for
        metrics and caching ("sql_generation", "analysis", ...).
        """
        ...


def response_format(
    *, json_mode: bool, json_schema: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    if json_schema is not None:
        return {"type": "json_schema", "json_schema": {**json_schema, "strict": False}}
    if json_mode:
        return {"type": "json_object"}
    return None


@dataclass(frozen=True, slots=True)
class LLMProbe:
    reachable: bool
    latency_ms: float | None = None
    model_available: bool | None = None  # None when the server lists no models
    models: list[str] = field(default_factory=list)
    error: str | None = None


class OpenAICompatibleChatModel:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.endpoint = endpoint_kind(base_url)
        key = api_key or (LOCAL_PLACEHOLDER_KEY if self.endpoint == "local" else "")
        # The SDK retries connection errors, 408/409/429 and 5xx with backoff.
        self._client = (
            openai.AsyncOpenAI(
                api_key=key, base_url=base_url, timeout=timeout_seconds, max_retries=max_retries
            )
            if key
            else None
        )

    @property
    def configured(self) -> bool:
        return self._client is not None

    async def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        json_mode: bool = False,
        json_schema: Mapping[str, Any] | None = None,
        purpose: str = "general",
    ) -> str:
        if self._client is None:
            raise LLMNotConfiguredError("LLM_API_KEY is not set for a remote endpoint")

        fmt = response_format(json_mode=json_mode, json_schema=json_schema)
        started = time.perf_counter()
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=fmt if fmt is not None else openai.omit,  # type: ignore[arg-type]
            )
        except openai.OpenAIError as exc:
            self._record(purpose, started, success=False)
            logger.warning("LLM request failed (%s): %s", purpose, exc)
            raise LLMError(str(exc)) from exc

        content = response.choices[0].message.content if response.choices else None
        usage = response.usage
        if usage is not None:
            self._record(purpose, started, usage.prompt_tokens, usage.completion_tokens)
        else:
            self._record(
                purpose,
                started,
                estimate_tokens(system) + estimate_tokens(user),
                estimate_tokens(content or ""),
                estimated=True,
            )
        if not content:
            raise LLMError("LLM returned an empty completion")
        return content

    def _record(
        self,
        purpose: str,
        started: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        *,
        success: bool = True,
        estimated: bool = False,
    ) -> None:
        record_llm_call(
            LLMCallRecord(
                purpose=purpose,
                model=self.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                success=success,
                estimated=estimated,
            )
        )

    async def probe(self, *, timeout_seconds: float = 5.0) -> LLMProbe:
        """List the server's models: proves reachability and that `model` is served."""
        if self._client is None:
            return LLMProbe(reachable=False, error="not configured")
        started = time.perf_counter()
        try:
            page = await self._client.with_options(
                timeout=timeout_seconds, max_retries=0
            ).models.list()
        except openai.OpenAIError as exc:
            return LLMProbe(reachable=False, error=type(exc).__name__)
        latency = round((time.perf_counter() - started) * 1000, 2)
        ids = [m.id for m in page.data]
        return LLMProbe(
            reachable=True,
            latency_ms=latency,
            model_available=(self.model in ids) if ids else None,
            models=ids[:20],
        )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
