"""ORM models.

`info["description"]` on tables and columns is not DDL; it is the natural
language context the schema indexer embeds so the retriever and SQL generator
understand what each table holds. Tables with `info["queryable"] = False` are
never exposed to the LLM. `info["natural_key"]` names the columns that identify
a row without a database constraint; citations use it for row provenance.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> dt.datetime:
    """Naive UTC timestamp (columns are `timestamp without time zone`)."""
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


def _col_info(description: str) -> dict[str, str]:
    return {"description": description}


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = {
        "info": {
            "description": (
                "Large US-listed public companies with ticker, sector, industry "
                "and a business description (source: Yahoo Finance)."
            )
        }
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    ticker: Mapped[str | None] = mapped_column(
        String(20),
        unique=True,
        index=True,
        info=_col_info("Stock ticker symbol, e.g. AAPL or BRK-B."),
    )
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    founded_date: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=utcnow)

    financials: Mapped[list[FinancialStatement]] = relationship(back_populates="company")


class FinancialStatement(Base):
    __tablename__ = "financial_statements"
    __table_args__ = {
        "info": {
            "description": (
                "Quarterly or annual financial statements per company: income "
                "statement (revenue, profit, EPS), balance sheet (assets, "
                "liabilities, equity) and cash flow figures in USD, as reported "
                "(source: Yahoo Finance)."
            ),
            "natural_key": ("company_id", "statement_date", "period_type"),
        }
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    statement_date: Mapped[dt.date] = mapped_column(Date, info=_col_info("Fiscal period end date."))
    period_type: Mapped[str | None] = mapped_column(
        String(20), info=_col_info("'Quarterly' or 'Annual'.")
    )
    fiscal_year: Mapped[int | None] = mapped_column(Integer)

    # Income statement
    revenue: Mapped[float | None] = mapped_column(Float)
    cost_of_revenue: Mapped[float | None] = mapped_column(Float)
    gross_profit: Mapped[float | None] = mapped_column(Float)
    operating_expenses: Mapped[float | None] = mapped_column(Float)
    ebitda: Mapped[float | None] = mapped_column(Float)
    operating_income: Mapped[float | None] = mapped_column(Float)
    net_income: Mapped[float | None] = mapped_column(Float)
    eps: Mapped[float | None] = mapped_column(Float, info=_col_info("Earnings per share."))

    # Balance sheet
    total_assets: Mapped[float | None] = mapped_column(Float)
    current_assets: Mapped[float | None] = mapped_column(Float)
    total_liabilities: Mapped[float | None] = mapped_column(Float)
    current_liabilities: Mapped[float | None] = mapped_column(Float)
    shareholders_equity: Mapped[float | None] = mapped_column(Float)

    # Cash flow
    operating_cash_flow: Mapped[float | None] = mapped_column(Float)
    investing_cash_flow: Mapped[float | None] = mapped_column(Float)
    financing_cash_flow: Mapped[float | None] = mapped_column(Float)
    free_cash_flow: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=utcnow)

    company: Mapped[Company] = relationship(back_populates="financials")


class MarketData(Base):
    __tablename__ = "market_data"
    __table_args__ = {
        "info": {
            "description": (
                "Daily stock prices (OHLCV) per ticker with 50- and 200-day "
                "moving averages (source: Yahoo Finance). Join to companies on ticker."
            ),
            "related_tables": ("companies",),
            "natural_key": ("ticker", "date"),
        }
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), index=True)
    date: Mapped[dt.date] = mapped_column(Date, info=_col_info("Trading day."))

    open_price: Mapped[float | None] = mapped_column(Float)
    high_price: Mapped[float | None] = mapped_column(Float)
    low_price: Mapped[float | None] = mapped_column(Float)
    close_price: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(Integer)
    adj_close: Mapped[float | None] = mapped_column(
        Float, info=_col_info("Close adjusted for splits and dividends.")
    )

    ma_50: Mapped[float | None] = mapped_column(
        Float, info=_col_info("50-day simple moving average of close.")
    )
    ma_200: Mapped[float | None] = mapped_column(
        Float, info=_col_info("200-day simple moving average of close.")
    )

    created_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=utcnow)


class Fund(Base):
    __tablename__ = "funds"
    __table_args__ = {
        "info": {
            "description": (
                "Directory of the investment managers that file SEC Form 13F: one row "
                "per filer with its registered name and SEC CIK number."
            )
        }
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    cik: Mapped[int] = mapped_column(
        Integer, unique=True, info=_col_info("SEC Central Index Key of the filer.")
    )
    name: Mapped[str] = mapped_column(
        String(255), unique=True, info=_col_info("Filer name as registered with the SEC.")
    )
    created_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=utcnow)

    holdings: Mapped[list[FundHolding]] = relationship(back_populates="fund")


class FundHolding(Base):
    __tablename__ = "fund_holdings"
    __table_args__ = {
        "info": {
            "description": (
                "Stock portfolio holdings of investment funds (Berkshire Hathaway, "
                "Bridgewater, ARK, Pershing Square and other hedge funds) from their "
                "quarterly SEC 13F filings: which stocks and listed options each fund "
                "owns, shares held, market value in USD and portfolio weight, so its "
                "biggest bets and what it bought or sold between quarters. One row per "
                "fund, quarter and security. Join to companies (sector) or market_data "
                "on ticker."
            ),
            "related_tables": ("companies",),
            "natural_key": ("fund_id", "report_date", "cusip", "put_call"),
        }
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id"), index=True)
    report_date: Mapped[dt.date] = mapped_column(
        Date, info=_col_info("Quarter-end date the positions are reported as of.")
    )
    filing_date: Mapped[dt.date | None] = mapped_column(
        Date, info=_col_info("Date the 13F was filed (up to 45 days after quarter end).")
    )
    accession_number: Mapped[str] = mapped_column(
        String(25), info=_col_info("SEC accession number of the filing.")
    )
    issuer_name: Mapped[str] = mapped_column(
        String(255), info=_col_info("Issuer name as written in the filing, often abbreviated.")
    )
    title_of_class: Mapped[str | None] = mapped_column(
        String(100), info=_col_info("Security class, e.g. 'COM' or 'CL A'.")
    )
    cusip: Mapped[str] = mapped_column(String(9), info=_col_info("CUSIP of the security."))
    ticker: Mapped[str | None] = mapped_column(
        String(20),
        index=True,
        info=_col_info("Ticker of the held security; NULL if it could not be identified."),
    )
    shares: Mapped[int | None] = mapped_column(
        BigInteger, info=_col_info("Shares held (principal amount when share_type is PRN).")
    )
    share_type: Mapped[str | None] = mapped_column(
        String(3), info=_col_info("'SH' for shares, 'PRN' for principal amount.")
    )
    put_call: Mapped[str | None] = mapped_column(
        String(4), info=_col_info("'Put' or 'Call' for option positions; NULL for stock.")
    )
    value_usd: Mapped[float | None] = mapped_column(
        Float, info=_col_info("Market value of the position at quarter end, USD.")
    )
    portfolio_pct: Mapped[float | None] = mapped_column(
        Float,
        info=_col_info("Position value as a percentage of the fund's total that quarter, 0-100."),
    )
    created_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=utcnow)

    fund: Mapped[Fund] = relationship(back_populates="holdings")


class SecurityIdentifier(Base):
    """CUSIP -> ticker lookups (OpenFIGI), cached so refreshes only ask about new CUSIPs.

    A NULL ticker records that the lookup found nothing. Never exposed to the LLM.
    """

    __tablename__ = "security_identifiers"
    __table_args__ = {"info": {"queryable": False}}

    cusip: Mapped[str] = mapped_column(String(9), primary_key=True)
    ticker: Mapped[str | None] = mapped_column(String(20))
    name: Mapped[str | None] = mapped_column(String(255))
    looked_up_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class QueryLog(Base):
    """Audit trail of platform queries. Never exposed to the LLM."""

    __tablename__ = "query_logs"
    __table_args__ = {"info": {"queryable": False}}

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stored after PII redaction.
    user_query: Mapped[str] = mapped_column(Text)
    generated_sql: Mapped[str | None] = mapped_column(Text)
    sql_result: Mapped[str | None] = mapped_column(Text)
    final_answer: Mapped[str | None] = mapped_column(Text)
    context_used: Mapped[str | None] = mapped_column(Text)
    agent_reasoning: Mapped[str | None] = mapped_column(Text)
    execution_time_ms: Mapped[float | None] = mapped_column(Float)
    success: Mapped[bool | None] = mapped_column(default=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=utcnow, index=True)


#: Domain tables that may be referenced by generated SQL.
QUERYABLE_MODELS: tuple[type[Base], ...] = (
    Company,
    FinancialStatement,
    MarketData,
    Fund,
    FundHolding,
)


class RequestMetric(Base):
    """One row per query: outcome, LLM usage, cost and latency by stage.

    Operational telemetry for the observability dashboard; never exposed to the LLM.
    """

    __tablename__ = "request_metrics"
    __table_args__ = {"info": {"queryable": False}}

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    request_id: Mapped[str | None] = mapped_column(String(64))
    # PII-redacted and truncated.
    query: Mapped[str] = mapped_column(Text)
    success: Mapped[bool] = mapped_column(default=True)
    error_type: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(255))
    llm_endpoint: Mapped[str] = mapped_column(String(16))  # local | remote
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    cache_hits: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    retrieval_mode: Mapped[str | None] = mapped_column(String(32))
    verification_status: Mapped[str | None] = mapped_column(String(16))
    unsupported_claims: Mapped[int | None] = mapped_column(Integer)
    latency_total_ms: Mapped[float] = mapped_column(Float)
    latency_retrieval_ms: Mapped[float | None] = mapped_column(Float)
    latency_sql_generation_ms: Mapped[float | None] = mapped_column(Float)
    latency_sql_execution_ms: Mapped[float | None] = mapped_column(Float)
    latency_enrichment_ms: Mapped[float | None] = mapped_column(Float)
    latency_analysis_ms: Mapped[float | None] = mapped_column(Float)
    latency_verification_ms: Mapped[float | None] = mapped_column(Float)

    calls: Mapped[list[LLMCall]] = relationship(
        back_populates="request", cascade="all, delete-orphan", passive_deletes=True
    )


class LLMCall(Base):
    """One row per LLM completion (or cache hit) made while answering a query."""

    __tablename__ = "llm_calls"
    __table_args__ = {"info": {"queryable": False}}

    id: Mapped[int] = mapped_column(primary_key=True)
    request_metric_id: Mapped[int] = mapped_column(
        ForeignKey("request_metrics.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    purpose: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(255))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float)
    success: Mapped[bool] = mapped_column(default=True)
    cached: Mapped[bool] = mapped_column(default=False)
    tokens_estimated: Mapped[bool] = mapped_column(default=False)

    request: Mapped[RequestMetric] = relationship(back_populates="calls")
