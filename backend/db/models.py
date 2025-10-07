from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, Date, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    ticker = Column(String(20), unique=True, index=True)
    sector = Column(String(100))
    industry = Column(String(100))
    description = Column(Text)
    founded_date = Column(Date)
    created_at = Column(DateTime, default=datetime.utcnow)

    financials = relationship("FinancialStatement", back_populates="company")
    portfolios = relationship("PortfolioCompany", back_populates="company")


class FinancialStatement(Base):
    __tablename__ = "financial_statements"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    statement_date = Column(Date, nullable=False)
    period_type = Column(String(20))  # Q1, Q2, Q3, Q4, Annual
    fiscal_year = Column(Integer)

    # Income Statement
    revenue = Column(Float)
    cost_of_revenue = Column(Float)
    gross_profit = Column(Float)
    operating_expenses = Column(Float)
    ebitda = Column(Float)
    operating_income = Column(Float)
    net_income = Column(Float)
    eps = Column(Float)

    # Balance Sheet
    total_assets = Column(Float)
    current_assets = Column(Float)
    total_liabilities = Column(Float)
    current_liabilities = Column(Float)
    shareholders_equity = Column(Float)

    # Cash Flow
    operating_cash_flow = Column(Float)
    investing_cash_flow = Column(Float)
    financing_cash_flow = Column(Float)
    free_cash_flow = Column(Float)

    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="financials")


class PortfolioCompany(Base):
    __tablename__ = "portfolio_companies"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    investment_date = Column(Date, nullable=False)
    exit_date = Column(Date)
    investment_amount = Column(Float)
    current_valuation = Column(Float)
    ownership_percentage = Column(Float)
    investment_stage = Column(String(50))  # Seed, Series A, Growth, etc.
    status = Column(String(50))  # Active, Exited, Written Off
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="portfolios")
    metrics = relationship("PerformanceMetric", back_populates="portfolio_company")


class PerformanceMetric(Base):
    __tablename__ = "performance_metrics"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_company_id = Column(Integer, ForeignKey("portfolio_companies.id"), nullable=False)
    metric_date = Column(Date, nullable=False)

    # Growth Metrics
    arr = Column(Float)  # Annual Recurring Revenue
    mrr = Column(Float)  # Monthly Recurring Revenue
    customer_count = Column(Integer)
    churn_rate = Column(Float)

    # Efficiency Metrics
    cac = Column(Float)  # Customer Acquisition Cost
    ltv = Column(Float)  # Lifetime Value
    burn_rate = Column(Float)
    runway_months = Column(Float)

    # Valuation Metrics
    revenue_multiple = Column(Float)
    ebitda_multiple = Column(Float)

    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    portfolio_company = relationship("PortfolioCompany", back_populates="metrics")


class MarketData(Base):
    __tablename__ = "market_data"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(20), nullable=False, index=True)
    date = Column(Date, nullable=False)

    open_price = Column(Float)
    high_price = Column(Float)
    low_price = Column(Float)
    close_price = Column(Float)
    volume = Column(Integer)
    adj_close = Column(Float)

    # Technical Indicators
    ma_50 = Column(Float)  # 50-day moving average
    ma_200 = Column(Float)  # 200-day moving average

    created_at = Column(DateTime, default=datetime.utcnow)


class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_query = Column(Text, nullable=False)
    generated_sql = Column(Text)
    sql_result = Column(Text)
    final_answer = Column(Text)
    context_used = Column(Text)
    agent_reasoning = Column(Text)
    execution_time_ms = Column(Float)
    success = Column(Boolean, default=True)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
