"""Data-access helpers used by the API layer."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Company,
    FinancialStatement,
    Fund,
    FundHolding,
    LLMCall,
    MarketData,
    QueryLog,
    RequestMetric,
)


class QueryLogRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entry: QueryLog) -> int:
        self._session.add(entry)
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return entry.id

    def list_for_visitor(self, visitor_id: str, *, limit: int, offset: int) -> Sequence[QueryLog]:
        stmt = (
            select(QueryLog)
            .where(QueryLog.visitor_id == visitor_id)
            .order_by(QueryLog.created_at.desc(), QueryLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return self._session.scalars(stmt).all()

    def count_for_visitor(self, visitor_id: str) -> int:
        stmt = select(func.count()).select_from(QueryLog).where(QueryLog.visitor_id == visitor_id)
        return self._session.scalar(stmt) or 0

    def conversation(self, visitor_id: str, conversation_id: str) -> Sequence[QueryLog]:
        """Every turn of one visitor's conversation, oldest first."""
        stmt = (
            select(QueryLog)
            .where(
                QueryLog.visitor_id == visitor_id,
                QueryLog.conversation_id == conversation_id,
            )
            .order_by(QueryLog.created_at, QueryLog.id)
        )
        return self._session.scalars(stmt).all()

    def count_since(self, since: dt.datetime, *, visitor_id: str | None = None) -> int:
        stmt = select(func.count()).select_from(QueryLog).where(QueryLog.created_at >= since)
        if visitor_id is not None:
            stmt = stmt.where(QueryLog.visitor_id == visitor_id)
        return self._session.scalar(stmt) or 0

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


class MetricsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, metric: RequestMetric) -> None:
        self._session.add(metric)
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def requests_since(self, since: dt.datetime, *, limit: int) -> Sequence[RequestMetric]:
        stmt = (
            select(RequestMetric)
            .where(RequestMetric.created_at >= since)
            .order_by(RequestMetric.created_at.desc())
            .limit(limit)
        )
        return self._session.scalars(stmt).all()

    def calls_since(self, since: dt.datetime, *, limit: int) -> Sequence[LLMCall]:
        stmt = (
            select(LLMCall)
            .join(RequestMetric)
            .where(RequestMetric.created_at >= since)
            .order_by(LLMCall.id.desc())
            .limit(limit)
        )
        return self._session.scalars(stmt).all()

    def recent(self, *, limit: int) -> Sequence[RequestMetric]:
        stmt = (
            select(RequestMetric)
            .order_by(RequestMetric.created_at.desc(), RequestMetric.id.desc())
            .limit(limit)
        )
        return self._session.scalars(stmt).all()


def count_rows_by_table(session: Session) -> dict[str, int]:
    models = (Company, FinancialStatement, MarketData, Fund, FundHolding)
    return {
        model.__tablename__: session.scalar(select(func.count()).select_from(model)) or 0
        for model in models
    }


def companies_by_ticker(session: Session) -> dict[str, str]:
    """Map ticker -> company name for every listed company."""
    stmt = select(Company.ticker, Company.name).where(Company.ticker.is_not(None))
    return {ticker: name for ticker, name in session.execute(stmt).all() if ticker}
