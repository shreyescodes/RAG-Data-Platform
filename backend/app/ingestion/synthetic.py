"""Deterministic synthetic private-equity portfolio.

Public market data cannot provide PE portfolio holdings or SaaS operating
metrics, so this module generates a realistic portfolio: private companies,
one investment each, and a monthly metrics series from investment date until
exit, write-off or `as_of`.

The series are internally consistent (MRR = ARR / 12, customers = ARR / ARPA,
LTV derived from ARPA, margin and churn, ...) and seeded, so the same seed
always produces the same dataset.
"""

from __future__ import annotations

import datetime as dt
import logging
import random
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Company, PerformanceMetric, PortfolioCompany

logger = logging.getLogger(__name__)

_NAME_PREFIXES = (
    "Atlas", "Beacon", "Bright", "Cedar", "Clear", "Copper", "Echo", "Granite",
    "Harbor", "Helix", "Iron", "Lumen", "Meridian", "Nimbus", "North", "Orbit",
    "Pioneer", "Quantum", "Rapid", "Signal", "Silver", "Summit", "True", "Vector",
)  # fmt: skip
_NAME_SUFFIXES = (
    "Analytics", "Cloud", "Data", "Grid", "Health", "Labs", "Ledger", "Logic",
    "Metrics", "Pay", "Security", "Stack", "Systems", "Works",
)  # fmt: skip

_SECTORS: dict[str, tuple[str, ...]] = {
    "Technology": ("Vertical SaaS", "DevOps Tooling", "Data Infrastructure", "Cybersecurity"),
    "Financial Services": ("Payments", "Lending Platforms", "InsurTech"),
    "Healthcare": ("Health IT", "Digital Health"),
    "Industrials": ("Supply Chain Software", "Logistics Technology"),
}


@dataclass(frozen=True, slots=True)
class _Stage:
    name: str
    check_usd: tuple[float, float]
    ownership_pct: tuple[float, float]
    starting_arr: tuple[float, float]
    monthly_growth: tuple[float, float]
    revenue_multiple: tuple[float, float]
    arpa_usd: tuple[float, float]  # annual revenue per customer


_STAGES = (
    _Stage("Seed", (1e6, 4e6), (12, 25), (0.2e6, 1e6), (0.06, 0.10), (15, 30), (4e3, 15e3)),
    _Stage("Series A", (5e6, 15e6), (15, 25), (1e6, 3e6), (0.04, 0.07), (12, 25), (8e3, 25e3)),
    _Stage("Series B", (15e6, 40e6), (10, 20), (4e6, 12e6), (0.03, 0.05), (10, 18), (15e3, 40e3)),
    _Stage("Series C", (30e6, 80e6), (8, 15), (12e6, 35e6), (0.02, 0.04), (8, 14), (25e3, 60e3)),
    _Stage("Growth", (50e6, 150e6), (5, 15), (30e6, 90e6), (0.012, 0.03), (6, 12), (40e3, 90e3)),
)


