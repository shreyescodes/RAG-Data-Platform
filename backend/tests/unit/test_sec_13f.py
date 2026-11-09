"""SEC 13F ingestion: parsing, filing selection and an end-to-end load over a mocked network."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Fund, FundHolding, SecurityIdentifier
from app.ingestion import sec_13f
from app.ingestion.sec_13f import (
    Form13FLoader,
    OpenFigiClient,
    Position,
    latest_quarterly_filings,
    normalize_ticker,
    parse_information_table,
    reported_in_thousands,
)

ARK_CIK = 1697748
TSLA, AMD, PRIVATE = "88160R101", "007903107", "84615Q103"


def _row(
    name: str, cusip: str, value: int, shares: int, *, put_call: str = "", kind: str = "SH"
) -> str:
    option = f"<putCall>{put_call}</putCall>" if put_call else ""
    return f"""
  <infoTable>
    <nameOfIssuer>{name}</nameOfIssuer><titleOfClass>COM</titleOfClass><cusip>{cusip}</cusip>
    <value>{value}</value>
    <shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt><sshPrnamtType>{kind}</sshPrnamtType></shrsOrPrnAmt>
    {option}<investmentDiscretion>SOLE</investmentDiscretion>
  </infoTable>"""


def _table(*rows: str) -> bytes:
    return (
        '<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">'
        + "".join(rows)
        + "</informationTable>"
    ).encode()


# Real figures from ARK's 13F for 2026-06-30; Tesla is split over two rows.
Q2_TABLE = _table(
    _row("Tesla Inc", TSLA, 1_000_000_000, 2_377_600),
    _row("Tesla Inc", TSLA, 160_772_073, 382_200),
    _row("Advanced Micro Devices Inc", AMD, 822_826_048, 1_416_443),
    _row("Space Exploration Technologies Corp", PRIVATE, 765_113_281, 4_478_013),
    _row("Tesla Inc", TSLA, 5_000_000, 10_000, put_call="Call"),
)
Q1_TABLE = _table(_row("Tesla Inc", TSLA, 900_000_000, 2_759_800))

SUBMISSIONS = {
    "name": "ARK Investment Management LLC",
    "filings": {
        "recent": {
            "form": ["13F-HR", "10-K", "13F-HR/A", "13F-HR", "13F-HR"],
            "accessionNumber": ["acc-q2", "acc-10k", "acc-q2-amend", "acc-q1", "acc-q4"],
            "reportDate": ["2026-06-30", "2025-12-31", "2026-06-30", "2026-03-31", "2025-12-31"],
            "filingDate": ["2026-08-14", "2026-02-01", "2026-09-01", "2026-05-15", "2026-02-14"],
        }
    },
}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    # Throttling and back-off sleeps would only slow the tests down.
    monkeypatch.setattr("app.ingestion.sec_13f.time.sleep", lambda _seconds: None)


@pytest.fixture
def clean_db(db: Session) -> Iterator[Session]:
    yield db
    fund_ids = select(Fund.id).where(Fund.cik == ARK_CIK).scalar_subquery()
    db.execute(delete(FundHolding).where(FundHolding.fund_id.in_(fund_ids)))
    db.execute(delete(Fund).where(Fund.cik == ARK_CIK))
    db.execute(delete(SecurityIdentifier).where(SecurityIdentifier.cusip.in_([TSLA, AMD, PRIVATE])))
    db.commit()


class FakeNetwork:
    """Serves SEC EDGAR and OpenFIGI responses; records every request."""

    def __init__(self, *, fail_submissions: bool = False) -> None:
        self.requests: list[httpx.Request] = []
        self.fail_submissions = fail_submissions

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.endswith(f"CIK{ARK_CIK:010d}.json"):
            if self.fail_submissions:
                return httpx.Response(500)
            return httpx.Response(200, json=SUBMISSIONS)
        if url.endswith("/index.json"):
            items = [
                {"name": "primary_doc.xml", "size": "5000"},
                {"name": "table.xml", "size": "9000"},
            ]
            return httpx.Response(200, json={"directory": {"item": items}})
        if url.endswith("/accq2/table.xml"):
            return httpx.Response(200, content=Q2_TABLE)
        if url.endswith("/accq1/table.xml"):
            return httpx.Response(200, content=Q1_TABLE)
        if url == sec_13f.OPENFIGI_URL:
            known = {TSLA: "TSLA", AMD: "AMD"}
            answers = []
            for job in json.loads(request.content):
                ticker = known.get(job["idValue"])
                answers.append(
                    {"data": [{"ticker": ticker, "exchCode": "US", "name": ticker}]}
                    if ticker
                    else {"warning": "No identifier found."}
                )
            return httpx.Response(200, json=answers)
        return httpx.Response(404)

    def count(self, fragment: str) -> int:
        return sum(fragment in str(r.url) for r in self.requests)


def _loader(session: Session, network: FakeNetwork) -> Form13FLoader:
    http = httpx.Client(transport=httpx.MockTransport(network))
    return Form13FLoader(
        session,
        user_agent="tests contact@example.com",
        http=http,
        openfigi=OpenFigiClient(http),
        sec_request_interval=0,
    )


# --- Parsing -----------------------------------------------------------------------


def test_split_rows_are_summed_and_options_kept_apart() -> None:
    positions = {(p.cusip, p.put_call): p for p in parse_information_table(Q2_TABLE)}

    assert len(positions) == 4
    tesla = positions[(TSLA, None)]
    assert tesla.value_usd == 1_160_772_073
    assert tesla.shares == 2_759_800
    assert tesla.issuer_name == "Tesla Inc"
    assert positions[(TSLA, "Call")].value_usd == 5_000_000


def test_values_can_be_scaled() -> None:
    (position,) = parse_information_table(Q1_TABLE, value_multiplier=1000)
    assert position.value_usd == 900_000_000_000


def test_latest_quarterly_filings_skip_amendments_and_other_forms() -> None:
    filings = latest_quarterly_filings(SUBMISSIONS, quarters=2)
    assert [(f.accession_number, f.report_date) for f in filings] == [
        ("acc-q2", dt.date(2026, 6, 30)),
        ("acc-q1", dt.date(2026, 3, 31)),
    ]
    assert len(latest_quarterly_filings(SUBMISSIONS, quarters=10)) == 3


def _position(value: float, shares: int) -> Position:
    return Position("X", "COM", "000000000", shares, "SH", None, value)


def test_values_reported_in_thousands_are_detected() -> None:
    # Natera at $0.27 a share is a thousands-of-dollars report, not a real price.
    assert reported_in_thousands([_position(864_923, 3_186_306), _position(281_613, 589_680)])
    assert not reported_in_thousands([_position(65_950_296_923, 227_917_808)])
    assert not reported_in_thousands([])


def test_tickers_are_normalised_to_yahoo_style() -> None:
    assert normalize_ticker("BRK/B") == "BRK-B"
    assert normalize_ticker(" aapl ") == "AAPL"


# --- Loading ---------------------------------------------------------------------------


def test_load_stores_holdings_with_weights_and_tickers(clean_db: Session) -> None:
    network = FakeNetwork()
    report = _loader(clean_db, network).load([ARK_CIK], quarters=2)

    assert (report.funds, report.filings, report.holdings) == (1, 2, 5)
    assert report.failed_funds == []
    fund = clean_db.scalar(select(Fund).where(Fund.cik == ARK_CIK))
    assert fund is not None
    assert fund.name == "ARK Investment Management LLC"

    q2 = clean_db.scalars(
        select(FundHolding).where(
            FundHolding.fund_id == fund.id, FundHolding.report_date == dt.date(2026, 6, 30)
        )
    ).all()
    assert sum(h.portfolio_pct or 0 for h in q2) == pytest.approx(100, abs=0.01)
    by_key = {(h.cusip, h.put_call): h for h in q2}
    assert by_key[(TSLA, None)].ticker == "TSLA"
    assert by_key[(TSLA, None)].filing_date == dt.date(2026, 8, 14)
    assert by_key[(TSLA, None)].accession_number == "acc-q2"
    assert by_key[(AMD, None)].ticker == "AMD"
    assert by_key[(PRIVATE, None)].ticker is None  # not listed in the US

    # The negative lookup is cached too, so it is never asked about again.
    cached = clean_db.get(SecurityIdentifier, PRIVATE)
    assert cached is not None
    assert cached.ticker is None


def test_reloading_is_idempotent_and_reuses_the_ticker_cache(clean_db: Session) -> None:
    _loader(clean_db, FakeNetwork()).load([ARK_CIK], quarters=2)

    network = FakeNetwork()
    report = _loader(clean_db, network).load([ARK_CIK], quarters=2)

    assert (report.filings, report.holdings) == (0, 0)
    assert network.count("openfigi") == 0
    assert network.count("table.xml") == 0


def test_one_failing_fund_does_not_abort_the_run(clean_db: Session) -> None:
    report = _loader(clean_db, FakeNetwork(fail_submissions=True)).load([ARK_CIK], quarters=2)
    assert report.failed_funds == [ARK_CIK]
    assert report.holdings == 0


def test_openfigi_retries_when_rate_limited() -> None:
    answers = iter([httpx.Response(429), httpx.Response(200, json=[{"data": []}])])
    http = httpx.Client(transport=httpx.MockTransport(lambda _request: next(answers)))
    assert OpenFigiClient(http).lookup([PRIVATE]) == {PRIVATE: (None, None)}


def test_foreign_issuers_are_looked_up_as_cins() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        jobs = json.loads(request.content)
        seen.extend(job["idType"] for job in jobs)
        return httpx.Response(
            200, json=[{"data": [{"ticker": "CB", "exchCode": "US"}]}] * len(jobs)
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    assert OpenFigiClient(http).lookup(["H1467J104", TSLA])["H1467J104"] == ("CB", None)
    assert seen == ["ID_CINS", "ID_CUSIP"]
