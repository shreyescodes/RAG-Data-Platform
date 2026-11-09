"""Test doubles for the embedding model, the LLM and external data clients."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.exceptions import LLMError
from app.observability.metrics import LLMCallRecord, estimate_tokens, record_llm_call
from app.rag.embeddings import Matrix
from app.rag.sparse import tokenize

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
class OverlapReranker:
    """Scores the fraction of query terms a document contains; deterministic."""

    model_name: str = "test-overlap-reranker"
    error: Exception | None = None
    calls: int = 0

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        terms = set(tokenize(query))
        return [len(terms & set(tokenize(doc))) / (len(terms) or 1) for doc in documents]


def sql_reply(sql: str, **overrides: Any) -> str:
    """A well-formed SQL-generation reply; CANNOT_ANSWER means not answerable."""
    answerable = sql != "CANNOT_ANSWER"
    reply: dict[str, Any] = {
        "answerable": answerable,
        "sql": sql if answerable else None,
        "explanation": "Scripted by the test." if answerable else "No matching data.",
        "tables_used": [],
        "confidence": 0.9 if answerable else 0.1,
    }
    reply.update(overrides)
    return json.dumps(reply)


@dataclass
class FakeChatModel:
    """Scripted LLM, routed by the call's `purpose`.

    - `replies[purpose]`: raw completions returned in order before the defaults
      (a queued exception is raised instead);
    - "sql_generation" / "sql_repair": `sql` wrapped as a valid JSON reply;
    - "analysis": `analysis` (a dict is serialised, a str returned verbatim);
    - "verification": `verification`, or a reply marking every claim supported.
    """

    sql: str = "SELECT name, ticker FROM companies ORDER BY name"
    analysis: dict[str, Any] | str = field(
        default_factory=lambda: {
            "answer": "There are three companies.",
            "summary": "Apple, JPMorgan Chase and Microsoft.",
            "insights": ["Two are in Technology.", "One is a bank."],
        }
    )
    verification: dict[str, Any] | str | None = None
    replies: dict[str, list[str | Exception]] = field(default_factory=dict)
    # Priced by default, so cost accounting is exercised end to end.
    model: str = "openai/gpt-oss-120b"
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
        json_schema: Mapping[str, Any] | None = None,
        purpose: str = "general",
    ) -> str:
        self.calls.append(
            {
                "system": system,
                "user": user,
                "json_mode": json_mode,
                "json_schema": json_schema,
                "purpose": purpose,
            }
        )
        reply = self.fail_with or self._reply(user, purpose)
        if isinstance(reply, Exception):
            record_llm_call(LLMCallRecord(purpose, self.model, 0, 0, 1.0, success=False))
            raise reply
        record_llm_call(
            LLMCallRecord(
                purpose=purpose,
                model=self.model,
                prompt_tokens=estimate_tokens(system + user),
                completion_tokens=estimate_tokens(reply),
                latency_ms=1.0,
            )
        )
        return reply

    def _reply(self, user: str, purpose: str) -> str | Exception:
        queued = self.replies.get(purpose)
        if queued:
            return queued.pop(0)
        if purpose in ("sql_generation", "sql_repair"):
            return sql_reply(self.sql)
        if purpose == "analysis":
            return self.analysis if isinstance(self.analysis, str) else json.dumps(self.analysis)
        if purpose == "verification":
            return self._verification(user)
        return self.sql

    def _verification(self, user: str) -> str:
        if isinstance(self.verification, str):
            return self.verification
        if self.verification is not None:
            return json.dumps(self.verification)
        ids = re.findall(r"^\[(c\d+)\]", user, flags=re.MULTILINE)
        return json.dumps(
            {"verdicts": [{"id": i, "verdict": "supported", "evidence": []} for i in ids]}
        )

    def calls_for(self, purpose: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["purpose"] == purpose]


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
