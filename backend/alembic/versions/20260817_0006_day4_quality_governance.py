"""day4 semantic governance, minimal rbac, and audit

Revision ID: 20260817_0006
Revises: 20260817_0005
Create Date: 2026-08-17 20:05:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260817_0006"
down_revision: Union[str, None] = "20260817_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    for name in ("workspace_id", "email", "role", "status"):
        op.create_index(op.f(f"ix_app_user_{name}"), "app_user", [name], unique=name == "email")

    op.create_table(
        "resource_grant",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=36), nullable=False),
        sa.Column("can_read", sa.Boolean(), nullable=False),
        sa.Column("can_query", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "resource_type", "resource_id"),
    )
    for name in ("user_id", "resource_type", "resource_id"):
        op.create_index(op.f(f"ix_resource_grant_{name}"), "resource_grant", [name], unique=False)

    op.create_table(
        "audit_event",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ("workspace_id", "actor_user_id", "actor_email", "action", "resource_type", "resource_id", "status", "created_at"):
        op.create_index(op.f(f"ix_audit_event_{name}"), "audit_event", [name], unique=False)


def downgrade() -> None:
    for name in ("created_at", "status", "resource_id", "resource_type", "action", "actor_email", "actor_user_id", "workspace_id"):
        op.drop_index(op.f(f"ix_audit_event_{name}"), table_name="audit_event")
    op.drop_table("audit_event")
    for name in ("resource_id", "resource_type", "user_id"):
        op.drop_index(op.f(f"ix_resource_grant_{name}"), table_name="resource_grant")
    op.drop_table("resource_grant")
    for name in ("status", "role", "email", "workspace_id"):
        op.drop_index(op.f(f"ix_app_user_{name}"), table_name="app_user")
    op.drop_table("app_user")
