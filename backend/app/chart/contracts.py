from typing import Any, Literal

from pydantic import BaseModel, Field


ChartType = Literal["KPI", "LINE", "BAR", "GROUPED_BAR", "STACKED_BAR", "DONUT", "TABLE"]


class ChartSeries(BaseModel):
    name: str
    field: str
    type: Literal["line", "bar", "pie", "kpi", "table"]
    stack: str | None = None


class ChartSpec(BaseModel):
    version: str = "1.0"
    chart_type: ChartType
    title: str
    x_field: str | None = None
    y_fields: list[str] = Field(default_factory=list)
    series: list[ChartSeries] = Field(default_factory=list)
    aggregation: dict[str, str] = Field(default_factory=dict)
    unit: dict[str, str] = Field(default_factory=dict)
    sort: list[str] = Field(default_factory=list)
    limit: int = Field(default=20, ge=1, le=500)
    legend: dict[str, Any] = Field(default_factory=dict)
    axis: dict[str, Any] = Field(default_factory=dict)
    tooltip: dict[str, Any] = Field(default_factory=dict)
    data_source_query_id: str
    result_signature: str | None = None
    bound_columns: list[str] = Field(default_factory=list)
    bound_row_count: int = 0
    null_policy: Literal["PRESERVE", "ZERO", "DROP"] = "PRESERVE"
    warnings: list[str] = Field(default_factory=list)
