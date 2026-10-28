"""Operational commands.

Usage (from `backend/`, after `alembic upgrade head`):

    python -m app.cli seed                 # Yahoo Finance + synthetic portfolio + index
    python -m app.cli seed --skip-market   # offline: synthetic portfolio only
    python -m app.cli seed --excel data.xlsx
    python -m app.cli index-schema
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import delete

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import (
    Company,
    FinancialStatement,
    MarketData,
    PerformanceMetric,
    PortfolioCompany,
)
from app.db.repositories import count_rows_by_table
from app.db.session import get_session_factory
from app.ingestion.excel import ExcelLoader
from app.ingestion.synthetic import SyntheticPortfolioGenerator
from app.ingestion.yahoo import YahooFinanceLoader
from app.rag.embeddings import SentenceTransformerEmbedder
from app.rag.schema_indexer import SchemaIndexer
from app.rag.vector_store import FAISSVectorStore

logger = logging.getLogger("app.cli")

DEFAULT_TICKERS = ("AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "JPM", "BAC", "WMT")


def _index_schema() -> int:
    settings = get_settings()
    store = FAISSVectorStore(
        SentenceTransformerEmbedder(settings.embedding_model), settings.faiss_index_path
    )
    count = SchemaIndexer(store).index()
    logger.info("Indexed %d schema documents into %s", count, settings.faiss_index_path)
    return count


def cmd_seed(args: argparse.Namespace) -> int:
    session = get_session_factory()()
    try:
        if args.reset:
            # Children first to satisfy foreign keys. Query logs are kept.
            for model in (
                PerformanceMetric,
                PortfolioCompany,
                FinancialStatement,
                MarketData,
                Company,
            ):
                session.execute(delete(model))
            session.commit()
            logger.info("Cleared existing domain data")

        if args.excel:
            excel = ExcelLoader(session).load(Path(args.excel))
            logger.info("Excel import: %s", excel)

        if not args.skip_market:
            market = YahooFinanceLoader(session).load(args.tickers, years=args.years)
            logger.info("Yahoo Finance: %s", market)
            if market.failed_tickers:
                logger.warning("Failed tickers: %s", ", ".join(market.failed_tickers))

        portfolio = SyntheticPortfolioGenerator(session, seed=args.seed).generate(
            companies=args.portfolio_companies
        )
        logger.info("Synthetic portfolio: %s", portfolio)

        for table, rows in count_rows_by_table(session).items():
            logger.info("  %-22s %8d rows", table, rows)
    finally:
        session.close()

    if not args.no_index:
        _index_schema()
    return 0


def cmd_index_schema(_: argparse.Namespace) -> int:
    _index_schema()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="Load market data and generate the demo portfolio.")
    seed.add_argument("--tickers", nargs="+", default=list(DEFAULT_TICKERS), metavar="TICKER")
    seed.add_argument("--years", type=int, default=2, help="Years of price history (default: 2).")
    seed.add_argument(
        "--portfolio-companies",
        type=int,
        default=80,
        help="Synthetic private companies to generate (default: 80, ~5k metric rows).",
    )
    seed.add_argument("--seed", type=int, default=42, help="RNG seed for synthetic data.")
    seed.add_argument("--excel", metavar="PATH", help="Optional workbook to import first.")
    seed.add_argument("--skip-market", action="store_true", help="Skip Yahoo Finance (offline).")
    seed.add_argument("--reset", action="store_true", help="Delete existing domain data first.")
    seed.add_argument("--no-index", action="store_true", help="Do not rebuild the schema index.")
    seed.set_defaults(func=cmd_seed)

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
