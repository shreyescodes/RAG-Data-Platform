import pytest

from app.agents.base import Trace
from app.agents.enrichment import EnrichmentAgent, extract_tickers
from tests.fakes import FakeMarketData, FakeSecEdgar

COMPANIES = {
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "META": "Meta Platforms, Inc.",
    "BAC": "Bank of America Corporation",
}


@pytest.mark.parametrize(
    ("question", "rows", "expected"),
    [
        ("price of AAPL", [], ["AAPL"]),
        ("what is apple's stock price", [], ["AAPL"]),
        ("compare Microsoft and Meta", [], ["MSFT", "META"]),
        ("top stocks", [{"ticker": "msft"}, {"ticker": "AAPL"}], ["MSFT", "AAPL"]),
        ("bank deposits", [], []),  # generic first word must not match BAC
        ("Bank of America share price", [], ["BAC"]),
        ("ticker XYZ", [], []),
    ],
)
def test_extract_tickers(question: str, rows: list[dict[str, str]], expected: list[str]) -> None:
    assert extract_tickers(question, rows, COMPANIES) == expected


def test_extract_tickers_caps_results() -> None:
    rows = [{"ticker": t} for t in ("A", "B", "C", "D", "E")]
    assert len(extract_tickers("", rows, {})) == 3


async def test_skips_when_not_requested() -> None:
    agent = EnrichmentAgent(market_data=FakeMarketData(), sec_edgar=FakeSecEdgar())
    result = await agent.run("average revenue", [], COMPANIES, Trace())
    assert result.status == "skipped"
    assert not agent.wants_enrichment("average revenue")


async def test_skips_when_no_ticker_found() -> None:
    agent = EnrichmentAgent(market_data=FakeMarketData(), sec_edgar=None)
    result = await agent.run("stock price of unknown co", [], COMPANIES, Trace())
    assert result.status == "skipped"


async def test_fetches_quotes_and_filings() -> None:
    market = FakeMarketData(quotes={"AAPL": {"ticker": "AAPL", "current_price": 250.0}})
    sec = FakeSecEdgar(filings={"AAPL": [{"ticker": "AAPL", "form": "10-K"}]})
    agent = EnrichmentAgent(market_data=market, sec_edgar=sec)
    trace = Trace()

    result = await agent.run("AAPL stock price and latest 10-K filing", [], COMPANIES, trace)

    assert result.status == "completed"
    assert result.data["market_data"][0]["current_price"] == 250.0
    assert result.data["sec_filings"][0]["form"] == "10-K"
    assert [e.step for e in trace.entries] == [
        "tickers_identified",
        "market_data_fetched",
        "sec_filings_fetched",
    ]


async def test_external_failure_is_not_fatal() -> None:
    agent = EnrichmentAgent(market_data=FakeMarketData(error=RuntimeError("down")), sec_edgar=None)
    result = await agent.run("AAPL stock price", [], COMPANIES, Trace())
    assert result.status == "failed"
    assert result.data == {}


async def test_disabled_clients_mean_no_enrichment() -> None:
    agent = EnrichmentAgent(market_data=None, sec_edgar=None)
    assert not agent.wants_enrichment("AAPL stock price")
