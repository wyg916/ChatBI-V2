from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AnswerCreate(BaseModel):
    question: str = Field(min_length=2, max_length=512)
    model_name: str = Field(min_length=1, max_length=255)
    owner_name: str = Field(min_length=1, max_length=128)
    module: str = Field(default="模块 C1.1.8", max_length=64)
    status: str = Field(default="DRAFT", pattern="^(DRAFT|REVIEW|PUBLISHED)$")
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
    updated_at: datetime


class AnswerSummary(BaseModel):
    total: int
    average_accuracy: float
    monthly_adoptions: int
    pending_review: int
    favorites: int
    drafts: int
    published: int


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
