"""Observability: per-request metrics and per-call LLM usage.

`request_metrics` holds one row per query (outcome, tokens, cost, latency by
stage); `llm_calls` one row per completion or cache hit. Both are telemetry,
excluded from the schema the LLM sees (info["queryable"] = False).

Revision ID: 7d41c2b8e9f0
Revises: 5c2e8f1a9b47
Create Date: 2026-11-05 11:44:30.988801
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7d41c2b8e9f0"
down_revision: str | None = "5c2e8f1a9b47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STAGES = ("retrieval", "sql_generation", "sql_execution", "enrichment", "analysis", "verification")


def upgrade() -> None:
    op.create_table(
        "request_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("llm_endpoint", sa.String(length=16), nullable=False),
        sa.Column("llm_calls", sa.Integer(), nullable=False),
        sa.Column("cache_hits", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("retrieval_mode", sa.String(length=32), nullable=True),
        sa.Column("verification_status", sa.String(length=16), nullable=True),
        sa.Column("unsupported_claims", sa.Integer(), nullable=True),
        sa.Column("latency_total_ms", sa.Float(), nullable=False),
        *(sa.Column(f"latency_{stage}_ms", sa.Float(), nullable=True) for stage in _STAGES),
        sa.PrimaryKeyConstraint("id"),
        info={"queryable": False},
    )
    op.create_index("ix_request_metrics_created_at", "request_metrics", ["created_at"])

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_metric_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("cached", sa.Boolean(), nullable=False),
        sa.Column("tokens_estimated", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["request_metric_id"], ["request_metrics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        info={"queryable": False},
    )
    op.create_index("ix_llm_calls_request_metric_id", "llm_calls", ["request_metric_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_request_metric_id", table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_index("ix_request_metrics_created_at", table_name="request_metrics")
    op.drop_table("request_metrics")
