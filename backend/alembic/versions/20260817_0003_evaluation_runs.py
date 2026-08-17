"""evaluation center records

Revision ID: 20260817_0003
Revises: 20260817_0002
Create Date: 2026-08-17 14:50:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260817_0003"
down_revision: Union[str, None] = "20260817_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evaluation_run",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("release_name", sa.String(length=255), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("golden_set_count", sa.Integer(), nullable=False),
        sa.Column("sql_generation_rate", sa.Float(), nullable=False),
        sa.Column("result_accuracy", sa.Float(), nullable=False),
        sa.Column("semantic_accuracy", sa.Float(), nullable=False),
        sa.Column("relevance_accuracy", sa.Float(), nullable=False),
        sa.Column("average_response_seconds", sa.Float(), nullable=False),
        sa.Column("error_distribution", sa.JSON(), nullable=False),
        sa.Column("trend_points", sa.JSON(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_evaluation_run_workspace_id"), "evaluation_run", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_evaluation_run_status"), "evaluation_run", ["status"], unique=False)
    op.create_index(op.f("ix_evaluation_run_is_current"), "evaluation_run", ["is_current"], unique=False)
    op.create_index(op.f("ix_evaluation_run_sort_order"), "evaluation_run", ["sort_order"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_evaluation_run_sort_order"), table_name="evaluation_run")
    op.drop_index(op.f("ix_evaluation_run_is_current"), table_name="evaluation_run")
    op.drop_index(op.f("ix_evaluation_run_status"), table_name="evaluation_run")
    op.drop_index(op.f("ix_evaluation_run_workspace_id"), table_name="evaluation_run")
    op.drop_table("evaluation_run")
