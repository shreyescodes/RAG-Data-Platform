import httpx

from app.services.sec_edgar import SUBMISSIONS_URL, TICKER_MAP_URL, SecEdgarClient

TICKERS = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
SUBMISSIONS = {
    "filings": {
        "recent": {
            "form": ["4", "10-Q", "8-K", "10-K"],
            "filingDate": ["2026-10-01", "2026-08-01", "2026-07-15", "2025-11-01"],
            "reportDate": ["", "2026-06-30", "", "2025-09-30"],
            "accessionNumber": ["a-1", "0000320193-26-000077", "a-3", "a-4"],
            "primaryDocument": ["x.xml", "aapl-10q.htm", "y.htm", "aapl-10k.htm"],
        }
    }
}


def _client(seen: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if str(request.url) == TICKER_MAP_URL:
            return httpx.Response(200, json=TICKERS)
        if str(request.url) == SUBMISSIONS_URL.format(cik=320193):
            return httpx.Response(200, json=SUBMISSIONS)
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_recent_filings_filters_forms_and_builds_urls() -> None:
    seen: list[httpx.Request] = []
    async with _client(seen) as http:
        sec = SecEdgarClient(http, user_agent="tests admin@example.com")
        filings = await sec.recent_filings("aapl", limit=2)

    assert [f["form"] for f in filings] == ["10-Q", "8-K"]
    assert filings[0]["url"] == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000077/aapl-10q.htm"
    )
    assert all(r.headers["User-Agent"] == "tests admin@example.com" for r in seen)


async def test_unknown_ticker_returns_empty_and_caches_map() -> None:
    seen: list[httpx.Request] = []
    async with _client(seen) as http:
        sec = SecEdgarClient(http, user_agent="tests")
        assert await sec.recent_filings("ZZZZ") == []
        assert await sec.lookup_cik("AAPL") == 320193

    assert sum(str(r.url) == TICKER_MAP_URL for r in seen) == 1
