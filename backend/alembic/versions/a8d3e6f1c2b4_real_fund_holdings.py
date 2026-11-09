"""Replace the synthetic private-equity tables with real SEC 13F fund holdings.

Drops portfolio_companies and performance_metrics (generated data) and adds
funds, fund_holdings and the internal security_identifiers lookup cache.
Downgrading restores the old tables empty; their data is not recoverable.

Revision ID: a8d3e6f1c2b4
Revises: 7d41c2b8e9f0
Create Date: 2026-11-09 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a8d3e6f1c2b4"
down_revision: str | None = "7d41c2b8e9f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_performance_metrics_portfolio_company_id", table_name="performance_metrics")
    op.drop_table("performance_metrics")
    op.drop_index("ix_portfolio_companies_company_id", table_name="portfolio_companies")
    op.drop_table("portfolio_companies")

    op.create_table(
        "funds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cik", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cik"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "fund_holdings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fund_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("accession_number", sa.String(length=25), nullable=False),
        sa.Column("issuer_name", sa.String(length=255), nullable=False),
        sa.Column("title_of_class", sa.String(length=100), nullable=True),
        sa.Column("cusip", sa.String(length=9), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=True),
        sa.Column("shares", sa.BigInteger(), nullable=True),
        sa.Column("share_type", sa.String(length=3), nullable=True),
        sa.Column("put_call", sa.String(length=4), nullable=True),
        sa.Column("value_usd", sa.Float(), nullable=True),
        sa.Column("portfolio_pct", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["fund_id"], ["funds.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fund_holdings_fund_id", "fund_holdings", ["fund_id"], unique=False)
    op.create_index("ix_fund_holdings_ticker", "fund_holdings", ["ticker"], unique=False)
    op.create_table(
        "security_identifiers",
        sa.Column("cusip", sa.String(length=9), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("looked_up_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("cusip"),
    )


def downgrade() -> None:
    op.drop_table("security_identifiers")
    op.drop_index("ix_fund_holdings_ticker", table_name="fund_holdings")
    op.drop_index("ix_fund_holdings_fund_id", table_name="fund_holdings")
    op.drop_table("fund_holdings")
    op.drop_table("funds")

    op.create_table(
        "portfolio_companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("investment_date", sa.Date(), nullable=False),
        sa.Column("exit_date", sa.Date(), nullable=True),
        sa.Column("investment_amount", sa.Float(), nullable=True),
        sa.Column("current_valuation", sa.Float(), nullable=True),
        sa.Column("ownership_percentage", sa.Float(), nullable=True),
        sa.Column("investment_stage", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_portfolio_companies_company_id", "portfolio_companies", ["company_id"], unique=False
    )
    op.create_table(
        "performance_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_company_id", sa.Integer(), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("arr", sa.Float(), nullable=True),
        sa.Column("mrr", sa.Float(), nullable=True),
        sa.Column("customer_count", sa.Integer(), nullable=True),
        sa.Column("churn_rate", sa.Float(), nullable=True),
        sa.Column("cac", sa.Float(), nullable=True),
        sa.Column("ltv", sa.Float(), nullable=True),
        sa.Column("burn_rate", sa.Float(), nullable=True),
        sa.Column("runway_months", sa.Float(), nullable=True),
        sa.Column("revenue_multiple", sa.Float(), nullable=True),
        sa.Column("ebitda_multiple", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["portfolio_company_id"], ["portfolio_companies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_performance_metrics_portfolio_company_id",
        "performance_metrics",
        ["portfolio_company_id"],
        unique=False,
    )
