"""verified answer and dashboard libraries

Revision ID: 20260817_0002
Revises: 20260816_0001
Create Date: 2026-08-17 16:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260817_0002"
down_revision: Union[str, None] = "20260816_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "verified_answer",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("question", sa.String(length=512), nullable=False),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column("sql_synced", sa.Boolean(), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("owner_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("accuracy_percent", sa.Float(), nullable=False),
        sa.Column("adoption_count", sa.Integer(), nullable=False),
        sa.Column("monthly_adoption_count", sa.Integer(), nullable=False),
        sa.Column("is_favorite", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_verified_answer_workspace_id"), "verified_answer", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_verified_answer_status"), "verified_answer", ["status"], unique=False)
    op.create_index(op.f("ix_verified_answer_is_favorite"), "verified_answer", ["is_favorite"], unique=False)
    op.create_index(op.f("ix_verified_answer_sort_order"), "verified_answer", ["sort_order"], unique=False)

    op.create_table(
        "dashboard",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("card_count", sa.Integer(), nullable=False),
        sa.Column("is_shared", sa.Boolean(), nullable=False),
        sa.Column("refresh_count_today", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trend_variant", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dashboard_workspace_id"), "dashboard", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_dashboard_is_shared"), "dashboard", ["is_shared"], unique=False)
    op.create_index(op.f("ix_dashboard_sort_order"), "dashboard", ["sort_order"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_dashboard_sort_order"), table_name="dashboard")
    op.drop_index(op.f("ix_dashboard_is_shared"), table_name="dashboard")
    op.drop_index(op.f("ix_dashboard_workspace_id"), table_name="dashboard")
    op.drop_table("dashboard")
    op.drop_index(op.f("ix_verified_answer_sort_order"), table_name="verified_answer")
    op.drop_index(op.f("ix_verified_answer_is_favorite"), table_name="verified_answer")
    op.drop_index(op.f("ix_verified_answer_status"), table_name="verified_answer")
    op.drop_index(op.f("ix_verified_answer_workspace_id"), table_name="verified_answer")
    op.drop_table("verified_answer")
