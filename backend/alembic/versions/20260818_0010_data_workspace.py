"""add read-only SQL workspace execution history

Revision ID: 20260818_0010
Revises: 20260818_0009
Create Date: 2026-08-18 18:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260818_0010"
down_revision: Union[str, None] = "20260818_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sql_workspace_run",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("datasource_id", sa.String(length=36), sa.ForeignKey("datasource.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("sql_text", sa.Text(), nullable=False),
        sa.Column("normalized_sql", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("guard_payload", sa.JSON(), nullable=False),
        sa.Column("execution_payload", sa.JSON(), nullable=False),
        sa.Column("oracle_payload", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("verified_answer_id", sa.String(length=36), sa.ForeignKey("verified_answer.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("workspace_id", "user_id", "datasource_id", "operation", "status", "verified_answer_id", "created_at"):
        op.create_index(f"ix_sql_workspace_run_{column}", "sql_workspace_run", [column])


def downgrade() -> None:
    op.drop_table("sql_workspace_run")