def _add_months(day: dt.date, months: int) -> dt.date:
    index = day.month - 1 + months
    return dt.date(day.year + index // 12, index % 12 + 1, 1)


@dataclass(slots=True)
class PortfolioReport:
    companies: int = 0
    metrics: int = 0
    skipped: bool = False


class SyntheticPortfolioGenerator:
    def __init__(self, session: Session, *, seed: int = 42) -> None:
        self._session = session
        self._rng = random.Random(seed)

    def generate(self, *, companies: int, as_of: dt.date | None = None) -> PortfolioReport:
        existing = self._session.scalar(select(func.count()).select_from(PortfolioCompany))
        if existing:
            logger.info("Portfolio already has %d investments; skipping", existing)
            return PortfolioReport(skipped=True)

        as_of = as_of or dt.date.today()
        names = self._unique_names(companies)
        report = PortfolioReport()
        for name in names:
            report.metrics += self._generate_company(name, as_of)
            report.companies += 1
        self._session.commit()
        return report

    def _unique_names(self, count: int) -> list[str]:
        taken = set(self._session.scalars(select(Company.name)).all())
        candidates = [
            f"{prefix} {suffix}"
            for prefix in _NAME_PREFIXES
            for suffix in _NAME_SUFFIXES
            if f"{prefix} {suffix}" not in taken
        ]
        if count > len(candidates):
            raise ValueError(f"can generate at most {len(candidates)} unique companies")
        return self._rng.sample(candidates, count)

    def _generate_company(self, name: str, as_of: dt.date) -> int:
        rng = self._rng
        sector = rng.choice(list(_SECTORS))
        industry = rng.choice(_SECTORS[sector])
        stage = rng.choice(_STAGES)
        invested_on = dt.date(rng.randint(2018, 2022), rng.randint(1, 12), 1)

        company = Company(
            name=name,
            sector=sector,
            industry=industry,
            description=f"Private {industry.lower()} company ({stage.name} investment).",
            founded_date=dt.date(invested_on.year - rng.randint(1, 8), rng.randint(1, 12), 1),
        )

        roll = rng.random()
        status = "Active" if roll < 0.75 else "Exited" if roll < 0.93 else "Written Off"
        end = as_of
        exit_date = None
        if status == "Exited":
            exit_date = _add_months(invested_on, rng.randint(30, 72))
        elif status == "Written Off":
            exit_date = _add_months(invested_on, rng.randint(18, 42))
        if exit_date is not None:
            if exit_date > as_of:
                status, exit_date = "Active", None
            else:
                end = exit_date

        ownership = rng.uniform(*stage.ownership_pct)
        investment = PortfolioCompany(
            company=company,
            investment_date=invested_on,
            exit_date=exit_date,
            investment_amount=round(rng.uniform(*stage.check_usd), -3),
            ownership_percentage=round(ownership, 2),
            investment_stage=stage.name,
            status=status,
        )
        self._session.add(investment)

        metrics = self._metric_series(
            stage, investment, invested_on, end, written_off=status == "Written Off"
        )
        self._session.add_all(metrics)

        last = metrics[-1] if metrics else None
        if status == "Written Off":
            investment.current_valuation = 0.0
        elif last is not None and last.arr is not None and last.revenue_multiple is not None:
            investment.current_valuation = round(
                last.arr * last.revenue_multiple * ownership / 100, -3
            )
        return len(metrics)

    def _metric_series(
        self,
        stage: _Stage,
        investment: PortfolioCompany,
        start: dt.date,
        end: dt.date,
        *,
        written_off: bool,
    ) -> list[PerformanceMetric]:
        rng = self._rng
        arr = rng.uniform(*stage.starting_arr)
        growth = rng.uniform(*stage.monthly_growth)
        arpa = rng.uniform(*stage.arpa_usd)
        churn = rng.uniform(0.006, 0.03)
        gross_margin = rng.uniform(0.68, 0.85)
        multiple = rng.uniform(*stage.revenue_multiple)
        cash = (
            (investment.investment_amount or 0)
            * 100
            / (investment.ownership_percentage or 100)
            * 0.3
        )

        total_months = (end.year - start.year) * 12 + end.month - start.month
        series = []
        for month in range(total_months + 1):
            # Growth decays as companies scale; failing companies shrink.
            if written_off and month > total_months * 0.6:
                monthly_growth = rng.uniform(-0.06, -0.01)
            else:
                monthly_growth = max(0.002, growth * 0.985**month + rng.gauss(0, 0.006))
            arr *= 1 + monthly_growth
            churn = min(0.08, max(0.003, churn + rng.gauss(0, 0.0015)))
            mrr = arr / 12
            burn = max(0.0, mrr * rng.uniform(0.2, 1.4) * 0.97**month)
            cash = max(0.0, cash - burn + (mrr * rng.uniform(0.0, 0.1)))
            ltv = (arpa / 12) * gross_margin / churn
            current_multiple = max(
                2.0, multiple * (1 + (monthly_growth - 0.02) * 4) + rng.gauss(0, 0.4)
            )

            series.append(
                PerformanceMetric(
                    portfolio_company=investment,
                    metric_date=_add_months(start, month),
                    arr=round(arr, 2),
                    mrr=round(mrr, 2),
                    customer_count=max(1, round(arr / arpa)),
                    churn_rate=round(churn, 4),
                    cac=round(ltv / rng.uniform(2.0, 5.0), 2),
                    ltv=round(ltv, 2),
                    burn_rate=round(burn, 2),
                    runway_months=round(min(60.0, cash / burn), 1) if burn > 0 else 60.0,
                    revenue_multiple=round(current_multiple, 2),
                    ebitda_multiple=round(current_multiple * rng.uniform(2.5, 4.0), 2),
                )
            )
        return series
