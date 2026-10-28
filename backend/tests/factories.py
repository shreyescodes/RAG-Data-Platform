"""Small, known dataset shared by tests that hit the database."""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.db.models import (
    Company,
    FinancialStatement,
    MarketData,
    PerformanceMetric,
    PortfolioCompany,
)


def seed_reference_data(session: Session) -> None:
    apple = Company(name="Apple Inc.", ticker="AAPL", sector="Technology")
    microsoft = Company(name="Microsoft Corporation", ticker="MSFT", sector="Technology")
    private = Company(name="Atlas Analytics", sector="Technology")
    session.add_all([apple, microsoft, private])
    session.flush()

    session.add_all(
        [
            FinancialStatement(
                company_id=apple.id,
                statement_date=dt.date(2026, 6, 30),
                period_type="Quarterly",
                fiscal_year=2026,
                revenue=94.0e9,
                net_income=23.4e9,
            ),
            FinancialStatement(
                company_id=microsoft.id,
                statement_date=dt.date(2026, 6, 30),
                period_type="Quarterly",
                fiscal_year=2026,
                revenue=76.4e9,
                net_income=27.2e9,
            ),
            MarketData(ticker="AAPL", date=dt.date(2026, 10, 27), close_price=251.3),
        ]
    )

    investment = PortfolioCompany(
        company_id=private.id,
        investment_date=dt.date(2021, 3, 1),
        investment_amount=10e6,
        ownership_percentage=20.0,
        investment_stage="Series A",
        status="Active",
    )
    session.add(investment)
    session.flush()
    session.add(
        PerformanceMetric(
            portfolio_company_id=investment.id,
            metric_date=dt.date(2026, 9, 1),
            arr=12e6,
            mrr=1e6,
            churn_rate=0.012,
        )
    )
    session.commit()
