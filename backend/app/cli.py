"""Operational commands.

Usage (from `backend/`, after `alembic upgrade head`):

    python -m app.cli seed                 # Yahoo Finance + SEC 13F holdings + index
    python -m app.cli seed --skip-holdings # companies, prices and statements only
    python -m app.cli seed --excel data.xlsx
    python -m app.cli refresh              # daily top-up: new prices, statements, 13F filings
    python -m app.cli index-schema

All data is real and public: Yahoo Finance for companies, prices and
statements; SEC EDGAR Form 13F filings for fund holdings, with CUSIPs mapped
to tickers by OpenFIGI.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import Company, FinancialStatement, Fund, FundHolding, MarketData
from app.db.repositories import count_rows_by_table
from app.db.session import get_session_factory
from app.ingestion.excel import ExcelLoader
from app.ingestion.sec_13f import DEFAULT_FUND_CIKS, Form13FLoader
from app.ingestion.yahoo import YahooFinanceLoader
from app.rag.embeddings import SentenceTransformerEmbedder
from app.rag.schema_indexer import SchemaIndexer
from app.rag.vector_store import FAISSVectorStore

logger = logging.getLogger("app.cli")

#: 50 of the largest US-listed companies, across every major sector.
DEFAULT_TICKERS = (
    # Technology and communication
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "ORCL", "CRM", "ADBE",
    "AMD", "INTC", "CSCO", "IBM", "QCOM", "NFLX", "TSLA",
    # Financials
    "BRK-B", "JPM", "BAC", "WFC", "GS", "MS", "C", "V", "MA", "AXP",
    # Health care
    "LLY", "UNH", "JNJ", "ABBV", "MRK", "PFE", "TMO",
    # Consumer
    "WMT", "COST", "PG", "KO", "PEP", "MCD", "NKE", "HD", "DIS",
    # Energy and industrials
    "XOM", "CVX", "CAT", "BA", "GE",
    # Telecom
    "VZ", "T",
)  # fmt: skip


def _index_schema() -> int:
    settings = get_settings()
    store = FAISSVectorStore(
        SentenceTransformerEmbedder(settings.embedding_model), settings.faiss_index_path
    )
    count = SchemaIndexer(store).index()
    logger.info("Indexed %d schema documents into %s", count, settings.faiss_index_path)
    return count


def _load_holdings(session: Session, ciks: Sequence[int], quarters: int) -> None:
    settings = get_settings()
    key = settings.openfigi_api_key.get_secret_value() if settings.openfigi_api_key else None
    with httpx.Client(timeout=30.0, follow_redirects=True) as http:
        loader = Form13FLoader(
            session,
            user_agent=settings.sec_edgar_user_agent,
            http=http,
            openfigi_api_key=key,
        )
        holdings = loader.load(ciks, quarters=quarters)
    logger.info("SEC 13F: %s", holdings)
    if holdings.failed_funds:
        logger.warning("Failed funds (CIK): %s", ", ".join(map(str, holdings.failed_funds)))


def _load_market(session: Session, tickers: Sequence[str], years: int) -> None:
    market = YahooFinanceLoader(session).load(tickers, years=years)
    logger.info("Yahoo Finance: %s", market)
    if market.failed_tickers:
        logger.warning("Failed tickers: %s", ", ".join(market.failed_tickers))


def _log_counts(session: Session) -> None:
    for table, rows in count_rows_by_table(session).items():
        logger.info("  %-22s %8d rows", table, rows)


def cmd_seed(args: argparse.Namespace) -> int:
    session = get_session_factory()()
    try:
        if args.reset:
            # Children first to satisfy foreign keys. Query logs and the CUSIP
            # lookup cache are kept.
            for model in (FundHolding, Fund, FinancialStatement, MarketData, Company):
                session.execute(delete(model))
            session.commit()
            logger.info("Cleared existing domain data")

        if args.excel:
            excel = ExcelLoader(session).load(Path(args.excel))
            logger.info("Excel import: %s", excel)

        if not args.skip_market:
            _load_market(session, args.tickers, args.years)
        if not args.skip_holdings:
            _load_holdings(session, args.funds, args.quarters)
        _log_counts(session)
    finally:
        session.close()

    if not args.no_index:
        _index_schema()
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    """Top up every source; existing rows are skipped, so this is cheap to run daily."""
    session = get_session_factory()()
    try:
        tickers = list(
            session.scalars(select(Company.ticker).where(Company.ticker.is_not(None))).all()
        )
        ciks = list(session.scalars(select(Fund.cik)).all())
        _load_market(session, [t for t in tickers if t] or list(DEFAULT_TICKERS), years=1)
        _load_holdings(session, ciks or list(DEFAULT_FUND_CIKS), quarters=args.quarters)
        _log_counts(session)
    finally:
        session.close()
    return 0


def cmd_index_schema(_: argparse.Namespace) -> int:
    _index_schema()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="Load real market data and fund holdings.")
    seed.add_argument("--tickers", nargs="+", default=list(DEFAULT_TICKERS), metavar="TICKER")
    seed.add_argument("--years", type=int, default=2, help="Years of price history (default: 2).")
    seed.add_argument(
        "--funds",
        nargs="+",
        type=int,
        default=list(DEFAULT_FUND_CIKS),
        metavar="CIK",
        help="SEC CIKs of 13F filers (default: 10 well-known funds).",
    )
    seed.add_argument(
        "--quarters", type=int, default=8, help="Quarters of 13F holdings per fund (default: 8)."
    )
    seed.add_argument("--excel", metavar="PATH", help="Optional workbook to import first.")
    seed.add_argument("--skip-market", action="store_true", help="Skip Yahoo Finance.")
    seed.add_argument("--skip-holdings", action="store_true", help="Skip SEC 13F holdings.")
    seed.add_argument("--reset", action="store_true", help="Delete existing domain data first.")
    seed.add_argument("--no-index", action="store_true", help="Do not rebuild the schema index.")
    seed.set_defaults(func=cmd_seed)

    refresh = sub.add_parser("refresh", help="Add new prices, statements and 13F filings.")
    refresh.add_argument(
        "--quarters", type=int, default=2, help="Recent quarters to check per fund (default: 2)."
    )
    refresh.set_defaults(func=cmd_refresh)

    index = sub.add_parser("index-schema", help="Rebuild the schema vector index.")
    index.set_defaults(func=cmd_index_schema)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
