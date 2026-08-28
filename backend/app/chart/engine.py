from __future__ import annotations

from collections.abc import Mapping
from numbers import Number
from typing import Any

from app.chart.contracts import ChartSeries, ChartSpec, ChartType
from app.query.contracts import ExecutionResult, SQLPlan


TIME_FIELDS = {"date", "day", "week", "month", "quarter", "year", "time", "order_date", "kpi_date"}
CURRENCY_TOKENS = ("revenue", "cost", "profit", "amount", "income", "sales", "收入", "成本", "利润", "金额")
PERCENT_TOKENS = ("rate", "ratio", "percent", "margin", "share", "率", "占比")


def _is_number(value: Any) -> bool:
    return isinstance(value, Number) and not isinstance(value, bool)


def _unit(field: str) -> str:
    value = field.lower()
    if any(token in value for token in CURRENCY_TOKENS):
        return "元"
    if any(token in value for token in PERCENT_TOKENS):
        return "%"
    if "count" in value or "数量" in value:
        return "个"
    return ""


def _time_dimension(field: str) -> bool:
    value = field.lower()
    return value in TIME_FIELDS or any(token in value for token in ("date", "time", "month", "year", "日期", "月份", "年度"))


class ChartSelector:
    """Selects one controlled chart family from semantic intent and result shape."""

    def select(self, *, question: str, dimensions: list[str], metrics: list[str], row_count: int) -> ChartType:
        if row_count == 0 or not metrics:
            return "TABLE"
        if row_count == 1:
            return "KPI"
        if any(token in question for token in ("占比", "比例", "份额", "构成")) and len(metrics) == 1 and row_count <= 8:
            return "DONUT"
        if dimensions and _time_dimension(dimensions[0]):
            return "LINE"
        if len(metrics) > 1:
            return "STACKED_BAR" if any(token in question for token in ("堆叠", "构成", "累计")) else "GROUPED_BAR"
        if row_count > 12:
            return "HORIZONTAL_BAR"
        return "BAR"


class ChartEngine:
    """Builds a serializable ChartSpec. It never accepts or returns JavaScript."""

    def __init__(self, selector: ChartSelector | None = None):
        self.selector = selector or ChartSelector()

    def plan(self, *, query_id: str, plan: SQLPlan | Mapping[str, Any], execution: ExecutionResult | Mapping[str, Any]) -> ChartSpec:
        plan_value = plan.model_dump(mode="json") if isinstance(plan, SQLPlan) else dict(plan)
        result = execution.model_dump(mode="json") if isinstance(execution, ExecutionResult) else dict(execution)
        rows = list(result.get("rows") or [])
        columns = list(result.get("columns") or (list(rows[0]) if rows else []))
        declared_metrics = list(plan_value.get("metrics") or [])
        declared_dimensions = list(plan_value.get("dimensions") or [])
        metrics = [field for field in declared_metrics if field in columns]
        dimensions = [field for field in declared_dimensions if field in columns]

        if rows and not metrics:
            metrics = [field for field in columns if any(_is_number(row.get(field)) for row in rows)]
        if rows and not dimensions:
            dimensions = [field for field in columns if field not in metrics]

        question = str(plan_value.get("question") or "查询结果")
        field_labels = {
            str(key): str(value) for key, value in (plan_value.get("semantic_labels") or {}).items()
            if key and value
        }
        chart_type = self.selector.select(
            question=question, dimensions=dimensions, metrics=metrics, row_count=len(rows),
        )
        x_field = dimensions[0] if dimensions else None
        limit = min(max(len(rows), 1), 15) if chart_type != "TABLE" else min(max(len(rows), 1), 500)
        warnings: list[str] = []
        if len(rows) > 15 and chart_type != "TABLE":
            warnings.append("类别超过 15 个，图表仅展示按查询顺序排列的前 15 项；完整结果保留在明细表。")
        if any(any(value is None for value in row.values()) for row in rows):
            warnings.append("结果包含空值，图表保留空值且不推断为 0。")
        if any(_is_number(value) and value < 0 for row in rows for value in row.values()):
            warnings.append("结果包含负值，坐标轴保留零基线。")

        series_type = {
            "LINE": "line", "BAR": "bar", "HORIZONTAL_BAR": "bar", "GROUPED_BAR": "bar", "STACKED_BAR": "bar",
            "DONUT": "pie", "KPI": "kpi", "TABLE": "table",
        }[chart_type]
        series = [
            ChartSeries(
                name=field_labels.get(field, field),
                field=field,
                type=series_type,
                stack="total" if chart_type == "STACKED_BAR" else None,
            )
            for field in metrics
        ]
        aggregation = {item: str(plan_value.get("aggregation", {}).get(item, "QUERY_RESULT")) for item in metrics}
        units = {item: _unit(item) for item in metrics}
        title_subject = " / ".join(field_labels.get(item, item) for item in metrics) if metrics else "明细"
        title_dimension = f"按{field_labels.get(x_field, x_field)}查看" if x_field else ""
        question = str(plan_value.get("question") or "")
        if x_field and metrics and any(token in question.lower() for token in ("排名", "排行", "最高", "最低", "top")):
            contribution = "贡献" if "贡献" in question else ""
            title = f"{field_labels.get(x_field, x_field)}{title_subject}{contribution}排名"
        else:
            title = f"{title_dimension}{title_subject}"
        return ChartSpec(
            chart_type=chart_type,
            title=title,
            x_field=x_field,
            y_fields=metrics,
            series=series,
            aggregation=aggregation,
            unit=units,
            field_labels=field_labels,
            sort=list(plan_value.get("order_by") or []),
            limit=limit,
            legend={"show": len(metrics) > 1 or chart_type == "DONUT", "position": "top"},
            axis={"x_type": "time" if x_field and _time_dimension(x_field) else "category", "zero_baseline": True},
            tooltip={"trigger": "item" if chart_type in {"KPI", "DONUT"} else "axis", "show_unit": True},
            data_source_query_id=query_id,
            result_signature=result.get("result_signature"),
            bound_columns=columns,
            bound_row_count=int(result.get("row_count", len(rows))),
            warnings=warnings,
        )

    @staticmethod
    def binding_matches(spec: ChartSpec | Mapping[str, Any], *, query_id: str, result_signature: str | None) -> bool:
        value = spec.model_dump(mode="json") if isinstance(spec, ChartSpec) else spec
        return value.get("data_source_query_id") == query_id and value.get("result_signature") == result_signature
