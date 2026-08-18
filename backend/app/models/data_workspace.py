from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SqlWorkspaceRun(Base):
    """Auditable, workspace-scoped execution history for the read-only SQL workspace."""

    __tablename__ = "sql_workspace_run"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    datasource_id: Mapped[str] = mapped_column(ForeignKey("datasource.id", ondelete="RESTRICT"), index=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sql_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_sql: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    guard_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    execution_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    oracle_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    verified_answer_id: Mapped[str | None] = mapped_column(
        ForeignKey("verified_answer.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
