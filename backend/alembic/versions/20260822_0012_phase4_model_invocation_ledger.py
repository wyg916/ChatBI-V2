"""add the sanitized Phase 4 model invocation ledger

Revision ID: 20260822_0012
Revises: 20260822_0011
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_0012"
down_revision = "20260822_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_invocation",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(length=64)),
        sa.Column("route", sa.String(length=64), nullable=False, server_default="UNSPECIFIED"),
        sa.Column("capability", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False, server_default="unknown"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_cny", sa.Float(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fallback_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("premium_escalation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_code", sa.String(length=96)),
        sa.Column("circuit_state", sa.String(length=16), nullable=False, server_default="UNKNOWN"),
        sa.Column("pricing_version", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "workspace_id", "user_id", "trace_id", "request_id", "conversation_id", "route", "capability",
        "provider", "model", "status", "error_code", "created_at",
    ):
        op.create_index(f"ix_model_invocation_{column}", "model_invocation", [column])


def downgrade() -> None:
    op.drop_table("model_invocation")
