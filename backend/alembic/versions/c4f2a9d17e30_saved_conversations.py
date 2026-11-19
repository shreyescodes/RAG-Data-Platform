"""Save answers and scope query history to the visitor who asked.

Revision ID: c4f2a9d17e30
Revises: a8d3e6f1c2b4
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4f2a9d17e30"
down_revision: str | None = "a8d3e6f1c2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("query_logs", sa.Column("visitor_id", sa.String(length=64), nullable=True))
    op.add_column("query_logs", sa.Column("conversation_id", sa.String(length=64), nullable=True))
    op.add_column("query_logs", sa.Column("response_json", sa.Text(), nullable=True))
    op.create_index(op.f("ix_query_logs_visitor_id"), "query_logs", ["visitor_id"])
    op.create_index(op.f("ix_query_logs_conversation_id"), "query_logs", ["conversation_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_query_logs_conversation_id"), table_name="query_logs")
    op.drop_index(op.f("ix_query_logs_visitor_id"), table_name="query_logs")
    op.drop_column("query_logs", "response_json")
    op.drop_column("query_logs", "conversation_id")
    op.drop_column("query_logs", "visitor_id")
