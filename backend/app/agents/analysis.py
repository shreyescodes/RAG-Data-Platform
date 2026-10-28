"""Analysis agent: turns rows (plus enrichment) into an answer and insights."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agents.base import Agent, Trace
from app.core.exceptions import LLMError
from app.schemas import StageStatus
from app.services.llm import ChatModel

logger = logging.getLogger(__name__)

# Bounds on how much result data is sent to the model.
SAMPLE_ROWS = 25
MAX_PROMPT_DATA_CHARS = 8_000

_SYSTEM_PROMPT = """\
You are a financial data analyst. You are given a user's question, the SQL \
that was run, a sample of its results and optionally live market data.

Answer strictly from the data provided. Do not speculate beyond it. If the \
sample is truncated, say so when it matters. Format numbers for readability \
(e.g. $1.2B, 4.5%).

Respond with a JSON object with keys:
- "answer": a direct one-to-three sentence answer to the question
- "summary": a short paragraph describing what the data shows
- "insights": an array of 2-3 short, specific observations"""


class _AnalysisPayload(BaseModel):
    answer: str
    summary: str = ""
    insights: list[str] = Field(default_factory=list, max_length=5)


@dataclass(slots=True)
class AnalysisResult:
    status: StageStatus
    answer: str
    summary: str = ""
    insights: list[str] = field(default_factory=list)


def _serialise(data: Any, limit: int) -> str:
    text = json.dumps(data, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + " …(truncated)"


class AnalysisAgent(Agent):
    name = "analysis"

    def __init__(self, chat_model: ChatModel) -> None:
        self._chat = chat_model

    async def run(
        self,
        question: str,
        sql: str,
        rows: Sequence[Mapping[str, Any]],
        enrichment: Mapping[str, Any],
        trace: Trace,
    ) -> AnalysisResult:
        if not rows and not enrichment:
            self._record(trace, "no_rows")
            return AnalysisResult(
                status="completed",
                answer="No records matched this query.",
                summary="The query ran successfully but returned no rows.",
            )

        sample = list(rows[:SAMPLE_ROWS])
        if rows:
            prompt = (
                f"Question: {question}\n\n"
                f"SQL:\n{sql}\n\n"
                f"Results ({len(sample)} of {len(rows)} rows):\n"
                f"{_serialise(sample, MAX_PROMPT_DATA_CHARS)}"
            )
        else:
            prompt = (
                f"Question: {question}\n\n"
                "The internal database has no data for this question; answer from the "
                "live data below only."
            )
        if enrichment:
            prompt += f"\n\nLive data:\n{_serialise(enrichment, MAX_PROMPT_DATA_CHARS // 2)}"

        try:
            completion = await self._chat.complete(
                system=_SYSTEM_PROMPT,
                user=prompt,
                temperature=0.2,
                max_tokens=2000,
                json_mode=True,
            )
            payload = _AnalysisPayload.model_validate_json(completion)
        except (LLMError, ValidationError) as exc:
            logger.warning("Analysis fell back to a deterministic summary: %s", exc)
            self._record(trace, "fallback", type(exc).__name__)
            return self._fallback(rows)

        self._record(trace, "analysis_completed", {"insights": len(payload.insights)})
        return AnalysisResult(
            status="completed",
            answer=payload.answer,
            summary=payload.summary,
            insights=payload.insights,
        )

    @staticmethod
    def _fallback(rows: Sequence[Mapping[str, Any]]) -> AnalysisResult:
        if not rows:
            return AnalysisResult(
                status="degraded",
                answer="Live market data was retrieved; see the details below.",
            )
        columns = ", ".join(rows[0].keys())
        return AnalysisResult(
            status="degraded",
            answer=f"The query returned {len(rows)} row(s).",
            summary=(
                f"Columns: {columns}. An AI-generated narrative is unavailable, "
                "so the raw results are shown below."
            ),
        )
