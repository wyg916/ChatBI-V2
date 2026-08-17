import pytest

from app.chart import ChartEngine
from app.insight import NarrativeEngine


def plan(question="按地区统计收入", metrics=None, dimensions=None):
    return {
        "question": question,
        "metrics": metrics if metrics is not None else ["revenue"],
        "dimensions": dimensions if dimensions is not None else ["region"],
        "order_by": [],
    }


def execution(rows, columns=None, signature="a" * 64):
    return {
        "status": "SUCCEEDED",
        "columns": columns if columns is not None else (list(rows[0]) if rows else []),
        "rows": rows,
        "row_count": len(rows),
        "result_signature": signature,
    }


@pytest.mark.parametrize(
    ("case_plan", "case_execution", "expected_type"),
    [
        (plan(), execution([], ["region", "revenue"]), "TABLE"),
        (plan("统计收入", ["revenue"], []), execution([{"revenue": 10.0}]), "KPI"),
        (plan("统计订单量", ["order_count"], []), execution([{"order_count": 3}]), "KPI"),
        (plan("按月查看收入趋势", ["revenue"], ["month"]), execution([{"month": "01", "revenue": 1}, {"month": "02", "revenue": 2}]), "LINE"),
        (plan("按日期查看成本", ["cost"], ["order_date"]), execution([{"order_date": "01", "cost": 1}, {"order_date": "02", "cost": 2}]), "LINE"),
        (plan(), execution([{"region": "A", "revenue": 1}, {"region": "B", "revenue": 2}]), "BAR"),
        (plan("按地区对比收入成本", ["revenue", "cost"], ["region"]), execution([{"region": "A", "revenue": 1, "cost": 2}, {"region": "B", "revenue": 2, "cost": 1}]), "GROUPED_BAR"),
        (plan("按地区堆叠收入成本", ["revenue", "cost"], ["region"]), execution([{"region": "A", "revenue": 1, "cost": 2}, {"region": "B", "revenue": 2, "cost": 1}]), "STACKED_BAR"),
        (plan("各地区收入占比", ["revenue"], ["region"]), execution([{"region": "A", "revenue": 1}, {"region": "B", "revenue": 2}]), "DONUT"),
        (plan("明细", [], []), execution([{"name": "A", "value": 1}, {"name": "B", "value": 2}]), "BAR"),
        (plan("明细", [], []), execution([{"name": "A"}, {"name": "B"}]), "TABLE"),
        (plan(), execution([{"region": str(index), "revenue": index} for index in range(25)]), "BAR"),
        (plan(), execution([{"region": "A", "revenue": None}, {"region": "B", "revenue": 2}]), "BAR"),
        (plan(), execution([{"region": "A", "revenue": -1}, {"region": "B", "revenue": 2}]), "BAR"),
        (plan("统计利润率", ["margin_percent"], []), execution([{"margin_percent": 12.34}]), "KPI"),
    ],
)
def test_chart_selector_rules(case_plan, case_execution, expected_type):
    spec = ChartEngine().plan(query_id="q1", plan=case_plan, execution=case_execution)
    assert spec.chart_type == expected_type
    assert spec.data_source_query_id == "q1"
    assert spec.result_signature == "a" * 64


def test_large_category_null_negative_and_units_are_explicit():
    engine = ChartEngine()
    large = engine.plan(query_id="q", plan=plan(), execution=execution([{"region": str(index), "revenue": index} for index in range(25)]))
    assert large.limit == 20
    assert "类别超过" in large.warnings[0]
    nullable = engine.plan(query_id="q", plan=plan(), execution=execution([{"region": "A", "revenue": None}, {"region": "B", "revenue": -1}]))
    assert nullable.null_policy == "PRESERVE"
    assert any("空值" in item for item in nullable.warnings)
    assert any("负值" in item for item in nullable.warnings)
    assert nullable.unit["revenue"] == "元"


def test_chart_result_binding_detects_signature_or_query_drift():
    spec = ChartEngine().plan(query_id="q1", plan=plan(), execution=execution([{"region": "A", "revenue": 1}]))
    assert ChartEngine.binding_matches(spec, query_id="q1", result_signature="a" * 64)
    assert not ChartEngine.binding_matches(spec, query_id="q2", result_signature="a" * 64)
    assert not ChartEngine.binding_matches(spec, query_id="q1", result_signature="b" * 64)


def test_narrative_is_evidence_bound_and_does_not_claim_causality():
    result = execution([{"month": "01", "revenue": 100.0}, {"month": "02", "revenue": 120.0}])
    case_plan = plan("按月查看收入趋势", ["revenue"], ["month"])
    spec = ChartEngine().plan(query_id="q1", plan=case_plan, execution=result)
    narrative = NarrativeEngine().generate(
        query_id="q1", semantic_model_version=3, plan=case_plan, execution=result,
        oracle={"status": "PASSED"}, chart_spec=spec,
    )
    assert narrative.source_query_id == "q1"
    assert narrative.result_signature == "a" * 64
    assert narrative.semantic_model_version == 3
    assert narrative.trends and narrative.contributions and narrative.evidence
    text = "".join(narrative.insights)
    assert "因为" not in text and "导致" not in text
    assert 3 <= len(narrative.recommended_questions) <= 5


def test_narrative_refuses_insight_when_oracle_mismatches():
    result = execution([{"revenue": 100.0}])
    case_plan = plan("统计收入", ["revenue"], [])
    spec = ChartEngine().plan(query_id="q1", plan=case_plan, execution=result)
    narrative = NarrativeEngine().generate(
        query_id="q1", semantic_model_version=1, plan=case_plan, execution=result,
        oracle={"status": "MISMATCH"}, chart_spec=spec,
    )
    assert "不生成业务洞察" in narrative.conclusion
    assert narrative.insights == []
