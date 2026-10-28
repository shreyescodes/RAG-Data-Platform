"""Data-access helpers used by the API layer."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Company,
    FinancialStatement,
    MarketData,
    PerformanceMetric,
    PortfolioCompany,
    QueryLog,
)


class QueryLogRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entry: QueryLog) -> None:
        self._session.add(entry)
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def list_recent(self, *, limit: int, offset: int) -> Sequence[QueryLog]:
        stmt = (
            select(QueryLog)
            .order_by(QueryLog.created_at.desc(), QueryLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return self._session.scalars(stmt).all()

    def count(self, *, successful_only: bool = False) -> int:
        stmt = select(func.count()).select_from(QueryLog)
        if successful_only:
            stmt = stmt.where(QueryLog.success.is_(True))
        return self._session.scalar(stmt) or 0


def count_rows_by_table(session: Session) -> dict[str, int]:
    models = (Company, FinancialStatement, PortfolioCompany, PerformanceMetric, MarketData)
    return {
        model.__tablename__: session.scalar(select(func.count()).select_from(model)) or 0
        for model in models
    }


def companies_by_ticker(session: Session) -> dict[str, str]:
    """Map ticker -> company name for every listed company."""
    stmt = select(Company.ticker, Company.name).where(Company.ticker.is_not(None))
    return {ticker: name for ticker, name in session.execute(stmt).all() if ticker}
