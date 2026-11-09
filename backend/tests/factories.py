"""Small, known dataset shared by tests that hit the database."""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.db.models import Company, FinancialStatement, Fund, FundHolding, MarketData


def seed_reference_data(session: Session) -> None:
    apple = Company(name="Apple Inc.", ticker="AAPL", sector="Technology")
    microsoft = Company(name="Microsoft Corporation", ticker="MSFT", sector="Technology")
    jpmorgan = Company(name="JPMorgan Chase & Co.", ticker="JPM", sector="Financial Services")
    session.add_all([apple, microsoft, jpmorgan])
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

    berkshire = Fund(cik=1067983, name="BERKSHIRE HATHAWAY INC")
    session.add(berkshire)
    session.flush()
    session.add(
        FundHolding(
            fund_id=berkshire.id,
            report_date=dt.date(2026, 6, 30),
            filing_date=dt.date(2026, 8, 14),
            accession_number="0001193125-26-352200",
            issuer_name="APPLE INC",
            title_of_class="COM",
            cusip="037833100",
            ticker="AAPL",
            shares=280_000_000,
            share_type="SH",
            value_usd=70.4e9,
            portfolio_pct=23.5,
        )
    )
    session.commit()
