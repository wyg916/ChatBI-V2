from __future__ import annotations

from typing import Any

from chatbi_agent_contracts import QuestionRoute
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.answer_envelope import AnswerEnvelope

class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4_000)
    route: QuestionRoute | None = None
    datasource_id: str | None = None
    semantic_model_id: str | None = None
    row_limit: int | None = Field(default=None, ge=1, le=500)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
    file_evidence: dict[str, Any] | None = None


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    route: QuestionRoute
    trace_id: str
    primary: dict[str, Any]
    shadow: dict[str, Any] | None = None
    fallback_used: bool = False
    feature_modes: dict[str, str]
    security: dict[str, int]
    answer_envelope: AnswerEnvelope | None = None
