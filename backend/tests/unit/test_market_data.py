import time
from typing import Any

import pytest

from app.services.market_data import MarketDataClient

INFO = {"currentPrice": 251.3, "marketCap": 3.8e12, "trailingPE": 33.1, "currency": "USD"}


async def test_maps_yahoo_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MarketDataClient, "_fetch_info", staticmethod(lambda _: INFO))
    quote = await MarketDataClient(timeout_seconds=1).get_quote("AAPL")

    assert quote is not None
    assert quote["ticker"] == "AAPL"
    assert quote["current_price"] == 251.3
    assert quote["market_cap"] == 3.8e12
    assert quote["pe_ratio"] == 33.1
    assert "fetched_at" in quote


@pytest.mark.parametrize("info", [{}, {"marketCap": 1.0}])
async def test_returns_none_without_price(
    monkeypatch: pytest.MonkeyPatch, info: dict[str, Any]
) -> None:
    monkeypatch.setattr(MarketDataClient, "_fetch_info", staticmethod(lambda _: info))
    assert await MarketDataClient(timeout_seconds=1).get_quote("ZZZZ") is None


async def test_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(_: str) -> dict[str, Any]:
        time.sleep(0.5)
        return INFO

    monkeypatch.setattr(MarketDataClient, "_fetch_info", staticmethod(slow))
    assert await MarketDataClient(timeout_seconds=0.05).get_quote("AAPL") is None
