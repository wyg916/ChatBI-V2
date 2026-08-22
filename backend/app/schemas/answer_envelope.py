from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AnswerRoute(StrEnum):
    DATA_QUERY = "DATA_QUERY"
    KNOWLEDGE_QUERY = "KNOWLEDGE_QUERY"
    HYBRID_ANALYSIS = "HYBRID_ANALYSIS"
    COMPLEX_ANALYSIS = "COMPLEX_ANALYSIS"
    FILE_QUERY = "FILE_QUERY"
    VISION_QUERY = "VISION_QUERY"
    GENERAL_CHAT = "GENERAL_CHAT"
    CLARIFICATION = "CLARIFICATION"
    UNSUPPORTED = "UNSUPPORTED"


class AnswerResultSemantic(StrEnum):
    VALUE = "VALUE"
    ZERO = "ZERO"
    NO_ROWS = "NO_ROWS"
    NULL_VALUE = "NULL_VALUE"
    FAILED = "FAILED"


class _EnvelopeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnswerKpi(_EnvelopeModel):
    label: str = Field(min_length=1, max_length=160)
    value: Any = None
    unit: str = Field(default="", max_length=40)


class AnswerTable(_EnvelopeModel):
    columns: list[str] = Field(default_factory=list, max_length=200)
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    row_count: int = Field(default=0, ge=0)
    result_signature: str | None = Field(default=None, max_length=256)
    truncated: bool = False


class AnswerCitation(_EnvelopeModel):
    id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=512)
    version: str = Field(min_length=1, max_length=256)
    locator: str = Field(min_length=1, max_length=512)
    resource_id: str = Field(min_length=1, max_length=256)
    href: str | None = Field(default=None, max_length=2_048)

    @field_validator("href")
    @classmethod
    def safe_href(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.startswith("/api/v1/") and "\\" not in value and ".." not in value:
            return value
        if re.match(r"^https?://", value, flags=re.IGNORECASE):
            return value
        raise ValueError("citation href must be an approved HTTP(S) or API URL")


class AnswerArtifact(_EnvelopeModel):
    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=512)
    kind: str = Field(min_length=1, max_length=64)
    media_type: str | None = Field(default=None, max_length=128)
    download_url: str = Field(min_length=1, max_length=2_048)
    size_bytes: int | None = Field(default=None, ge=0)

    @field_validator("download_url")
    @classmethod
    def safe_download_url(cls, value: str) -> str:
        if not value.startswith("/api/v1/") or "\\" in value or ".." in value:
            raise ValueError("artifact download URL must stay inside /api/v1")
        return value


class FileEvidenceItem(_EnvelopeModel):
    attachment_id: str = Field(min_length=1, max_length=256)
    filename: str = Field(min_length=1, max_length=512)
    kind: str = Field(default="FILE", max_length=64)
    locator: str | None = Field(default=None, max_length=512)
    result_signature: str | None = Field(default=None, max_length=256)


class VisualClaimItem(_EnvelopeModel):
    claim: str = Field(min_length=1, max_length=512)
    value: Any = None
    locator: str | None = Field(default=None, max_length=512)
    confidence: float | None = Field(default=None, ge=0, le=1)
    time_range: str | None = Field(default=None, max_length=256)
    dimension: str | None = Field(default=None, max_length=256)


class VisualEvidenceItem(_EnvelopeModel):
    attachment_id: str | None = Field(default=None, max_length=256)
    provider: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=256)
    claims: list[VisualClaimItem] = Field(default_factory=list, max_length=100)
    sanitized_text: str = Field(default="", max_length=40_000)
    sensitive_classification: str = Field(default="NONE", max_length=32)
    injection_detected: bool = False
    signature: str | None = Field(default=None, max_length=256)


class AgentStepItem(_EnvelopeModel):
    ordinal: int = Field(ge=1)
    code: str = Field(min_length=1, max_length=128)
    agent_role: str = Field(min_length=1, max_length=128)
    tool_name: str | None = Field(default=None, max_length=128)
    status: str = Field(min_length=1, max_length=64)
    duration_ms: int = Field(default=0, ge=0)
    result_signature: str | None = Field(default=None, max_length=256)
    error_code: str | None = Field(default=None, max_length=128)


class AnswerWarning(_EnvelopeModel):
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2_000)
    severity: str = Field(default="WARNING", max_length=32)


class AnswerError(_EnvelopeModel):
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2_000)
    retryable: bool = False


class AnswerCost(_EnvelopeModel):
    input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    amount_cny: float = Field(default=0, ge=0)
    exact: bool = False
    pricing_version: str | None = Field(default=None, max_length=128)


class AnswerLatency(_EnvelopeModel):
    total_ms: int = Field(default=0, ge=0)
    model_ms: int | None = Field(default=None, ge=0)
    time_to_first_token_ms: int | None = Field(default=None, ge=0)


class VerificationCheck(_EnvelopeModel):
    code: str = Field(min_length=1, max_length=128)
    passed: bool | None = None
    detail: str | None = Field(default=None, max_length=1_000)


class AnswerVerification(_EnvelopeModel):
    status: str = Field(default="NOT_RUN", max_length=64)
    checks: list[VerificationCheck] = Field(default_factory=list, max_length=100)
    result_signature: str | None = Field(default=None, max_length=256)


class AnswerEnvelope(_EnvelopeModel):
    version: str = "1.0"
    answer_id: str = Field(min_length=1, max_length=256)
    conversation_id: str = Field(min_length=1, max_length=256)
    message_id: str = Field(min_length=1, max_length=256)
    trace_id: str = Field(min_length=1, max_length=256)
    route: AnswerRoute
    status: str = Field(min_length=1, max_length=64)
    result_semantic: AnswerResultSemantic = AnswerResultSemantic.VALUE
    summary: str = Field(default="", max_length=20_000)
    markdown: str = Field(default="", max_length=100_000)
    kpis: list[AnswerKpi] = Field(default_factory=list, max_length=100)
    insights: list[str] = Field(default_factory=list, max_length=100)
    sql: str | None = Field(default=None, max_length=100_000)
    table: AnswerTable | None = None
    chart: dict[str, Any] | None = None
    citations: list[AnswerCitation] = Field(default_factory=list, max_length=200)
    artifacts: list[AnswerArtifact] = Field(default_factory=list, max_length=100)
    file_evidence: list[FileEvidenceItem] = Field(default_factory=list, max_length=100)
    visual_evidence: list[VisualEvidenceItem] = Field(default_factory=list, max_length=50)
    agent_steps: list[AgentStepItem] = Field(default_factory=list, max_length=100)
    warnings: list[AnswerWarning] = Field(default_factory=list, max_length=100)
    errors: list[AnswerError] = Field(default_factory=list, max_length=100)
    cost: AnswerCost = Field(default_factory=AnswerCost)
    latency: AnswerLatency = Field(default_factory=AnswerLatency)
    provider: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=256)
    verification: AnswerVerification = Field(default_factory=AnswerVerification)
    follow_up_suggestions: list[str] = Field(default_factory=list, max_length=20)


__all__ = [
    "AgentStepItem",
    "AnswerArtifact",
    "AnswerCitation",
    "AnswerCost",
    "AnswerEnvelope",
    "AnswerError",
    "AnswerKpi",
    "AnswerLatency",
    "AnswerResultSemantic",
    "AnswerRoute",
    "AnswerTable",
    "AnswerVerification",
    "AnswerWarning",
    "FileEvidenceItem",
    "VerificationCheck",
    "VisualClaimItem",
    "VisualEvidenceItem",
]
