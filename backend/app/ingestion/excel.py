"""Import your own companies and financial statements from an Excel workbook.

Sheets are routed by name: sheets containing "company" load companies, and
"financial"/"statement" load financial statements (for companies that exist
or were loaded from an earlier sheet). Column headers are matched
case-insensitively against the aliases below.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, FinancialStatement

logger = logging.getLogger(__name__)

_COMPANY_ALIASES = ("company name", "company", "name")


@dataclass(slots=True)
class ExcelReport:
    companies: int = 0
    statements: int = 0


def _get(row: pd.Series, *aliases: str) -> Any:
    lookup = {str(k).strip().lower(): v for k, v in row.items()}
    for alias in aliases:
        value = lookup.get(alias)
        if value is not None and not pd.isna(value):
            return value
    return None


def _as_date(value: Any) -> dt.date | None:
    return None if value is None else pd.Timestamp(value).date()


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


class ExcelLoader:
    def __init__(self, session: Session) -> None:
        self._session = session

    def load(self, path: Path) -> ExcelReport:
        report = ExcelReport()
        workbook = pd.read_excel(path, sheet_name=None)
        try:
            for sheet, frame in workbook.items():
                key = sheet.lower()
                if "company" in key:
                    report.companies += self._load_companies(frame)
                elif "financial" in key or "statement" in key:
                    report.statements += self._load_financials(frame)
                else:
                    logger.info("Skipping unrecognised sheet %r", sheet)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return report

    def _company(self, name: Any, *, create_from: pd.Series | None = None) -> Company | None:
        if name is None:
            return None
        company = self._session.scalar(select(Company).where(Company.name == str(name)))
        if company is None and create_from is not None:
            company = Company(
                name=str(name),
                ticker=_get(create_from, "ticker"),
                sector=_get(create_from, "sector"),
                industry=_get(create_from, "industry"),
                description=_get(create_from, "description"),
            )
            self._session.add(company)
            self._session.flush()
        return company

    def _load_companies(self, frame: pd.DataFrame) -> int:
        added = 0
        for _, row in frame.iterrows():
            name = _get(row, *_COMPANY_ALIASES)
            if name is None:
                continue
            exists = self._session.scalar(select(Company).where(Company.name == str(name)))
            if exists is None:
                self._company(name, create_from=row)
                added += 1
        return added

    def _load_financials(self, frame: pd.DataFrame) -> int:
        added = 0
        for _, row in frame.iterrows():
            company = self._company(_get(row, *_COMPANY_ALIASES))
            period_end = _as_date(_get(row, "date", "statement date"))
            if company is None or period_end is None:
                continue
            year = _get(row, "year", "fiscal year")
            self._session.add(
                FinancialStatement(
                    company_id=company.id,
                    statement_date=period_end,
                    period_type=_get(row, "period", "period type") or "Annual",
                    fiscal_year=int(year) if year is not None else period_end.year,
                    revenue=_as_float(_get(row, "revenue")),
                    gross_profit=_as_float(_get(row, "gross profit")),
                    operating_income=_as_float(_get(row, "operating income")),
                    net_income=_as_float(_get(row, "net income")),
                    total_assets=_as_float(_get(row, "total assets")),
                    total_liabilities=_as_float(_get(row, "total liabilities")),
                    shareholders_equity=_as_float(_get(row, "equity", "shareholders equity")),
                )
            )
            added += 1
        return added
