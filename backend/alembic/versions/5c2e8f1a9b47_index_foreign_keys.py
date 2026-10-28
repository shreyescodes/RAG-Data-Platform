"""Index foreign keys and query log timestamps; drop redundant PK indexes.

Primary keys are already indexed by their constraint, so the `ix_<table>_id`
indexes created by the initial migration only cost write throughput.

Revision ID: 5c2e8f1a9b47
Revises: 0993bfe37a5d
Create Date: 2026-10-28 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "5c2e8f1a9b47"
down_revision: str | None = "0993bfe37a5d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PK_TABLES = (
    "companies",
    "financial_statements",
    "market_data",
    "performance_metrics",
    "portfolio_companies",
    "query_logs",
)

_NEW_INDEXES = (
    ("ix_financial_statements_company_id", "financial_statements", "company_id"),
    ("ix_portfolio_companies_company_id", "portfolio_companies", "company_id"),
    ("ix_performance_metrics_portfolio_company_id", "performance_metrics", "portfolio_company_id"),
    ("ix_query_logs_created_at", "query_logs", "created_at"),
)


def upgrade() -> None:
    for table in _PK_TABLES:
        op.drop_index(f"ix_{table}_id", table_name=table)
    for name, table, column in _NEW_INDEXES:
        op.create_index(name, table, [column], unique=False)


def downgrade() -> None:
    for name, table, _ in reversed(_NEW_INDEXES):
        op.drop_index(name, table_name=table)
    for table in _PK_TABLES:
        op.create_index(f"ix_{table}_id", table, ["id"], unique=False)
