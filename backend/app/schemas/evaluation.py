from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
