from typing import Dict, Any, Optional
from .base_agent import BaseAgent
import httpx
import os
import yfinance as yf
from datetime import datetime


class EnrichmentAgent(BaseAgent):
    def __init__(self):
        super().__init__("EnrichmentAgent")
        self.sec_api_key = os.getenv("SEC_EDGAR_API_KEY")

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enrichment Agent workflow:
        1. Determine if additional external data is needed
        2. Fetch data from external APIs (Yahoo Finance, SEC EDGAR)
        3. Enrich the response with external context
        """
        user_query = context.get("query", "").lower()
        analysis_result = context.get("analysis_result", {})

        self.log_reasoning("enrichment_started", {
            "query": user_query
        })

        enriched_data = {}

        # Check if query mentions specific companies or tickers
        if any(keyword in user_query for keyword in ["stock", "ticker", "market", "price", "yahoo"]):
            ticker = self._extract_ticker(context)
            if ticker:
                market_data = await self._fetch_yahoo_finance(ticker)
                if market_data:
                    enriched_data["market_data"] = market_data
                    self.log_reasoning("yahoo_finance_enrichment", {
                        "ticker": ticker,
                        "data_fetched": True
                    })

        # Check if SEC EDGAR data is needed
        if any(keyword in user_query for keyword in ["sec", "edgar", "filing", "10-k", "10-q"]):
            company_cik = self._extract_company_identifier(context)
            if company_cik:
                sec_data = await self._fetch_sec_edgar(company_cik)
                if sec_data:
                    enriched_data["sec_data"] = sec_data
                    self.log_reasoning("sec_edgar_enrichment", {
                        "company": company_cik,
                        "data_fetched": True
                    })

        if not enriched_data:
            self.log_reasoning("no_enrichment_needed", "Query does not require external data")

        return {
            "success": True,
            "enriched_data": enriched_data,
            "reasoning": self.get_reasoning()
        }

    def _extract_ticker(self, context: Dict[str, Any]) -> Optional[str]:
        """Extract stock ticker from context"""
        # Try to find ticker in retrieval results
        retrieval_result = context.get("retrieval_result", {})
        data = retrieval_result.get("data", [])

        for row in data:
            if isinstance(row, dict) and "ticker" in row:
                return row["ticker"]

        # Could also parse from query using NLP
        return None

    def _extract_company_identifier(self, context: Dict[str, Any]) -> Optional[str]:
        """Extract company name or CIK for SEC lookup"""
        retrieval_result = context.get("retrieval_result", {})
        data = retrieval_result.get("data", [])

        for row in data:
            if isinstance(row, dict):
                if "name" in row:
                    return row["name"]
                if "ticker" in row:
                    return row["ticker"]

        return None

    async def _fetch_yahoo_finance(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch real-time data from Yahoo Finance"""
        try:
            stock = yf.Ticker(ticker)
            info = stock.info

            return {
                "ticker": ticker,
                "current_price": info.get("currentPrice"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "dividend_yield": info.get("dividendYield"),
                "52_week_high": info.get("fiftyTwoWeekHigh"),
                "52_week_low": info.get("fiftyTwoWeekLow"),
                "volume": info.get("volume"),
                "fetched_at": datetime.utcnow().isoformat()
            }
        except Exception as e:
            self.log_reasoning("yahoo_finance_error", str(e))
            return None

    async def _fetch_sec_edgar(self, company_identifier: str) -> Optional[Dict[str, Any]]:
        """Fetch data from SEC EDGAR API"""
        if not self.sec_api_key:
            return None

        try:
            async with httpx.AsyncClient() as client:
                headers = {
                    "User-Agent": f"RAG Platform {self.sec_api_key}"
                }

                # Search for company CIK
                search_url = f"https://www.sec.gov/cgi-bin/browse-edgar"
                params = {
                    "company": company_identifier,
                    "output": "json"
                }

                response = await client.get(search_url, headers=headers, params=params, timeout=10)

                if response.status_code == 200:
                    return {
                        "company": company_identifier,
                        "search_results": response.json(),
                        "fetched_at": datetime.utcnow().isoformat()
                    }

        except Exception as e:
            self.log_reasoning("sec_edgar_error", str(e))
            return None

        return None
