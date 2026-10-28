import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.models import Base, PerformanceMetric, PortfolioCompany
from app.ingestion.synthetic import SyntheticPortfolioGenerator

AS_OF = dt.date(2026, 10, 1)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_generates_consistent_metrics(session: Session) -> None:
    report = SyntheticPortfolioGenerator(session, seed=1).generate(companies=5, as_of=AS_OF)

    assert report.companies == 5
    assert report.metrics == session.scalar(select(func.count()).select_from(PerformanceMetric))
    for metric in session.scalars(select(PerformanceMetric)).all():
        assert metric.arr is not None
        assert metric.mrr is not None
        assert metric.mrr == pytest.approx(metric.arr / 12, rel=1e-6)
        assert metric.ltv is not None
        assert metric.cac is not None
        assert 2.0 <= metric.ltv / metric.cac <= 5.0
        assert metric.metric_date <= AS_OF


def test_is_deterministic_for_a_seed() -> None:
    def run() -> list[tuple[Any, ...]]:
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            SyntheticPortfolioGenerator(session, seed=7).generate(companies=3, as_of=AS_OF)
            rows = session.execute(
                select(
                    PortfolioCompany.investment_stage, PortfolioCompany.current_valuation
                ).order_by(PortfolioCompany.id)
            ).all()
        engine.dispose()
        return [tuple(r) for r in rows]

    assert run() == run()


def test_skips_when_portfolio_exists(session: Session) -> None:
    generator = SyntheticPortfolioGenerator(session, seed=1)
    generator.generate(companies=2, as_of=AS_OF)
    assert generator.generate(companies=2, as_of=AS_OF).skipped


def test_rejects_impossible_company_count(session: Session) -> None:
    with pytest.raises(ValueError, match="at most"):
        SyntheticPortfolioGenerator(session).generate(companies=10_000, as_of=AS_OF)
