"""Test doubles for the embedding model, the LLM and external data clients."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.exceptions import LLMError
from app.rag.embeddings import Matrix

_TOKEN = re.compile(r"[a-z0-9]+")


class HashingEmbedder:
    """Bag-of-words embedder: texts sharing words get similar vectors.

    Deterministic and dependency-free, which is all retrieval tests need.
    """

    model_name = "test-hashing-embedder"
    dimension = 256

    def encode(self, texts: Sequence[str]) -> Matrix:
        out = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in _TOKEN.findall(text.lower().replace("_", " ")):
                bucket = int(hashlib.md5(token.encode()).hexdigest(), 16) % self.dimension  # noqa: S324
                out[row, bucket] += 1.0
            norm = np.linalg.norm(out[row])
            if norm:
                out[row] /= norm
        return out


@dataclass
class FakeChatModel:
    """Scripted LLM. SQL prompts get `sql`, JSON-mode prompts get `analysis`."""

    sql: str = "SELECT name, ticker FROM companies ORDER BY name"
    analysis: dict[str, Any] | str = field(
        default_factory=lambda: {
            "answer": "There are three companies.",
            "summary": "Apple, Microsoft and a private company.",
            "insights": ["Two companies are listed.", "One is private."],
        }
    )
    fail_with: LLMError | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        json_mode: bool = False,
    ) -> str:
        self.calls.append({"system": system, "user": user, "json_mode": json_mode})
        if self.fail_with is not None:
            raise self.fail_with
        if json_mode:
            return self.analysis if isinstance(self.analysis, str) else json.dumps(self.analysis)
        return self.sql


@dataclass
class FakeMarketData:
    quotes: dict[str, dict[str, Any]] = field(default_factory=dict)
    error: Exception | None = None

    async def get_quote(self, ticker: str) -> dict[str, Any] | None:
        if self.error is not None:
            raise self.error
        return self.quotes.get(ticker)


@dataclass
class FakeSecEdgar:
    filings: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    async def recent_filings(self, ticker: str, **_: Any) -> list[dict[str, str]]:
        return self.filings.get(ticker, [])
