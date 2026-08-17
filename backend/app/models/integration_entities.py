import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeSource(Base):
    __tablename__ = "knowledge_source"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    source_commit: Mapped[str | None] = mapped_column(String(40))
    migration_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_document"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("knowledge_source.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(96), index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    migration_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KnowledgeDocumentVersion(Base):
    __tablename__ = "knowledge_document_version"
    __table_args__ = (UniqueConstraint("document_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_document.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    migration_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"
    __table_args__ = (UniqueConstraint("document_version_id", "ordinal"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("knowledge_document_version.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    locator: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    migration_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)


class KnowledgeAcl(Base):
    __tablename__ = "knowledge_acl"
    __table_args__ = (UniqueConstraint("document_version_id", "principal_type", "principal_value"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("knowledge_document_version.id", ondelete="CASCADE"), index=True)
    principal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    principal_value: Mapped[str] = mapped_column(String(128), nullable=False)
    permission: Mapped[str] = mapped_column(String(32), nullable=False, default="READ")
    migration_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)


class KnowledgeIngestionRun(Base):
    __tablename__ = "knowledge_ingestion_run"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("knowledge_source.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64))
    migration_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KnowledgeRetrievalRun(Base):
    __tablename__ = "knowledge_retrieval_run"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"), index=True)
    query_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    retrieval_mode: Mapped[str | None] = mapped_column(String(96))
    trace_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    citation_count: Mapped[int] = mapped_column(Integer, default=0)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    migration_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Citation(Base):
    __tablename__ = "citation"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    retrieval_run_id: Mapped[str] = mapped_column(ForeignKey("knowledge_retrieval_run.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_document.id", ondelete="SET NULL"), index=True)
    document_version_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_document_version.id", ondelete="SET NULL"), index=True)
    chunk_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_chunk.id", ondelete="SET NULL"), index=True)
    source: Mapped[str] = mapped_column(String(1024), nullable=False)
    locator: Mapped[str | None] = mapped_column(String(512))
    text_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    score_millionths: Mapped[int] = mapped_column(Integer, default=0)
    migration_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)


class OrchestrationProfile(Base):
    __tablename__ = "orchestration_profile"
    __table_args__ = (UniqueConstraint("workspace_id", "code"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    allowed_tools: Mapped[list] = mapped_column(JSON, default=list)
    max_steps: Mapped[int] = mapped_column(Integer, default=8)
    max_tool_calls: Mapped[int] = mapped_column(Integer, default=12)
    max_replan: Mapped[int] = mapped_column(Integer, default=2)
    max_agent_depth: Mapped[int] = mapped_column(Integer, default=2)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=30000)
    token_budget: Mapped[int] = mapped_column(Integer, default=6000)
    migration_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)


class OrchestrationRun(Base):
    __tablename__ = "orchestration_run"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    profile_id: Mapped[str | None] = mapped_column(ForeignKey("orchestration_profile.id", ondelete="SET NULL"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("app_user.id", ondelete="SET NULL"), index=True)
    route: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64))
    ttft_ms: Mapped[int] = mapped_column(Integer, default=0)
    total_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    tool_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    trace_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    migration_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrchestrationStep(Base):
    __tablename__ = "orchestration_step"
    __table_args__ = (UniqueConstraint("orchestration_run_id", "ordinal"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    orchestration_run_id: Mapped[str] = mapped_column(ForeignKey("orchestration_run.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(96))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    migration_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)


class ToolBinding(Base):
    __tablename__ = "tool_binding"
    __table_args__ = (UniqueConstraint("orchestration_profile_id", "tool_name"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    orchestration_profile_id: Mapped[str] = mapped_column(ForeignKey("orchestration_profile.id", ondelete="CASCADE"), index=True)
    tool_name: Mapped[str] = mapped_column(String(96), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    migration_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)


class ToolCall(Base):
    __tablename__ = "tool_call"
    __table_args__ = (UniqueConstraint("orchestration_run_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    orchestration_run_id: Mapped[str] = mapped_column(ForeignKey("orchestration_run.id", ondelete="CASCADE"), index=True)
    orchestration_step_id: Mapped[str | None] = mapped_column(ForeignKey("orchestration_step.id", ondelete="SET NULL"), index=True)
    tool_name: Mapped[str] = mapped_column(String(96), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    response_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    migration_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)


class PromptTemplate(Base):
    __tablename__ = "prompt_template"
    __table_args__ = (UniqueConstraint("workspace_id", "code"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(96), nullable=False)
    purpose: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    migration_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)


class PromptVersion(Base):
    __tablename__ = "prompt_version"
    __table_args__ = (UniqueConstraint("prompt_template_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    prompt_template_id: Mapped[str] = mapped_column(ForeignKey("prompt_template.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(96), nullable=False, default="CHATBI_V1_REIMPLEMENTED")
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source_commit: Mapped[str | None] = mapped_column(String(40))
    migration_batch_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
