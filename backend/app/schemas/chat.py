from __future__ import annotations

from datetime import datetime
from typing import Any

from chatbi_agent_contracts import QuestionRoute
from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="新会话", min_length=1, max_length=255)


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


class ChatResponse(BaseModel):
    conversation: ConversationRead
    user_message: MessageRead
    assistant_message: MessageRead


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
