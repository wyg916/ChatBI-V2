from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EvaluationProfile(BaseModel):
    model: str = Field(default="deterministic", min_length=1, max_length=64)
    prompt: str = Field(default="chatbi-eval-v2.1", min_length=1, max_length=128)
    semantic_engine: str = Field(default="chatbi-semantic", min_length=1, max_length=128)
    nl2sql_engine: str = Field(default="chatbi-nl2sql", min_length=1, max_length=128)
    version: str = Field(default="v2.1", min_length=1, max_length=64)


class EvaluationCreate(BaseModel):
    name: str = Field(default="ChatBI V2.1 Golden 50", min_length=1, max_length=255)
    profile: EvaluationProfile = Field(default_factory=EvaluationProfile)


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
    profile: EvaluationProfile = Field(default_factory=EvaluationProfile)
    accuracy: dict[str, float] = Field(default_factory=dict)
    release_gate: dict = Field(default_factory=dict)
    multiple_ground_truth: bool = False


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


class EvaluationComparisonRequest(BaseModel):
    run_ids: list[str] = Field(min_length=2, max_length=8)


class EvaluationComparisonResponse(BaseModel):
    axes: list[str]
    runs: list[EvaluationRunRead]
    metrics: list[dict]
    winner_run_id: str | None = None


class EvaluationDashboardResponse(BaseModel):
    current: EvaluationRunRead
    accuracy_cards: list[dict]
    error_analysis: list[dict]
    release_gate: dict
    comparison_axes: list[str]


class ReleaseGateResponse(BaseModel):
    run_id: str
    status: str
    thresholds: dict[str, float]
    metrics: dict[str, float]
    checks: list[dict]


class FeedbackCorrectionCreate(BaseModel):
    query_run_id: str
    comment: str = Field(min_length=1, max_length=2000)
    corrected_sql: str = Field(min_length=1, max_length=20000)
    expected_rows: list[dict]
    expected_columns: list[str] = Field(default_factory=list)
    owner_name: str = Field(default="当前用户", min_length=1, max_length=128)


class FeedbackCorrectCreate(BaseModel):
    query_run_id: str
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackReviewRequest(BaseModel):
    decision: str = Field(pattern="^(APPROVE|REJECT)$")
    comment: str = Field(min_length=1, max_length=2000)


class FeedbackRecallRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    datasource_id: str | None = None
    semantic_model_id: str | None = None


class FeedbackReplayRequest(FeedbackRecallRequest):
    expected_rows: list[dict] | None = None
    expected_columns: list[str] = Field(default_factory=list)


class FeedbackCandidate(BaseModel):
    answer_id: str
    question: str
    sql: str
    score: float
    version: int
    status: str


class FeedbackWorkflowRead(BaseModel):
    answer_id: str
    query_run_id: str | None = None
    status: str
    workflow_state: str
    question: str
    corrected_sql: str | None = None
    oracle_status: str | None = None
    version: int
    feedback: dict


class FeedbackReplayResponse(BaseModel):
    candidate: FeedbackCandidate
    query_run_id: str
    guard_status: str
    oracle_status: str
    result_signature: str | None = None
    replay_passed: bool
    replay_rate: float


class FeedbackDashboardResponse(BaseModel):
    terminology: list[dict]
    sql_examples: list[FeedbackCandidate]
    workflows: list[FeedbackWorkflowRead]
    total_replays: int
    passed_replays: int
    feedback_replay_rate: float


class EvaluationRunDetail(BaseModel):
    run: EvaluationRunRead
    cases: list[EvaluationCaseResultRead]


class EvaluationCaseDetail(BaseModel):
    run: EvaluationRunRead
    case: EvaluationCaseResultRead
    previous_case_id: str | None = None
    next_case_id: str | None = None
