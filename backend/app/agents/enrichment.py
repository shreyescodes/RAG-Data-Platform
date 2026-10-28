"""Enrichment agent: augments query results with live external data."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from app.agents.base import Agent, Trace
from app.schemas import StageStatus

logger = logging.getLogger(__name__)

T = TypeVar("T")


class QuoteProvider(Protocol):
    async def get_quote(self, ticker: str) -> dict[str, Any] | None: ...


class FilingsProvider(Protocol):
    async def recent_filings(self, ticker: str) -> list[dict[str, str]]: ...


MARKET_KEYWORDS = (
    "stock",
    "share price",
    "price",
    "market cap",
    "quote",
    "trading",
    "p/e",
    "pe ratio",
    "52-week",
    "dividend",
)
FILING_KEYWORDS = ("sec", "edgar", "filing", "10-k", "10-q", "8-k", "annual report")

MAX_TICKERS = 3

_TICKER_TOKEN = re.compile(r"\b[A-Z]{1,5}\b")
_CORPORATE_SUFFIX = re.compile(
    r"[,.]?\s+(inc|incorporated|corp|corporation|co|company|ltd|plc|holdings|group|"
    r"platforms|technologies)\.?$",
    re.IGNORECASE,
)
# First words too generic to identify a company on their own.
_GENERIC_FIRST_WORDS = {"bank", "first", "general", "american", "united", "the", "global"}


def _mentions(text: str, keywords: Iterable[str]) -> bool:
    return any(re.search(rf"\b{re.escape(k)}\b", text) for k in keywords)


def _normalise_company_name(name: str) -> str:
    previous = None
    name = name.strip()
    while previous != name:
        previous, name = name, _CORPORATE_SUFFIX.sub("", name).strip()
    return name.lower()


def extract_tickers(
    question: str,
    rows: Sequence[Mapping[str, Any]],
    companies: Mapping[str, str],
) -> list[str]:
    """Find tickers relevant to a query, most specific source first.

    1. A `ticker` column in the result rows.
    2. Upper-case tokens in the question that are known tickers ("AAPL").
    3. Known company names mentioned in the question ("Apple").

    `companies` maps ticker -> company name for companies in the database.
    """
    found: list[str] = []

    def add(ticker: str) -> None:
        if ticker and ticker not in found:
            found.append(ticker)

    for row in rows:
        for key, value in row.items():
            if key.lower() == "ticker" and isinstance(value, str):
                add(value.upper())

    for token in _TICKER_TOKEN.findall(question):
        if token in companies:
            add(token)

    lowered = question.lower()
    for ticker, name in companies.items():
        normalised = _normalise_company_name(name)
        first_word = normalised.split(" ", 1)[0]
        if (normalised and re.search(rf"\b{re.escape(normalised)}\b", lowered)) or (
            len(first_word) >= 4
            and first_word not in _GENERIC_FIRST_WORDS
            and re.search(rf"\b{re.escape(first_word)}\b", lowered)
        ):
            add(ticker)

    return found[:MAX_TICKERS]


def _successes(outcomes: Sequence[T | BaseException], label: str) -> list[T]:
    """Results of `asyncio.gather(..., return_exceptions=True)`, logging errors."""
    ok: list[T] = []
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            logger.warning("%s lookup failed: %r", label, outcome)
        else:
            ok.append(outcome)
    return ok


def _count_failures(outcomes: Sequence[object]) -> int:
    return sum(isinstance(o, BaseException) for o in outcomes)


@dataclass(slots=True)
class EnrichmentResult:
    status: StageStatus = "skipped"
    data: dict[str, Any] = field(default_factory=dict)


class EnrichmentAgent(Agent):
    name = "enrichment"

    def __init__(
        self,
        *,
        market_data: QuoteProvider | None,
        sec_edgar: FilingsProvider | None,
    ) -> None:
        self._market = market_data
        self._sec = sec_edgar

    def _wanted(self, question: str) -> tuple[bool, bool]:
        lowered = question.lower()
        return (
            self._market is not None and _mentions(lowered, MARKET_KEYWORDS),
            self._sec is not None and _mentions(lowered, FILING_KEYWORDS),
        )

    def wants_enrichment(self, question: str) -> bool:
        """Whether `question` asks for any data this agent can provide."""
        return any(self._wanted(question))

    async def run(
        self,
        question: str,
        rows: Sequence[Mapping[str, Any]],
        companies: Mapping[str, str],
        trace: Trace,
    ) -> EnrichmentResult:
        want_quotes, want_filings = self._wanted(question)
        if not (want_quotes or want_filings):
            self._record(trace, "skipped", "query does not ask for live market or filing data")
            return EnrichmentResult()

        tickers = extract_tickers(question, rows, companies)
        if not tickers:
            self._record(trace, "skipped", "no known ticker in query or results")
            return EnrichmentResult()
        self._record(trace, "tickers_identified", tickers)

        result = EnrichmentResult()
        failures = 0
        if want_quotes and self._market is not None:
            outcomes = await asyncio.gather(
                *(self._market.get_quote(t) for t in tickers), return_exceptions=True
            )
            quotes = [q for q in _successes(outcomes, "quote") if q is not None]
            failures += _count_failures(outcomes)
            if quotes:
                result.data["market_data"] = quotes
            self._record(trace, "market_data_fetched", {"tickers": [q["ticker"] for q in quotes]})

        if want_filings and self._sec is not None:
            batches = await asyncio.gather(
                *(self._sec.recent_filings(t) for t in tickers), return_exceptions=True
            )
            filings = [f for batch in _successes(batches, "SEC filing") for f in batch]
            failures += _count_failures(batches)
            if filings:
                result.data["sec_filings"] = filings
            self._record(trace, "sec_filings_fetched", {"count": len(filings)})

        if failures:
            self._record(trace, "partial_failure", {"failed_calls": failures})

        if result.data:
            result.status = "degraded" if failures else "completed"
        else:
            result.status = "failed" if failures else "skipped"
        return result
