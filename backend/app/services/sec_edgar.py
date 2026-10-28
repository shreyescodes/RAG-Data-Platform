"""Recent filings from SEC EDGAR's public JSON APIs.

No API key is required, but the SEC asks every client to send a descriptive
User-Agent and to stay under 10 requests/second:
https://www.sec.gov/os/accessing-edgar-data
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Collection
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"

DEFAULT_FORMS = frozenset({"10-K", "10-Q", "8-K"})


class SecEdgarClient:
    def __init__(self, http: httpx.AsyncClient, *, user_agent: str) -> None:
        self._http = http
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self._cik_by_ticker: dict[str, int] | None = None
        self._lock = asyncio.Lock()

    async def _get_json(self, url: str) -> Any:
        response = await self._http.get(url, headers=self._headers)
        response.raise_for_status()
        return response.json()

    async def lookup_cik(self, ticker: str) -> int | None:
        if self._cik_by_ticker is None:
            async with self._lock:
                if self._cik_by_ticker is None:
                    payload = await self._get_json(TICKER_MAP_URL)
                    self._cik_by_ticker = {
                        str(row["ticker"]).upper(): int(row["cik_str"]) for row in payload.values()
                    }
        return self._cik_by_ticker.get(ticker.upper())

    async def recent_filings(
        self,
        ticker: str,
        *,
        forms: Collection[str] = DEFAULT_FORMS,
        limit: int = 5,
    ) -> list[dict[str, str]]:
        cik = await self.lookup_cik(ticker)
        if cik is None:
            return []

        payload = await self._get_json(SUBMISSIONS_URL.format(cik=cik))
        recent = payload.get("filings", {}).get("recent", {})
        columns = ("form", "filingDate", "reportDate", "accessionNumber", "primaryDocument")
        rows = zip(*(recent.get(col, []) for col in columns), strict=False)

        filings: list[dict[str, str]] = []
        for form, filed, period, accession, document in rows:
            if form not in forms:
                continue
            filings.append(
                {
                    "ticker": ticker.upper(),
                    "form": form,
                    "filing_date": filed,
                    "period": period,
                    "url": ARCHIVE_URL.format(
                        cik=cik, accession=accession.replace("-", ""), document=document
                    ),
                }
            )
            if len(filings) >= limit:
                break
        return filings
