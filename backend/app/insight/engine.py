from __future__ import annotations

from collections.abc import Mapping
from numbers import Number
from typing import Any

from app.chart.contracts import ChartSpec
from app.insight.contracts import Narrative, NarrativeEvidence
from app.query.contracts import ExecutionResult, OracleResult, SQLPlan


def _numeric(value: Any) -> float | None:
    if isinstance(value, Number) and not isinstance(value, bool):
        return float(value)
    return None


def _format(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return f"{value:,}"
    return "—" if value is None else str(value)


class FollowUpSuggestionEngine:
    def suggest(self, *, question: str, plan: Mapping[str, Any], rows: list[dict[str, Any]]) -> list[str]:
        metrics = list(plan.get("metrics") or [])
        dimensions = list(plan.get("dimensions") or [])
        filters = list(plan.get("filters") or [])
        suggestions: list[str] = []
        if "region" not in dimensions:
            suggestions.append("按地区拆分看看？")
        if "month" not in dimensions:
            suggestions.append("按月查看趋势怎么样？")
        if "customer" not in dimensions:
            suggestions.append("哪个客户贡献最高？")
        if metrics and metrics[0] != "profit":
            suggestions.append("对比收入与利润表现？")
        if filters:
            suggestions.append("去掉当前筛选后的整体表现如何？")
        if len(rows) > 1:
            suggestions.append("继续查看贡献最高项的明细？")
        if not suggestions:
            suggestions.append(f"继续按其他维度分析{metrics[0] if metrics else '当前结果'}？")
        # Keep stable order and never return a duplicate of the current question.
        return [item for item in dict.fromkeys(suggestions) if item.rstrip("？?") not in question][:5]


class InsightGenerator:
    """Deterministic, evidence-bound insight extraction without causal claims."""

    def generate(self, *, metrics: list[str], dimensions: list[str], rows: list[dict[str, Any]]) -> tuple[list[str], list[str], list[str], list[NarrativeEvidence]]:
        trends: list[str] = []
        contributions: list[str] = []
        anomalies: list[str] = []
        evidence: list[NarrativeEvidence] = []
        metric = metrics[0] if metrics else None
        dimension = dimensions[0] if dimensions else None
        numeric_rows = [(index, _numeric(row.get(metric))) for index, row in enumerate(rows)] if metric else []
        numeric_rows = [(index, value) for index, value in numeric_rows if value is not None]
        if metric and dimension and len(numeric_rows) >= 2:
            first_index, first = numeric_rows[0]
            last_index, last = numeric_rows[-1]
            if first not in (None, 0) and last is not None:
                change = (last - first) / abs(first) * 100
                direction = "上升" if change > 0 else "下降" if change < 0 else "持平"
                statement = f"{dimension}序列首尾相比{direction}{abs(change):.1f}%"
                trends.append(statement)
                evidence.append(NarrativeEvidence(statement=statement, fields=[dimension, metric], row_indexes=[first_index, last_index], evidence_type="TREND"))
            leader_index, leader_value = max(numeric_rows, key=lambda item: item[1])
            total = sum(value for _, value in numeric_rows)
            label = rows[leader_index].get(dimension)
            share = leader_value / total * 100 if total > 0 else 0
            statement = f"{label}的{metric}最高，为{_format(leader_value)}"
            if total > 0:
                statement += f"，占当前结果合计{share:.1f}%"
            contributions.append(statement)
            evidence.append(NarrativeEvidence(statement=statement, fields=[dimension, metric], row_indexes=[leader_index], evidence_type="CONTRIBUTION"))
        null_count = sum(value is None for row in rows for value in row.values())
        negative_count = sum((_numeric(value) or 0) < 0 for row in rows for value in row.values())
        if null_count:
            anomalies.append(f"结果中有 {null_count} 个空值，未将其自动解释为 0。")
        if negative_count:
            anomalies.append(f"结果中有 {negative_count} 个负值，建议结合指标口径复核。")
        return trends, contributions, anomalies, evidence


class NarrativeEngine:
    def __init__(self, insight_generator: InsightGenerator | None = None, followups: FollowUpSuggestionEngine | None = None):
        self.insight_generator = insight_generator or InsightGenerator()
        self.followups = followups or FollowUpSuggestionEngine()

    def generate(
        self, *, query_id: str, semantic_model_version: int,
        plan: SQLPlan | Mapping[str, Any], execution: ExecutionResult | Mapping[str, Any],
        oracle: OracleResult | Mapping[str, Any], chart_spec: ChartSpec | Mapping[str, Any],
    ) -> Narrative:
        plan_value = plan.model_dump(mode="json") if isinstance(plan, SQLPlan) else dict(plan)
        result = execution.model_dump(mode="json") if isinstance(execution, ExecutionResult) else dict(execution)
        oracle_value = oracle.model_dump(mode="json") if isinstance(oracle, OracleResult) else dict(oracle)
        chart_value = chart_spec.model_dump(mode="json") if isinstance(chart_spec, ChartSpec) else dict(chart_spec)
        rows = list(result.get("rows") or [])
        metrics = list(plan_value.get("metrics") or [])
        dimensions = list(plan_value.get("dimensions") or [])
        if oracle_value.get("status") != "PASSED":
            return Narrative(
                conclusion="结果未通过 Result Oracle 校验，不生成业务洞察。",
                source_query_id=query_id, result_signature=result.get("result_signature"),
                semantic_model_version=semantic_model_version,
            )
        if not rows:
            conclusion = "查询已完成，当前条件下没有匹配数据。"
            key_metrics: list[dict[str, Any]] = []
            evidence = [NarrativeEvidence(statement=conclusion, fields=[], row_indexes=[], evidence_type="EMPTY_RESULT")]
        elif len(rows) == 1 and metrics:
            key_metrics = [{"label": metric, "value": rows[0].get(metric), "unit": chart_value.get("unit", {}).get(metric, "")} for metric in metrics[:4]]
            conclusion = "；".join(f"{item['label']}为{_format(item['value'])}{item['unit']}" for item in key_metrics) + "。"
            evidence = [NarrativeEvidence(statement=conclusion, fields=metrics[:4], row_indexes=[0], evidence_type="KPI")]
        else:
            key_metrics = []
            conclusion = f"查询返回 {len(rows)} 行按{'、'.join(dimensions) or '明细'}汇总的可验证结果。"
            evidence = [NarrativeEvidence(statement=conclusion, fields=dimensions + metrics, row_indexes=list(range(min(len(rows), 20))), evidence_type="RESULT_SHAPE")]
        trends, contributions, anomalies, extracted = self.insight_generator.generate(metrics=metrics, dimensions=dimensions, rows=rows)
        evidence.extend(extracted)
        insights = [*trends, *contributions, *anomalies]
        return Narrative(
            conclusion=conclusion,
            key_metrics=key_metrics,
            trends=trends,
            contributions=contributions,
            anomalies=anomalies,
            insights=insights,
            recommended_questions=self.followups.suggest(question=str(plan_value.get("question") or ""), plan=plan_value, rows=rows),
            evidence=evidence,
            source_query_id=query_id,
            result_signature=result.get("result_signature"),
            semantic_model_version=semantic_model_version,
        )
