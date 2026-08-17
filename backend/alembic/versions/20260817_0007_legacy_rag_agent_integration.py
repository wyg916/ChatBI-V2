"""optional legacy RAG and bounded orchestration metadata

Revision ID: 20260817_0007
Revises: 20260817_0006
Create Date: 2026-08-17 22:15:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260817_0007"
down_revision: Union[str, None] = "20260817_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _batch_column() -> sa.Column:
    return sa.Column("migration_batch_id", sa.String(length=64), nullable=True)


def _batch_index(table: str) -> None:
    op.create_index(op.f(f"ix_{table}_migration_batch_id"), table, ["migration_batch_id"])


def upgrade() -> None:
    op.create_table(
        "knowledge_source",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_commit", sa.String(40)),
        _batch_column(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "name"),
    )
    op.create_index(op.f("ix_knowledge_source_workspace_id"), "knowledge_source", ["workspace_id"])
    _batch_index("knowledge_source")
    op.create_table(
        "knowledge_document",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("knowledge_source.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(96)),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("source_path", sa.String(1024), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        _batch_column(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name in ("source_id", "workspace_id", "external_id"):
        op.create_index(op.f(f"ix_knowledge_document_{name}"), "knowledge_document", [name])
    _batch_index("knowledge_document")
    op.create_table(
        "knowledge_document_version",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("knowledge_document.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        _batch_column(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "version"),
    )
    for name in ("document_id", "content_sha256"):
        op.create_index(op.f(f"ix_knowledge_document_version_{name}"), "knowledge_document_version", [name])
    _batch_index("knowledge_document_version")
    op.create_table(
        "knowledge_chunk",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_version_id", sa.String(36), sa.ForeignKey("knowledge_document_version.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        _batch_column(),
        sa.UniqueConstraint("document_version_id", "ordinal"),
    )
    for name in ("document_version_id", "content_sha256"):
        op.create_index(op.f(f"ix_knowledge_chunk_{name}"), "knowledge_chunk", [name])
    _batch_index("knowledge_chunk")
    op.create_table(
        "knowledge_acl",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_version_id", sa.String(36), sa.ForeignKey("knowledge_document_version.id", ondelete="CASCADE"), nullable=False),
        sa.Column("principal_type", sa.String(32), nullable=False),
        sa.Column("principal_value", sa.String(128), nullable=False),
        sa.Column("permission", sa.String(32), nullable=False),
        _batch_column(),
        sa.UniqueConstraint("document_version_id", "principal_type", "principal_value"),
    )
    op.create_index(op.f("ix_knowledge_acl_document_version_id"), "knowledge_acl", ["document_version_id"])
    _batch_index("knowledge_acl")
    op.create_table(
        "knowledge_ingestion_run",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("knowledge_source.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("trace_id", sa.String(96), nullable=False),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(64)),
        _batch_column(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name in ("source_id", "workspace_id", "trace_id"):
        op.create_index(op.f(f"ix_knowledge_ingestion_run_{name}"), "knowledge_ingestion_run", [name])
    _batch_index("knowledge_ingestion_run")
    op.create_table(
        "knowledge_retrieval_run",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.Column("query_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("retrieval_mode", sa.String(96)),
        sa.Column("trace_id", sa.String(96), nullable=False),
        sa.Column("citation_count", sa.Integer(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        _batch_column(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name in ("workspace_id", "user_id", "trace_id"):
        op.create_index(op.f(f"ix_knowledge_retrieval_run_{name}"), "knowledge_retrieval_run", [name])
    _batch_index("knowledge_retrieval_run")
    op.create_table(
        "citation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("retrieval_run_id", sa.String(36), sa.ForeignKey("knowledge_retrieval_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("knowledge_document.id", ondelete="SET NULL")),
        sa.Column("document_version_id", sa.String(36), sa.ForeignKey("knowledge_document_version.id", ondelete="SET NULL")),
        sa.Column("chunk_id", sa.String(36), sa.ForeignKey("knowledge_chunk.id", ondelete="SET NULL")),
        sa.Column("source", sa.String(1024), nullable=False),
        sa.Column("locator", sa.String(512)),
        sa.Column("text_excerpt", sa.Text(), nullable=False),
        sa.Column("score_millionths", sa.Integer(), nullable=False),
        _batch_column(),
    )
    for name in ("retrieval_run_id", "document_id", "document_version_id", "chunk_id"):
        op.create_index(op.f(f"ix_citation_{name}"), "citation", [name])
    _batch_index("citation")
    op.create_table(
        "orchestration_profile",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(96), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("allowed_tools", sa.JSON(), nullable=False),
        sa.Column("max_steps", sa.Integer(), nullable=False),
        sa.Column("timeout_ms", sa.Integer(), nullable=False),
        sa.Column("token_budget", sa.Integer(), nullable=False),
        _batch_column(),
        sa.UniqueConstraint("workspace_id", "code"),
    )
    op.create_index(op.f("ix_orchestration_profile_workspace_id"), "orchestration_profile", ["workspace_id"])
    _batch_index("orchestration_profile")
    op.create_table(
        "orchestration_run",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("orchestration_profile.id", ondelete="SET NULL")),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.Column("route", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("trace_id", sa.String(96), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(64)),
        _batch_column(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("workspace_id", "idempotency_key"),
    )
    for name in ("profile_id", "workspace_id", "user_id", "trace_id"):
        op.create_index(op.f(f"ix_orchestration_run_{name}"), "orchestration_run", [name])
    _batch_index("orchestration_run")
    op.create_table(
        "orchestration_step",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("orchestration_run_id", sa.String(36), sa.ForeignKey("orchestration_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("tool_name", sa.String(96)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        _batch_column(),
        sa.UniqueConstraint("orchestration_run_id", "ordinal"),
    )
    op.create_index(op.f("ix_orchestration_step_orchestration_run_id"), "orchestration_step", ["orchestration_run_id"])
    _batch_index("orchestration_step")
    op.create_table(
        "tool_binding",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("orchestration_profile_id", sa.String(36), sa.ForeignKey("orchestration_profile.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_name", sa.String(96), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        _batch_column(),
        sa.UniqueConstraint("orchestration_profile_id", "tool_name"),
    )
    op.create_index(op.f("ix_tool_binding_orchestration_profile_id"), "tool_binding", ["orchestration_profile_id"])
    _batch_index("tool_binding")
    op.create_table(
        "tool_call",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("orchestration_run_id", sa.String(36), sa.ForeignKey("orchestration_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("orchestration_step_id", sa.String(36), sa.ForeignKey("orchestration_step.id", ondelete="SET NULL")),
        sa.Column("tool_name", sa.String(96), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        _batch_column(),
        sa.UniqueConstraint("orchestration_run_id", "idempotency_key"),
    )
    for name in ("orchestration_run_id", "orchestration_step_id"):
        op.create_index(op.f(f"ix_tool_call_{name}"), "tool_call", [name])
    _batch_index("tool_call")
    op.create_table(
        "prompt_template",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(96), nullable=False),
        sa.Column("purpose", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        _batch_column(),
        sa.UniqueConstraint("workspace_id", "code"),
    )
    op.create_index(op.f("ix_prompt_template_workspace_id"), "prompt_template", ["workspace_id"])
    _batch_index("prompt_template")
    op.create_table(
        "prompt_version",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("prompt_template_id", sa.String(36), sa.ForeignKey("prompt_template.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_commit", sa.String(40)),
        _batch_column(),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("prompt_template_id", "version"),
    )
    op.create_index(op.f("ix_prompt_version_prompt_template_id"), "prompt_version", ["prompt_template_id"])
    _batch_index("prompt_version")


def downgrade() -> None:
    for table in (
        "prompt_version", "prompt_template", "tool_call", "tool_binding", "orchestration_step",
        "orchestration_run", "orchestration_profile", "citation", "knowledge_retrieval_run",
        "knowledge_ingestion_run", "knowledge_acl", "knowledge_chunk", "knowledge_document_version",
        "knowledge_document", "knowledge_source",
    ):
        op.drop_table(table)
