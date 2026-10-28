"""Live market quotes from Yahoo Finance."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Any

import yfinance as yf

logger = logging.getLogger(__name__)

_QUOTE_FIELDS = {
    "currentPrice": "current_price",
    "currency": "currency",
    "marketCap": "market_cap",
    "trailingPE": "pe_ratio",
    "dividendYield": "dividend_yield",
    "fiftyTwoWeekHigh": "fifty_two_week_high",
    "fiftyTwoWeekLow": "fifty_two_week_low",
    "volume": "volume",
}


class MarketDataClient:
    def __init__(self, *, timeout_seconds: float) -> None:
        self._timeout = timeout_seconds

    async def get_quote(self, ticker: str) -> dict[str, Any] | None:
        """Return a quote snapshot, or None if Yahoo has no data for `ticker`."""
        try:
            info = await asyncio.wait_for(
                asyncio.to_thread(self._fetch_info, ticker), timeout=self._timeout
            )
        except TimeoutError:
            logger.warning("Yahoo Finance timed out for %s", ticker)
            return None

        if not info or info.get("currentPrice") is None:
            return None
        quote: dict[str, Any] = {"ticker": ticker}
        quote.update({ours: info.get(theirs) for theirs, ours in _QUOTE_FIELDS.items()})
        quote["fetched_at"] = dt.datetime.now(dt.UTC).isoformat()
        return quote

    @staticmethod
    def _fetch_info(ticker: str) -> dict[str, Any]:
        info: dict[str, Any] = yf.Ticker(ticker).info
        return info
