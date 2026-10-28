"""ORM models.

`info["description"]` on tables and columns is not DDL; it is the natural
language context the schema indexer embeds so the retriever and SQL generator
understand what each table holds. Tables with `info["queryable"] = False` are
never exposed to the LLM.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
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
                "Master list of companies (public and private) with ticker, "
                "sector and industry classification."
            )
        }
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    ticker: Mapped[str | None] = mapped_column(
        String(20),
        unique=True,
        index=True,
        info=_col_info("Stock ticker symbol, e.g. AAPL. NULL for private companies."),
    )
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    founded_date: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=utcnow)

    financials: Mapped[list[FinancialStatement]] = relationship(back_populates="company")
    portfolios: Mapped[list[PortfolioCompany]] = relationship(back_populates="company")


class FinancialStatement(Base):
    __tablename__ = "financial_statements"
    __table_args__ = {
        "info": {
            "description": (
                "Quarterly or annual financial statements per company: income "
                "statement (revenue, profit, EPS), balance sheet (assets, "
                "liabilities, equity) and cash flow figures in USD."
            )
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


class PortfolioCompany(Base):
    __tablename__ = "portfolio_companies"
    __table_args__ = {
        "info": {
            "description": (
                "Private-equity fund investments: one row per investment in a "
                "company, with amount invested, current valuation, ownership, "
                "stage and status."
            )
        }
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    investment_date: Mapped[dt.date] = mapped_column(Date)
    exit_date: Mapped[dt.date | None] = mapped_column(Date)
    investment_amount: Mapped[float | None] = mapped_column(
        Float, info=_col_info("Capital invested, USD.")
    )
    current_valuation: Mapped[float | None] = mapped_column(
        Float, info=_col_info("Latest valuation of the fund's stake, USD.")
    )
    ownership_percentage: Mapped[float | None] = mapped_column(
        Float, info=_col_info("Fund ownership, 0-100.")
    )
    investment_stage: Mapped[str | None] = mapped_column(
        String(50), info=_col_info("Seed, Series A, Series B, Series C or Growth.")
    )
    status: Mapped[str | None] = mapped_column(
        String(50), info=_col_info("Active, Exited or Written Off.")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=utcnow)

    company: Mapped[Company] = relationship(back_populates="portfolios")
    metrics: Mapped[list[PerformanceMetric]] = relationship(back_populates="portfolio_company")


class PerformanceMetric(Base):
    __tablename__ = "performance_metrics"
    __table_args__ = {
        "info": {
            "description": (
                "Monthly SaaS operating metrics for portfolio companies: ARR, "
                "MRR, customers, churn, CAC, LTV, burn, runway and valuation "
                "multiples."
            )
        }
    }

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_company_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio_companies.id"), index=True
    )
    metric_date: Mapped[dt.date] = mapped_column(Date)

    # Growth
    arr: Mapped[float | None] = mapped_column(
        Float, info=_col_info("Annual recurring revenue, USD.")
    )
    mrr: Mapped[float | None] = mapped_column(
        Float, info=_col_info("Monthly recurring revenue, USD.")
    )
    customer_count: Mapped[int | None] = mapped_column(Integer)
    churn_rate: Mapped[float | None] = mapped_column(
        Float, info=_col_info("Monthly customer churn as a fraction, e.g. 0.02 = 2%.")
    )

    # Efficiency
    cac: Mapped[float | None] = mapped_column(
        Float, info=_col_info("Customer acquisition cost, USD.")
    )
    ltv: Mapped[float | None] = mapped_column(
        Float, info=_col_info("Customer lifetime value, USD.")
    )
    burn_rate: Mapped[float | None] = mapped_column(
        Float, info=_col_info("Net monthly cash burn, USD.")
    )
    runway_months: Mapped[float | None] = mapped_column(Float)

    # Valuation
    revenue_multiple: Mapped[float | None] = mapped_column(Float)
    ebitda_multiple: Mapped[float | None] = mapped_column(Float)

    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime | None] = mapped_column(DateTime, default=utcnow)

    portfolio_company: Mapped[PortfolioCompany] = relationship(back_populates="metrics")


class MarketData(Base):
    __tablename__ = "market_data"
    __table_args__ = {
        "info": {
            "description": (
                "Daily stock prices (OHLCV) per ticker with 50- and 200-day "
                "moving averages. Join to companies on ticker."
            ),
            "related_tables": ("companies",),
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
    PortfolioCompany,
    PerformanceMetric,
    MarketData,
)
