"""add Phase 2 authenticated chat, conversations and attachments

Revision ID: 20260818_0009
Revises: 20260817_0008
Create Date: 2026-08-18 02:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260818_0009"
down_revision: Union[str, None] = "20260817_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("password_hash", sa.String(length=512), nullable=True))
    op.add_column("app_user", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "auth_session",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("client_ip_hash", sa.String(length=64), nullable=True),
    )
    for column in ("user_id", "workspace_id", "token_hash", "expires_at", "revoked_at"):
        op.create_index(f"ix_auth_session_{column}", "auth_session", [column])

    op.create_table(
        "login_attempt",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("identity_hash", sa.String(length=64), nullable=False),
        sa.Column("client_ip_hash", sa.String(length=64), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("identity_hash", "client_ip_hash", "succeeded", "created_at"):
        op.create_index(f"ix_login_attempt_{column}", "login_attempt", [column])

    op.create_table(
        "conversation",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("slot_state", sa.JSON(), nullable=False),
        sa.Column("active_attachment_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("workspace_id", "user_id", "created_at", "updated_at"):
        op.create_index(f"ix_conversation_{column}", "conversation", [column])

    op.create_table(
        "chat_message",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("conversation_id", sa.String(length=36), sa.ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_message_id", sa.String(length=36), sa.ForeignKey("chat_message.id", ondelete="SET NULL"), nullable=True),
        sa.Column("client_message_id", sa.String(length=128), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("route", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attachment_ids", sa.JSON(), nullable=False),
        sa.Column("context_payload", sa.JSON(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("trace_payload", sa.JSON(), nullable=False),
        sa.Column("query_run_id", sa.String(length=36), sa.ForeignKey("query_run.id", ondelete="SET NULL"), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id", "client_message_id", name="uq_chat_message_conversation_client"),
    )
    for column in ("conversation_id", "workspace_id", "user_id", "parent_message_id", "client_message_id", "role", "route", "status", "query_run_id", "error_code", "created_at"):
        op.create_index(f"ix_chat_message_{column}", "chat_message", [column])

    op.create_table(
        "attachment",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), sa.ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("extension", sa.String(length=16), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("extracted_payload", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("workspace_id", "user_id", "conversation_id", "extension", "kind", "sha256", "status", "created_at", "expires_at"):
        op.create_index(f"ix_attachment_{column}", "attachment", [column])


def downgrade() -> None:
    op.drop_table("attachment")
    op.drop_table("chat_message")
    op.drop_table("conversation")
    op.drop_table("login_attempt")
    op.drop_table("auth_session")
    op.drop_column("app_user", "password_changed_at")
    op.drop_column("app_user", "password_hash")
