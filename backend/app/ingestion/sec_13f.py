"""Load quarterly fund holdings from SEC Form 13F filings.

Institutional managers with over $100M in US equities must report their
positions to the SEC within 45 days of each quarter end. This loader reads the
filings from EDGAR (no API key; the SEC asks for a contact User-Agent and at
most 10 requests/second), and maps each CUSIP to a ticker with OpenFIGI so the
holdings join to `companies` and `market_data`.

Loading is idempotent: quarters already stored for a fund are skipped, so the
loader can run on a schedule to pick up new filings.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx
from defusedxml.ElementTree import fromstring as parse_xml
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Fund, FundHolding, SecurityIdentifier

logger = logging.getLogger(__name__)

#: Well-known filers with very different styles: value, macro, innovation,
#: activist, family offices and tech-focused hedge funds.
DEFAULT_FUND_CIKS: tuple[int, ...] = (
    1067983,  # Berkshire Hathaway
    1350694,  # Bridgewater Associates
    1697748,  # ARK Investment Management
    1336528,  # Pershing Square Capital Management
    1536411,  # Duquesne Family Office
    1029160,  # Soros Fund Management
    1167483,  # Tiger Global Management
    1040273,  # Third Point
    1656456,  # Appaloosa
    1061768,  # Baupost Group
)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FILING_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/index.json"
FILING_FILE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{name}"
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"

# Filings made before this date report values in thousands of dollars.
_DOLLAR_VALUES_SINCE = dt.date(2023, 1, 3)


@dataclass(slots=True)
class Position:
    issuer_name: str
    title_of_class: str | None
    cusip: str
    shares: int | None
    share_type: str | None
    put_call: str | None
    value_usd: float


@dataclass(slots=True)
class Filing:
    accession_number: str
    report_date: dt.date
    filing_date: dt.date


@dataclass(slots=True)
class HoldingsReport:
    funds: int = 0
    filings: int = 0
    holdings: int = 0
    tickers_mapped: int = 0
    failed_funds: list[int] = field(default_factory=list)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, name: str) -> str | None:
    for child in element.iter():
        if _local(child.tag) == name and child.text and child.text.strip():
            return child.text.strip()
    return None


def parse_information_table(xml: bytes, *, value_multiplier: float = 1.0) -> list[Position]:
    """Parse a 13F information table into one position per security.

    Filers often split a security across several rows (one per sub-manager or
    voting arrangement); those rows are summed.
    """
    # defusedxml: the XML comes from the internet, so entity expansion is refused.
    root = parse_xml(xml)
    merged: dict[tuple[str, str | None, str | None], Position] = {}
    for entry in root.iter():
        if _local(entry.tag) != "infoTable":
            continue
        cusip = (_child_text(entry, "cusip") or "").upper()
        if not cusip:
            continue
        put_call = _child_text(entry, "putCall")
        put_call = put_call.capitalize() if put_call else None
        share_type = _child_text(entry, "sshPrnamtType")
        shares_text = _child_text(entry, "sshPrnamt")
        shares = int(float(shares_text)) if shares_text else None
        value = float(_child_text(entry, "value") or 0) * value_multiplier

        key = (cusip, put_call, share_type)
        if key in merged:
            position = merged[key]
            position.value_usd += value
            if shares is not None:
                position.shares = (position.shares or 0) + shares
        else:
            merged[key] = Position(
                issuer_name=_child_text(entry, "nameOfIssuer") or cusip,
                title_of_class=_child_text(entry, "titleOfClass"),
                cusip=cusip,
                shares=shares,
                share_type=share_type,
                put_call=put_call,
                value_usd=value,
            )
    return list(merged.values())


def reported_in_thousands(positions: Sequence[Position]) -> bool:
    """Whether a filing still reports values in thousands of dollars.

    The SEC switched 13F values to whole dollars in January 2023, but some
    filers kept using thousands. Listed stocks trade well above $1, so a median
    implied price per share below $1 gives that away.
    """
    prices = sorted(
        p.value_usd / p.shares
        for p in positions
        if p.share_type == "SH" and p.put_call is None and p.shares
    )
    return bool(prices) and prices[len(prices) // 2] < 1.0


def latest_quarterly_filings(submissions: dict[str, Any], quarters: int) -> list[Filing]:
    """The newest original 13F-HR per quarter, most recent first.

    Amendments (13F-HR/A) are skipped: they may restate or only add to a report,
    and the form does not say which.
    """
    recent = submissions.get("filings", {}).get("recent", {})
    by_quarter: dict[dt.date, Filing] = {}
    for form, accession, report, filed in zip(
        recent.get("form", []),
        recent.get("accessionNumber", []),
        recent.get("reportDate", []),
        recent.get("filingDate", []),
        strict=False,
    ):
        if form != "13F-HR" or not report:
            continue
        filing = Filing(accession, dt.date.fromisoformat(report), dt.date.fromisoformat(filed))
        current = by_quarter.get(filing.report_date)
        if current is None or filing.filing_date > current.filing_date:
            by_quarter[filing.report_date] = filing
    return sorted(by_quarter.values(), key=lambda f: f.report_date, reverse=True)[:quarters]


def normalize_ticker(ticker: str) -> str:
    """OpenFIGI writes share classes as BRK/B; Yahoo Finance uses BRK-B."""
    return ticker.strip().upper().replace("/", "-").replace(" ", "-")


def _id_type(cusip: str) -> str:
    """CUSIPs of foreign-incorporated issuers (Chubb, CRH, ...) start with a
    letter: those are CINS codes, which OpenFIGI looks up under their own type."""
    return "ID_CINS" if cusip[:1].isalpha() else "ID_CUSIP"


class _Throttle:
    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._last = 0.0

    def wait(self) -> None:
        delay = self._last + self._interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()


class OpenFigiClient:
    """CUSIP -> US ticker via https://www.openfigi.com/api (free; key optional)."""

    def __init__(self, http: httpx.Client, *, api_key: str | None = None) -> None:
        self._http = http
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["X-OPENFIGI-APIKEY"] = api_key
        # Without a key: 25 requests/minute, 10 CUSIPs each. With one: 25 per
        # 6 seconds, 100 each.
        self.batch_size = 100 if api_key else 10
        self._throttle = _Throttle(0.25 if api_key else 2.5)

    def lookup(self, cusips: Sequence[str]) -> dict[str, tuple[str | None, str | None]]:
        """Map each CUSIP to (ticker, name); (None, None) when nothing is listed in the US."""
        results: dict[str, tuple[str | None, str | None]] = {}
        for start in range(0, len(cusips), self.batch_size):
            batch = list(cusips[start : start + self.batch_size])
            jobs = [{"idType": _id_type(c), "idValue": c} for c in batch]
            for attempt in range(4):
                self._throttle.wait()
                response = self._http.post(OPENFIGI_URL, json=jobs, headers=self._headers)
                if response.status_code != 429:
                    break
                time.sleep(15 * (attempt + 1))  # rate limited: back off and retry
            response.raise_for_status()
            for cusip, answer in zip(batch, response.json(), strict=False):
                listings = [d for d in answer.get("data", []) if d.get("exchCode") == "US"]
                if listings and listings[0].get("ticker"):
                    best = listings[0]
                    results[cusip] = (normalize_ticker(best["ticker"]), best.get("name"))
                else:
                    results[cusip] = (None, None)
        return results


