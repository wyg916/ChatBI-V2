"""V1.3.1 functional settings, provider runtime and invitations.

Revision ID: 20260828_0013
Revises: 20260822_0012
"""
from alembic import op
import sqlalchemy as sa

revision = "20260828_0013"
down_revision = "20260822_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_setting",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("query_security", sa.JSON(), nullable=False),
        sa.Column("workspace_config", sa.JSON(), nullable=False),
        sa.Column("appearance", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "provider_runtime_setting",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("healthy", sa.Boolean()),
        sa.Column("health_message", sa.String(255)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("cost_policy", sa.String(32), nullable=False, server_default="STANDARD"),
        sa.Column("updated_by", sa.String(36), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "provider_id"),
    )
    op.create_index("ix_provider_runtime_workspace", "provider_runtime_setting", ["workspace_id"])
    op.create_index("ix_provider_runtime_provider", "provider_runtime_setting", ["provider_id"])
    op.create_table(
        "workspace_invitation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_workspace_invitation_workspace", "workspace_invitation", ["workspace_id"])
    op.create_index("ix_workspace_invitation_email", "workspace_invitation", ["email"])
    op.create_index("ix_workspace_invitation_status", "workspace_invitation", ["status"])
    op.create_index("ix_workspace_invitation_expires", "workspace_invitation", ["expires_at"])


def downgrade() -> None:
    op.drop_table("workspace_invitation")
    op.drop_table("provider_runtime_setting")
    op.drop_table("workspace_setting")
