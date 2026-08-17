from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EvaluationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    release_name: str
    model_name: str
    status: str
    is_current: bool
    golden_set_count: int
    sql_generation_rate: float
    result_accuracy: float
    semantic_accuracy: float
    relevance_accuracy: float
    average_response_seconds: float
    error_distribution: list[dict]
    trend_points: list[dict]
    completed_at: datetime
    duration_seconds: int
    manifest_sha256: str | None = None
    sql_execution_pass_count: int = 0
    result_value_pass_count: int = 0
    semantic_pass_count: int = 0
    dangerous_sql_total: int = 0
    dangerous_sql_block_count: int = 0


class EvaluationMetric(BaseModel):
    key: str
    label: str
    value: float
    unit: str
    change: float


class EvaluationOverviewResponse(BaseModel):
    current: EvaluationRunRead
    metrics: list[EvaluationMetric]
    comparisons: list[EvaluationRunRead]


class EvaluationCaseResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    evaluation_run_id: str
    case_id: str
    category: str
    question: str
    status: str
    execution_ok: bool
    result_ok: bool
    semantic_ok: bool
    expected: dict
    actual: dict
    generated_sql: str | None = None
    result_diff: list[dict] = Field(default_factory=list)
    error_category: str | None = None
    query_run_id: str | None = None
    created_at: datetime
    updated_at: datetime


class EvaluationRunDetail(BaseModel):
    run: EvaluationRunRead
    cases: list[EvaluationCaseResultRead]


class EvaluationCaseDetail(BaseModel):
    run: EvaluationRunRead
    case: EvaluationCaseResultRead
    previous_case_id: str | None = None
    next_case_id: str | None = None
