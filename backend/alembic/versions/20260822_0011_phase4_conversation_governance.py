"""add Phase 4 conversation, project, share, and batch governance

Revision ID: 20260822_0011
Revises: 20260818_0010
Create Date: 2026-08-22 17:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260822_0011"
down_revision: Union[str, None] = "20260818_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "user_id", "name", name="uq_project_owner_name"),
    )
    for column in ("workspace_id", "user_id", "archived_at", "created_at", "updated_at"):
        op.create_index(op.f(f"ix_project_{column}"), "project", [column])

    with op.batch_alter_table("conversation") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_conversation_project_id", "project", ["project_id"], ["id"], ondelete="SET NULL",
        )
        batch_op.create_index(op.f("ix_conversation_project_id"), ["project_id"])
        batch_op.create_index(op.f("ix_conversation_pinned_at"), ["pinned_at"])
        batch_op.create_index(op.f("ix_conversation_archived_at"), ["archived_at"])

    op.create_table(
        "conversation_share",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("conversation_id", sa.String(length=36), sa.ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "conversation_id", "workspace_id", "created_by_user_id", "token_hash", "expires_at", "revoked_at", "created_at",
    ):
        op.create_index(op.f(f"ix_conversation_share_{column}"), "conversation_share", [column])


def downgrade() -> None:
    op.drop_table("conversation_share")
    with op.batch_alter_table("conversation") as batch_op:
        batch_op.drop_index(op.f("ix_conversation_archived_at"))
        batch_op.drop_index(op.f("ix_conversation_pinned_at"))
        batch_op.drop_index(op.f("ix_conversation_project_id"))
        batch_op.drop_constraint("fk_conversation_project_id", type_="foreignkey")
        batch_op.drop_column("archived_at")
        batch_op.drop_column("pinned_at")
        batch_op.drop_column("project_id")
    op.drop_table("project")
