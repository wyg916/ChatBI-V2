from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LinkedObject(BaseModel):
    object_type: str
    object_id: str
    name: str
    label: str
    qualified_name: str | None = None
    score: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)


class SecurityPolicy(BaseModel):
    read_only: bool = True
    single_statement: bool = True
    allowed_statement_types: list[str] = Field(default_factory=lambda: ["SELECT", "WITH_SELECT"])
    row_limit: int = 500
    timeout_ms: int = 8000
    allowed_schemas: list[str] = Field(default_factory=list)
    allowed_tables: list[str] = Field(default_factory=list)
    allowed_columns: dict[str, list[str]] = Field(default_factory=dict)


class QueryContext(BaseModel):
    request_id: str = "SYSTEM"
    trace_id: str = "TRACE-SYSTEM"
    route: str = "DATA_QUERY"
    user_id: str = "SYSTEM"
    conversation_id: str | None = None
    permission_hash: str = "system"
    workspace_id: str
    workspace_name: str
    datasource_id: str
    datasource_name: str
    dialect: Literal["postgresql", "mysql"]
    schema_name: str | None = None
    semantic_model_id: str
    semantic_model_name: str
    semantic_model_version: int
    cache_role: str = "SYSTEM"
    knowledge_version: str = "none"
    data_version: str = "unknown"
    input_signature: str = ""
    entities: list[dict[str, Any]]
    candidate_tables: list[LinkedObject]
    candidate_columns: list[LinkedObject]
    metrics: list[dict[str, Any]]
    dimensions: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    business_terms: list[dict[str, Any]]
    verified_sql_examples: list[dict[str, Any]] = Field(default_factory=list)
    linking_trace: list[LinkedObject] = Field(default_factory=list)
    now: datetime
    row_limit: int
    token_budget: int
    estimated_tokens: int
    truncated: bool = False
    security_policy: SecurityPolicy


class QueryFilter(BaseModel):
    field: str
    operator: str
    value: Any


class QueryTimeRange(BaseModel):
    field: str = "orders.order_date"
    kind: str
    start: str | None = None
    end_exclusive: str | None = None


class CanonicalOutputField(BaseModel):
    canonical_name: str
    semantic_id: str
    kind: Literal["METRIC", "DIMENSION", "AUXILIARY"]
    expected_projection_type: str


class CanonicalOutputSchema(BaseModel):
    dimensions: list[CanonicalOutputField] = Field(default_factory=list)
    metrics: list[CanonicalOutputField] = Field(default_factory=list)
    auxiliary: list[CanonicalOutputField] = Field(default_factory=list)


class SQLPlan(BaseModel):
    question: str
    intent: str
    dialect: Literal["postgresql", "mysql"]
    provider: str
    semantic_model_id: str
    semantic_model_version: int
    selected_entities: list[str]
    selected_tables: list[str]
    selected_columns: list[str]
    metrics: list[str]
    dimensions: list[str]
    joins: list[dict[str, Any]]
    filters: list[QueryFilter]
    time_range: QueryTimeRange | None = None
    group_by: list[str] = Field(default_factory=list)
    order_by: list[str] = Field(default_factory=list)
    limit: int = Field(ge=1, le=5000)
    generated_sql: str
    confidence: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)
    repair_count: int = Field(default=0, ge=0, le=2)
    model_trace: dict[str, Any] = Field(default_factory=dict)
    canonical_output_schema: CanonicalOutputSchema = Field(default_factory=CanonicalOutputSchema)


class GuardIssue(BaseModel):
    code: str
    message: str
    object_name: str | None = None


class GuardResult(BaseModel):
    allowed: bool
    dialect: str
    normalized_sql: str | None = None
    statement_type: str | None = None
    tables: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    applied_limit: int | None = None
    issues: list[GuardIssue] = Field(default_factory=list)
    normalization_actions: list[str] = Field(default_factory=list)


class ExecutionResult(BaseModel):
    status: Literal["SUCCEEDED", "FAILED", "TIMEOUT", "CONCURRENCY_LIMIT"]
    columns: list[str] = Field(default_factory=list)
    column_types: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    duration_ms: int = 0
    datasource_id: str
    dialect: str
    normalized_sql: str
    result_signature: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class ExplainCostAssessment(BaseModel):
    status: Literal["PASS", "BLOCKED", "ERROR"]
    estimated_cost: float | None = None
    maximum_cost: float
    explain_duration_ms: int = 0
    reason: str


class VerificationQueryResult(BaseModel):
    required: bool
    executed: bool
    passed: bool
    kind: Literal["NOT_REQUIRED", "READ_ONLY_REPLAY"]
    query_sha256: str | None = None
    primary_signature: str | None = None
    verification_signature: str | None = None
    duration_ms: int = 0
    error_code: str | None = None


class ExpectedResult(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    tolerance: float = 0.0001
    order_independent: bool = True
    metric_names: list[str] = Field(default_factory=list)
    dimension_names: list[str] = Field(default_factory=list)
    expected_signature: str | None = None


class OracleCheck(BaseModel):
    name: str
    passed: bool
    message: str


class OracleResult(BaseModel):
    status: Literal["PASSED", "MISMATCH", "NOT_RUN"]
    confidence: float = Field(ge=0, le=1)
    checks: list[OracleCheck] = Field(default_factory=list)
    actual_signature: str | None = None
    expected_signature: str | None = None
    mismatch_count: int = 0


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    datasource_id: str | None = None
    semantic_model_id: str | None = None
    row_limit: int | None = Field(default=None, ge=1, le=500)


class FeedbackRequest(BaseModel):
    feedback_type: Literal["HELPFUL", "NOT_HELPFUL", "INCORRECT"]
    comment: str | None = Field(default=None, max_length=2000)


class SaveAnswerRequest(BaseModel):
    owner_name: str = Field(default="当前用户", min_length=1, max_length=128)
    status: Literal["DRAFT", "VERIFIED"] = "VERIFIED"


class VerifyResultRequest(BaseModel):
    expected: ExpectedResult


class QueryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    question: str
    status: str
    provider: str
    datasource_id: str
    semantic_model_id: str
    semantic_model_version: int
    context: dict[str, Any]
    plan: dict[str, Any]
    guard: dict[str, Any]
    execution: dict[str, Any]
    oracle: dict[str, Any]
    chart_spec: dict[str, Any]
    narrative: dict[str, Any]
    result_evidence: dict[str, Any] = Field(default_factory=dict)
    answer_claims: list[dict[str, Any]] = Field(default_factory=list)
    summary: str
    kpis: list[dict[str, Any]]
    recommended_questions: list[str]
    error_code: str | None = None
    error_message: str | None = None
