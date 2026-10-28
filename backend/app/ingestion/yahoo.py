"""Load public-company reference data, prices and statements from Yahoo Finance.

Loading is idempotent: companies are upserted by ticker, and existing price
days and statement periods are skipped, so the loader can be re-run to top up
data.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, FinancialStatement, MarketData

logger = logging.getLogger(__name__)

# Extra history fetched so the 200-day moving average is defined from day one.
_MA_WARMUP_DAYS = 300

# Our column -> (statement frame, Yahoo row label)
_STATEMENT_FIELDS: dict[str, tuple[str, str]] = {
    "revenue": ("income", "Total Revenue"),
    "cost_of_revenue": ("income", "Cost Of Revenue"),
    "gross_profit": ("income", "Gross Profit"),
    "operating_expenses": ("income", "Operating Expense"),
    "ebitda": ("income", "EBITDA"),
    "operating_income": ("income", "Operating Income"),
    "net_income": ("income", "Net Income"),
    "eps": ("income", "Diluted EPS"),
    "total_assets": ("balance", "Total Assets"),
    "current_assets": ("balance", "Current Assets"),
    "total_liabilities": ("balance", "Total Liabilities Net Minority Interest"),
    "current_liabilities": ("balance", "Current Liabilities"),
    "shareholders_equity": ("balance", "Stockholders Equity"),
    "operating_cash_flow": ("cashflow", "Operating Cash Flow"),
    "investing_cash_flow": ("cashflow", "Investing Cash Flow"),
    "financing_cash_flow": ("cashflow", "Financing Cash Flow"),
    "free_cash_flow": ("cashflow", "Free Cash Flow"),
}


@dataclass(slots=True)
class LoadReport:
    companies: int = 0
    price_rows: int = 0
    statements: int = 0
    failed_tickers: list[str] = field(default_factory=list)


def _cell(frame: pd.DataFrame, label: str, column: Any) -> float | None:
    if frame.empty or label not in frame.index or column not in frame.columns:
        return None
    value = frame.at[label, column]
    return None if pd.isna(value) else float(value)


def _optional(value: Any) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


class YahooFinanceLoader:
    def __init__(self, session: Session) -> None:
        self._session = session

    def load(self, tickers: Sequence[str], *, years: int) -> LoadReport:
        report = LoadReport()
        for symbol in tickers:
            try:
                self._load_ticker(symbol.upper(), years, report)
                self._session.commit()
            except Exception:
                # One bad ticker (delisted, rate-limited, ...) must not abort the run.
                logger.exception("Failed to load %s", symbol)
                self._session.rollback()
                report.failed_tickers.append(symbol)
        return report

    def _load_ticker(self, symbol: str, years: int, report: LoadReport) -> None:
        ticker = yf.Ticker(symbol)
        company = self._upsert_company(symbol, ticker.info or {})
        report.companies += 1
        report.price_rows += self._load_prices(symbol, ticker, years)
        report.statements += self._load_statements(company, ticker)
        logger.info("Loaded %s", symbol)

    def _upsert_company(self, symbol: str, info: dict[str, Any]) -> Company:
        company = self._session.scalar(select(Company).where(Company.ticker == symbol))
        if company is None:
            company = Company(ticker=symbol, name=info.get("longName") or symbol)
            self._session.add(company)
        company.sector = info.get("sector") or company.sector
        company.industry = info.get("industry") or company.industry
        summary = info.get("longBusinessSummary")
        if summary:
            company.description = summary[:1000]
        self._session.flush()
        return company

    def _load_prices(self, symbol: str, ticker: yf.Ticker, years: int) -> int:
        end = dt.date.today()
        start = end - dt.timedelta(days=365 * years)
        history = ticker.history(
            start=start - dt.timedelta(days=_MA_WARMUP_DAYS),
            end=end,
            auto_adjust=False,
        )
        if history.empty:
            return 0

        history["ma_50"] = history["Close"].rolling(50, min_periods=50).mean()
        history["ma_200"] = history["Close"].rolling(200, min_periods=200).mean()

        existing = set(
            self._session.scalars(select(MarketData.date).where(MarketData.ticker == symbol)).all()
        )
        rows = []
        for timestamp, bar in history.iterrows():
            day = pd.Timestamp(timestamp).date()
            if day < start or day in existing:
                continue
            rows.append(
                MarketData(
                    ticker=symbol,
                    date=day,
                    open_price=_optional(bar["Open"]),
                    high_price=_optional(bar["High"]),
                    low_price=_optional(bar["Low"]),
                    close_price=_optional(bar["Close"]),
                    adj_close=_optional(bar.get("Adj Close", bar["Close"])),
                    volume=int(bar["Volume"]) if pd.notna(bar["Volume"]) else None,
                    ma_50=_optional(bar["ma_50"]),
                    ma_200=_optional(bar["ma_200"]),
                )
            )
        self._session.add_all(rows)
        return len(rows)

    def _load_statements(self, company: Company, ticker: yf.Ticker) -> int:
        existing = set(
            self._session.execute(
                select(FinancialStatement.statement_date, FinancialStatement.period_type).where(
                    FinancialStatement.company_id == company.id
                )
            ).all()
        )
        periods = {
            "Quarterly": {
                "income": ticker.quarterly_income_stmt,
                "balance": ticker.quarterly_balance_sheet,
                "cashflow": ticker.quarterly_cashflow,
            },
            "Annual": {
                "income": ticker.income_stmt,
                "balance": ticker.balance_sheet,
                "cashflow": ticker.cashflow,
            },
        }

        added = 0
        for period_type, frames in periods.items():
            income = frames["income"]
            if income is None or income.empty:
                continue
            for column in income.columns:
                period_end = pd.Timestamp(column).date()
                if (period_end, period_type) in existing:
                    continue
                values = {
                    field_name: _cell(frames[frame], label, column)
                    for field_name, (frame, label) in _STATEMENT_FIELDS.items()
                }
                if values["revenue"] is None and values["net_income"] is None:
                    continue  # Yahoo sometimes returns empty trailing periods.
                self._session.add(
                    FinancialStatement(
                        company_id=company.id,
                        statement_date=period_end,
                        period_type=period_type,
                        fiscal_year=period_end.year,
                        **values,
                    )
                )
                added += 1
        return added
