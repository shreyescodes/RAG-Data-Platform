"""Analysis agent: turns rows (plus enrichment) into an answer and insights."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import Agent, Trace
from app.agents.result_overview import (
    MAX_SCANNED_ROWS,
    column_overview,
    representative_indices,
    series_patterns,
)
from app.core.exceptions import LLMError
from app.schemas import StageStatus
from app.services.structured_output import StructuredOutputExtractor

logger = logging.getLogger(__name__)

# Bounds on how much result data is sent to the model.
SAMPLE_ROWS = 25
MAX_PROMPT_DATA_CHARS = 8_000
MAX_OVERVIEW_CHARS = 4_000
# Fewer rows are sent when wide rows would not fit, so the last row is never cut off.
_SAMPLE_SIZES = (SAMPLE_ROWS, 13, 7, 3)

_SYSTEM_PROMPT = """\
You are a financial data analyst. You are given a user's question, the SQL \
that was run, its results and optionally live market data.

Answer strictly from the data provided. Do not speculate beyond it: every \
number, name and date you state must appear in, or follow directly from, the \
data. The user sees every row in a table. A long result comes as an overview \
computed from every row, plus selected rows. Describe the whole result from \
its first row to its last, take highs, lows and averages from the overview, \
and do not state details of rows you were not given. Anything about how values \
moved over time (crossings, staying above or below, steady rises or falls) must \
come from the listed patterns; if none are listed, do not describe such moves. \
Do not call the rows a sample. Format numbers for readability (e.g. $1.2B, 4.5%)."""

PURPOSE = "analysis"


class AnalysisPayload(BaseModel):
    answer: str = Field(min_length=1, description="A direct one-to-three sentence answer.")
    summary: str = Field(default="", description="A short paragraph on what the data shows.")
    insights: list[str] = Field(
        default_factory=list, max_length=5, description="2-3 short, specific observations."
    )


@dataclass(slots=True)
class AnalysisResult:
    status: StageStatus
    answer: str
    summary: str = ""
    insights: list[str] = field(default_factory=list)


def _serialise(data: Any, limit: int) -> str:
    text = json.dumps(data, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + " …(truncated)"


def _results_block(rows: Sequence[Mapping[str, Any]]) -> str:
    """The rows themselves when they fit, otherwise an overview plus selected rows."""
    if len(rows) <= SAMPLE_ROWS:
        return (
            f"Results ({len(rows)} of {len(rows)} rows):\n{_serialise(rows, MAX_PROMPT_DATA_CHARS)}"
        )

    scanned = rows[:MAX_SCANNED_ROWS]
    overview = _serialise(column_overview(scanned), MAX_OVERVIEW_CHARS)
    selected: list[Mapping[str, Any]] = []
    text = ""
    for size in _SAMPLE_SIZES:
        selected = [scanned[i] for i in representative_indices(scanned, size)]
        text = _serialise(selected, MAX_PROMPT_DATA_CHARS)
        if len(text) <= MAX_PROMPT_DATA_CHARS:
            break
    patterns = "\n".join(f"- {line}" for line in series_patterns(scanned))
    patterns_block = f"Patterns computed from every row, oldest to newest:\n{patterns}\n\n"
    return (
        f"Results: {len(rows)} rows.\n\n"
        f"Overview of each column across {len(scanned)} rows, in query order:\n{overview}\n\n"
        f"{patterns_block if patterns else ''}"
        f"{len(selected)} selected rows, in query order (the first and last rows, each "
        f"column's highest and lowest rows, and rows spaced evenly between):\n{text}"
    )


class AnalysisAgent(Agent):
    name = "analysis"

    def __init__(self, extractor: StructuredOutputExtractor) -> None:
        self._extractor = extractor

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

        if rows:
            prompt = f"Question: {question}\n\nSQL:\n{sql}\n\n{_results_block(rows)}"
        else:
            prompt = (
                f"Question: {question}\n\n"
                "The internal database has no data for this question; answer from the "
                "live data below only."
            )
        if enrichment:
            prompt += f"\n\nLive data:\n{_serialise(enrichment, MAX_PROMPT_DATA_CHARS // 2)}"

        try:
            extraction = await self._extractor.extract(
                AnalysisPayload,
                system=_SYSTEM_PROMPT,
                user=prompt,
                purpose=PURPOSE,
                temperature=0.2,
                max_tokens=2000,
            )
        except LLMError as exc:  # includes StructuredOutputError after the retries
            logger.warning("Analysis fell back to a deterministic summary: %s", exc)
            self._record(trace, "fallback", type(exc).__name__)
            return self._fallback(rows)

        payload = extraction.value
        self._record(
            trace,
            "analysis_completed",
            {"insights": len(payload.insights), "attempts": len(extraction.attempts)},
        )
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
