from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from chatbi_agent_contracts import QuestionRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="新会话", min_length=1, max_length=255)


class ConversationRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = " ".join(value.split())[:255]
        if not cleaned:
            raise ValueError("title must contain visible characters")
        return cleaned


class ResultSemantic(StrEnum):
    VALUE = "VALUE"
    ZERO = "ZERO"
    NO_ROWS = "NO_ROWS"
    NULL_VALUE = "NULL_VALUE"
    FAILED = "FAILED"


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str
    role: str | None = None


class KpiItem(BaseModel):
    label: str
    value: Any
    unit: str = ""


class KpiPart(BaseModel):
    type: Literal["kpi"] = "kpi"
    items: list[KpiItem]


class ChartPart(BaseModel):
    type: Literal["chart"] = "chart"
    chart_spec: dict[str, Any]
    result_signature: str


class TablePart(BaseModel):
    type: Literal["table"] = "table"
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    result_signature: str


class CitationItem(BaseModel):
    title: str
    version: str
    locator: str
    resource_id: str


class CitationsPart(BaseModel):
    type: Literal["citations"] = "citations"
    items: list[CitationItem]


class EvidencePart(BaseModel):
    type: Literal["evidence"] = "evidence"
    sql: str | None = None
    guard: dict[str, Any]
    oracle: dict[str, Any]
    semantic: dict[str, Any]
    phases: list[dict[str, Any]]


class ErrorPart(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str
    retryable: bool


MessagePart = TextPart | KpiPart | ChartPart | TablePart | CitationsPart | EvidencePart | ErrorPart


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    summary: str
    active_attachment_ids: list[str]
    created_at: datetime
    updated_at: datetime


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    conversation_id: str
    parent_message_id: str | None
    role: str
    content: str
    route: str | None
    status: str
    attachment_ids: list[str]
    context_payload: dict[str, Any]
    response_payload: dict[str, Any]
    trace_payload: dict[str, Any]
    error_code: str | None
    created_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[MessageRead] = Field(default_factory=list)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str
    content: str = Field(default="", max_length=4_000)
    parent_message_id: str | None = None
    client_message_id: str = Field(min_length=8, max_length=128)
    attachment_ids: list[str] = Field(default_factory=list, max_length=8)
    route: QuestionRoute | None = None
    datasource_id: str | None = None
    semantic_model_id: str | None = None


class ChatCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str
    client_message_id: str = Field(min_length=8, max_length=128)


class ChatResponse(BaseModel):
    conversation: ConversationRead
    user_message: MessageRead
    assistant_message: MessageRead
    message_parts: list[MessagePart] = Field(default_factory=list)
    result_semantic: ResultSemantic = ResultSemantic.VALUE


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    conversation_id: str
    filename: str
    extension: str
    mime_type: str
    kind: str
    size_bytes: int
    status: str
    error_code: str | None
    created_at: datetime
    expires_at: datetime
