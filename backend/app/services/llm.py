"""Chat-completion client for any OpenAI-compatible endpoint (Groq by default)."""

from __future__ import annotations

import logging
from typing import Protocol

import openai

from app.core.exceptions import LLMError, LLMNotConfiguredError

logger = logging.getLogger(__name__)


class ChatModel(Protocol):
    async def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        json_mode: bool = False,
    ) -> str: ...


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
        # The SDK retries connection errors, 408/409/429 and 5xx with backoff.
        self._client = (
            openai.AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout_seconds,
                max_retries=max_retries,
            )
            if api_key
            else None
        )

    async def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        json_mode: bool = False,
    ) -> str:
        if self._client is None:
            raise LLMNotConfiguredError("LLM_API_KEY is not set")

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"} if json_mode else openai.omit,
            )
        except openai.OpenAIError as exc:
            logger.warning("LLM request failed: %s", exc)
            raise LLMError(str(exc)) from exc

        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise LLMError("LLM returned an empty completion")
        return content

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