class Form13FLoader:
    def __init__(
        self,
        session: Session,
        *,
        user_agent: str,
        http: httpx.Client | None = None,
        openfigi: OpenFigiClient | None = None,
        openfigi_api_key: str | None = None,
        sec_request_interval: float = 0.15,
    ) -> None:
        self._session = session
        self._http = http or httpx.Client(timeout=30.0, follow_redirects=True)
        self._sec_headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        self._sec_throttle = _Throttle(sec_request_interval)
        self._openfigi = openfigi or OpenFigiClient(self._http, api_key=openfigi_api_key)

    # --- SEC access ------------------------------------------------------------

    def _sec_get(self, url: str) -> httpx.Response:
        for attempt in range(4):
            self._sec_throttle.wait()
            response = self._http.get(url, headers=self._sec_headers)
            if response.status_code not in (429, 503):
                response.raise_for_status()
                return response
            time.sleep(2 * (attempt + 1))
        response.raise_for_status()
        return response

    def _information_table(self, cik: int, accession: str) -> bytes:
        folder = accession.replace("-", "")
        index = self._sec_get(FILING_INDEX_URL.format(cik=cik, accession=folder)).json()
        candidates = [
            item
            for item in index["directory"]["item"]
            if item["name"].lower().endswith(".xml") and item["name"].lower() != "primary_doc.xml"
        ]
        if not candidates:
            raise ValueError(f"no information table in filing {accession}")
        # The information table is the large XML; the cover page is primary_doc.xml.
        name = max(candidates, key=lambda item: int(item.get("size") or 0))["name"]
        return self._sec_get(FILING_FILE_URL.format(cik=cik, accession=folder, name=name)).content

    # --- Loading -----------------------------------------------------------------

    def load(self, ciks: Iterable[int], *, quarters: int) -> HoldingsReport:
        report = HoldingsReport()
        for cik in ciks:
            try:
                self._load_fund(cik, quarters, report)
            except Exception:
                # One failing filer must not abort the run.
                logger.exception("Failed to load 13F filings for CIK %s", cik)
                self._session.rollback()
                report.failed_funds.append(cik)
        try:
            report.tickers_mapped = self.backfill_tickers()
        except httpx.HTTPError:
            logger.exception("Ticker lookup failed; holdings keep NULL tickers until next run")
            self._session.rollback()
        return report

    def _load_fund(self, cik: int, quarters: int, report: HoldingsReport) -> None:
        submissions = self._sec_get(SUBMISSIONS_URL.format(cik=cik)).json()
        fund = self._upsert_fund(cik, str(submissions.get("name") or f"CIK {cik}"))
        report.funds += 1

        stored = set(
            self._session.scalars(
                select(FundHolding.report_date).where(FundHolding.fund_id == fund.id).distinct()
            ).all()
        )
        for filing in latest_quarterly_filings(submissions, quarters):
            if filing.report_date in stored:
                continue
            multiplier = 1.0 if filing.filing_date >= _DOLLAR_VALUES_SINCE else 1000.0
            positions = parse_information_table(
                self._information_table(cik, filing.accession_number),
                value_multiplier=multiplier,
            )
            if multiplier == 1.0 and reported_in_thousands(positions):
                logger.warning(
                    "%s reported %s in thousands of dollars; converting",
                    fund.name,
                    filing.report_date,
                )
                for position in positions:
                    position.value_usd *= 1000
            report.holdings += self._store(fund, filing, positions)
            report.filings += 1
            self._session.commit()
            logger.info("13F %s %s: %d positions", fund.name, filing.report_date, len(positions))

    def _upsert_fund(self, cik: int, name: str) -> Fund:
        fund = self._session.scalar(select(Fund).where(Fund.cik == cik))
        if fund is None:
            fund = Fund(cik=cik, name=name)
            self._session.add(fund)
        else:
            fund.name = name
        self._session.flush()
        return fund

    def _store(self, fund: Fund, filing: Filing, positions: Sequence[Position]) -> int:
        total = sum(p.value_usd for p in positions)
        known: dict[str, str | None] = dict(
            self._session.execute(
                select(SecurityIdentifier.cusip, SecurityIdentifier.ticker).where(
                    SecurityIdentifier.cusip.in_({p.cusip for p in positions})
                )
            ).all()
        )
        self._session.add_all(
            FundHolding(
                fund_id=fund.id,
                report_date=filing.report_date,
                filing_date=filing.filing_date,
                accession_number=filing.accession_number,
                issuer_name=p.issuer_name[:255],
                title_of_class=p.title_of_class[:100] if p.title_of_class else None,
                cusip=p.cusip,
                ticker=known.get(p.cusip),
                shares=p.shares,
                share_type=p.share_type,
                put_call=p.put_call,
                value_usd=p.value_usd,
                portfolio_pct=round(100 * p.value_usd / total, 4) if total else None,
            )
            for p in positions
        )
        return len(positions)

    def backfill_tickers(self) -> int:
        """Look up CUSIPs never seen before and fill in missing tickers.

        Every answer is cached in security_identifiers (including "not listed"),
        so each CUSIP is looked up once.
        """
        missing = set(
            self._session.scalars(
                select(FundHolding.cusip).where(FundHolding.ticker.is_(None)).distinct()
            ).all()
        )
        cached = set(
            self._session.scalars(
                select(SecurityIdentifier.cusip).where(SecurityIdentifier.cusip.in_(missing))
            ).all()
        )
        to_lookup = sorted(missing - cached)
        if to_lookup:
            logger.info("Looking up %d new CUSIPs on OpenFIGI", len(to_lookup))
            for start in range(0, len(to_lookup), 200):
                found = self._openfigi.lookup(to_lookup[start : start + 200])
                self._session.add_all(
                    SecurityIdentifier(cusip=c, ticker=t, name=n) for c, (t, n) in found.items()
                )
                self._session.commit()  # keep progress if a later batch fails

        mapped: dict[str, str | None] = dict(
            self._session.execute(
                select(SecurityIdentifier.cusip, SecurityIdentifier.ticker).where(
                    SecurityIdentifier.cusip.in_(missing),
                    SecurityIdentifier.ticker.is_not(None),
                )
            ).all()
        )
        for cusip, ticker in mapped.items():
            self._session.execute(
                update(FundHolding)
                .where(FundHolding.cusip == cusip, FundHolding.ticker.is_(None))
                .values(ticker=ticker)
            )
        self._session.commit()
        return len(mapped)
