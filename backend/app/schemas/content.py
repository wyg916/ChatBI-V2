from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AnswerCreate(BaseModel):
    question: str = Field(min_length=2, max_length=512)
    model_name: str = Field(min_length=1, max_length=255)
    owner_name: str = Field(min_length=1, max_length=128)
    module: str = Field(default="模块 C1.1.8", max_length=64)
    status: str = Field(default="DRAFT", pattern="^(DRAFT|VERIFIED|REJECTED|DEPRECATED)$")
    accuracy_percent: float = Field(default=0, ge=0, le=100)


class AnswerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    question: str
    module: str
    sql_synced: bool
    model_name: str
    owner_name: str
    status: str
    accuracy_percent: float
    adoption_count: int
    is_favorite: bool
    query_run_id: str | None = None
    sql_text: str | None = None
    result_signature: str | None = None
    semantic_model_version: int | None = None
    semantic_intent: dict = Field(default_factory=dict)
    sql_plan: dict = Field(default_factory=dict)
    result_snapshot: dict = Field(default_factory=dict)
    chart_spec: dict = Field(default_factory=dict)
    narrative: dict = Field(default_factory=dict)
    semantic_model_id: str | None = None
    datasource_id: str | None = None
    oracle_status: str | None = None
    feedback: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AnswerVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version: int
    snapshot: dict
    created_at: datetime


class AnswerDetailResponse(AnswerRead):
    versions: list[AnswerVersionRead] = Field(default_factory=list)


class AnswerStatusUpdate(BaseModel):
    status: str = Field(pattern="^(DRAFT|VERIFIED|REJECTED|DEPRECATED)$")
    feedback: str | None = Field(default=None, max_length=2000)


class AnswerSummary(BaseModel):
    total: int
    average_accuracy: float
    monthly_adoptions: int
    pending_review: int
    favorites: int
    drafts: int
    published: int
    verified: int
    rejected: int
    deprecated: int


class AnswerLibraryResponse(BaseModel):
    summary: AnswerSummary
    items: list[AnswerRead]
    total: int
    page: int
    page_size: int


class DashboardCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str = Field(min_length=2, max_length=1000)
    card_count: int = Field(default=0, ge=0)
    is_shared: bool = False


class DashboardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    card_count: int
    is_shared: bool
    refresh_count_today: int
    status: str
    trend_variant: int
    updated_at: datetime


class DashboardSummary(BaseModel):
    total: int
    cards: int
    shared: int
    refreshes_today: int


class DashboardLibraryResponse(BaseModel):
    summary: DashboardSummary
    items: list[DashboardRead]
    total: int
    page: int
    page_size: int


class DashboardKpi(BaseModel):
    label: str
    value: float
    unit: str
    change: float
    change_unit: str = "%"


class DashboardTrendPoint(BaseModel):
    date: str
    revenue: float


class DashboardRegionRow(BaseModel):
    region: str
    order_count: int
    revenue: float
    charging_kwh: float
    margin_percent: float
    change_percent: float


class DashboardDetailResponse(BaseModel):
    dashboard: DashboardRead
    data_as_of: str
    range_start: str
    range_end: str
    kpis: list[DashboardKpi]
    revenue_trend: list[DashboardTrendPoint]
    regions: list[DashboardRegionRow]
    insight: str
    cards: list["DashboardCardRead"] = Field(default_factory=list)


class DashboardCardCreate(BaseModel):
    answer_id: str
    title: str | None = Field(default=None, max_length=255)
    position: dict = Field(default_factory=lambda: {"x": 0, "y": 0})
    size: dict = Field(default_factory=lambda: {"w": 6, "h": 4})
    filter_context: dict = Field(default_factory=dict)
    refresh_policy: str = Field(default="MANUAL", pattern="^(MANUAL|ON_LOAD)$")


class DashboardCardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dashboard_id: str
    answer_id: str
    query_run_id: str
    chart_spec: dict
    title: str
    position: dict
    size: dict
    filter_context: dict
    semantic_model_version: int
    result_signature: str | None = None
    refresh_policy: str
    source_question: str = ""
    result_snapshot: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
