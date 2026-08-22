from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class GovernanceCoverage(BaseModel):
    source: str
    complete: bool
    warnings: list[str] = Field(default_factory=list)


class CostLedgerEntry(BaseModel):
    id: str
    workspace_id: str
    user_id: str | None = None
    trace_id: str
    request_id: str | None = None
    conversation_id: str | None = None
    route: str | None = None
    capability: str | None = None
    provider: str
    model: str
    status: str
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cost_cny: float = 0
    latency_ms: int = 0
    cache_hit: bool = False
    fallback_count: int = 0
    premium_escalation: bool = False
    retry_count: int = 0
    error_code: str | None = None
    circuit_state: str | None = None
    pricing_version: str | None = None
    source: str
    created_at: datetime


class CostBreakdown(BaseModel):
    key: str
    requests: int
    input_tokens: int
    output_tokens: int
    cost_cny: float
    cache_hits: int
    fallbacks: int
    premium_escalations: int
    errors: int
    average_latency_ms: float


class CostDashboardResponse(BaseModel):
    coverage: GovernanceCoverage
    currency: Literal["CNY"] = "CNY"
    requests: int
    input_tokens: int
    output_tokens: int
    cost_cny: float
    cache_hits: int
    fallbacks: int
    premium_escalations: int
    errors: int
    average_latency_ms: float
    by_workspace: list[CostBreakdown]
    by_user: list[CostBreakdown]
    by_conversation: list[CostBreakdown]
    by_provider: list[CostBreakdown]
    by_model: list[CostBreakdown]
    by_route: list[CostBreakdown]
    entries: list[CostLedgerEntry]


class TraceStageRead(BaseModel):
    stage: str
    status: str
    started_at: datetime
    duration_ms: int = 0
    timing_source: str
    provider: str | None = None
    model: str | None = None
    tool: str | None = None
    sql: str | None = None
    error_code: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceSummaryRead(BaseModel):
    trace_id: str
    workspace_id: str
    user_id: str | None = None
    route: str | None = None
    status: str
    started_at: datetime
    duration_ms: int = 0
    stage_count: int = 0
    provider: str | None = None
    model: str | None = None
    tools: list[str] = Field(default_factory=list)
    has_sql: bool = False
    has_rag: bool = False
    has_agent: bool = False
    has_file: bool = False
    has_vision: bool = False
    artifact_count: int = 0
    error_code: str | None = None


class TraceDashboardResponse(BaseModel):
    coverage: GovernanceCoverage
    trace_granularity: Literal["COMPLETION_RECEIPT_LEVEL", "STAGE_LEVEL"]
    items: list[TraceSummaryRead]


class TraceDetailResponse(BaseModel):
    coverage: GovernanceCoverage
    trace: TraceSummaryRead
    stages: list[TraceStageRead]


class ModelProviderGovernanceRead(BaseModel):
    provider: str
    display_name: str
    model: str | None = None
    configured: bool
    health: str
    circuit_state: str
    circuit_failure_threshold: int
    circuit_cooldown_seconds: float
    requests: int
    errors: int
    average_latency_ms: float
    cost_cny: float
    fallback_rate: float
    premium_ratio: float


class ModelDashboardResponse(BaseModel):
    coverage: GovernanceCoverage
    pricing_version: str
    default_routes: dict[str, list[str]]
    providers: list[ModelProviderGovernanceRead]


class EvaluationGovernanceRun(BaseModel):
    id: str
    source: Literal["DATABASE", "EVIDENCE"]
    suite: str
    version: str | None = None
    source_sha: str | None = None
    status: str
    pass_rate: float | None = None
    result_accuracy: float | None = None
    citation_accuracy: float | None = None
    runtime_calls: int | None = None
    errors: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    evidence_sha256: str | None = None
    executed_at: datetime | None = None


class EvaluationGovernanceDashboardResponse(BaseModel):
    coverage: GovernanceCoverage
    runs: list[EvaluationGovernanceRun]


class ModelInvocationContract(BaseModel):
    """Required append-only ONE_MODEL_GATEWAY ledger contract for the shared migration patch."""

    id: str
    workspace_id: str
    user_id: str
    trace_id: str
    request_id: str
    conversation_id: str | None = None
    route: str
    capability: str
    provider: str
    model: str
    status: Literal["SUCCEEDED", "FAILED", "CANCELLED"]
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cost_cny: float = 0
    latency_ms: int = 0
    cache_hit: bool = False
    fallback_count: int = 0
    retry_count: int = 0
    premium_escalation: bool = False
    error_code: str | None = None
    circuit_state: str
    pricing_version: str | None = None
    created_at: datetime
