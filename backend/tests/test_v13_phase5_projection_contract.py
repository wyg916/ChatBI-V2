from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.model_gateway.normalization import normalize_chat_completion
from app.query.contracts import (
    ExecutionResult,
    ExpectedResult,
    QueryContext,
    SQLPlan,
    SecurityPolicy,
)
from app.query.executor import QueryExecutor
from app.query.nl2sql_response import normalize_nl2sql_response
from app.query.oracle import ResultOracle
from app.query.projection_contract import ProjectionContractError, ProjectionContractValidator
from app.query.sql_guard import SqlGuard


FIXTURES = Path(__file__).parent / "fixtures" / "provider_responses"


def _context(
    *,
    dialect: str = "postgresql",
    duplicate_metric_expression: bool = False,
    shared_revenue_column: bool = False,
) -> QueryContext:
    metrics = [
        {
            "id": "metric-revenue",
            "name": "revenue",
            "label": "收入",
            "description": "订单收入",
            "expression": "orders.revenue",
            "aggregation": "SUM",
            "filters": [],
        },
        {
            "id": "metric-cost",
            "name": "cost",
            "label": "成本",
            "description": "订单成本",
            "expression": "orders.cost",
            "aggregation": "SUM",
            "filters": [],
        },
    ]
    if duplicate_metric_expression:
        metrics.append({
            "id": "metric-gross-revenue",
            "name": "gross_revenue",
            "label": "总收入",
            "description": "与收入相同表达式的独立定义",
            "expression": "orders.revenue",
            "aggregation": "SUM",
            "filters": [],
        })
    entities = [
        {"id": "orders", "name": "orders", "source_table": "orders", "primary_key": "id"},
        {"id": "regions", "name": "regions", "source_table": "regions", "primary_key": "id"},
    ]
    allowed_tables = ["orders", "regions"]
    allowed_columns = {
        "orders": ["id", "revenue", "cost", "order_date"],
        "regions": ["id", "province"],
    }
    if shared_revenue_column:
        entities.append({
            "id": "daily_kpi", "name": "daily_kpi", "source_table": "daily_kpi", "primary_key": "id",
        })
        allowed_tables.append("daily_kpi")
        allowed_columns["daily_kpi"] = ["id", "revenue"]
    return QueryContext(
        workspace_id="workspace",
        workspace_name="Workspace",
        datasource_id="datasource",
        datasource_name="Demo",
        dialect=dialect,
        semantic_model_id="semantic-model",
        semantic_model_name="Business",
        semantic_model_version=1,
        entities=entities,
        candidate_tables=[],
        candidate_columns=[],
        metrics=metrics,
        dimensions=[{
            "id": "dimension-province",
            "name": "province",
            "label": "省份",
            "source_column": "regions.province",
            "type": "STRING",
        }, {
            "id": "dimension-order-date",
            "name": "order_date",
            "label": "订单日期",
            "source_column": "orders.order_date",
            "type": "DATE",
        }],
        relationships=[],
        business_terms=[],
        now=datetime(2026, 8, 26, tzinfo=timezone.utc),
        row_limit=100,
        token_budget=4000,
        estimated_tokens=100,
        security_policy=SecurityPolicy(
            allowed_tables=allowed_tables,
            allowed_columns=allowed_columns,
        ),
    )


def _plan(
    sql: str,
    *,
    metrics: list[str] | None = None,
    dimensions: list[str] | None = None,
    dialect: str = "postgresql",
) -> SQLPlan:
    return SQLPlan(
        question="test",
        intent="ANALYTICAL_QUERY",
        dialect=dialect,
        provider="mimo",
        semantic_model_id="semantic-model",
        semantic_model_version=1,
        selected_entities=["orders", "regions"],
        selected_tables=["orders", "regions"],
        selected_columns=["orders.revenue", "orders.cost", "regions.province"],
        metrics=metrics or [],
        dimensions=dimensions or [],
        joins=[],
        filters=[],
        limit=100,
        generated_sql=sql,
        confidence=1.0,
    )


def _validate(plan: SQLPlan, *, context: QueryContext | None = None):
    return ProjectionContractValidator().validate_and_normalize(
        plan=plan,
        context=context or _context(dialect=plan.dialect),
    )


def test_projection_contract_01_canonical_alias_already_correct() -> None:
    sql = "SELECT SUM(o.revenue) AS revenue FROM orders o"
    result = _validate(_plan(sql, metrics=["revenue"]))
    assert result.status == "PASS"
    assert result.normalization_actions == ()
    assert result.plan.generated_sql == sql
    assert result.plan.canonical_output_schema.metrics[0].model_dump() == {
        "canonical_name": "revenue",
        "semantic_id": "metric-revenue",
        "kind": "METRIC",
        "expected_projection_type": "AGGREGATE_SUM",
    }


def test_projection_contract_02_single_safe_metric_alias_mismatch() -> None:
    result = _validate(_plan("SELECT SUM(o.revenue) AS total_revenue FROM orders o", metrics=["revenue"]))
    assert "AS revenue" in result.plan.generated_sql
    assert "total_revenue" not in result.plan.generated_sql
    assert result.normalization_actions == ({
        "from": "total_revenue",
        "to": "revenue",
        "semantic_metric": "revenue",
        "semantic_id": "metric-revenue",
        "reason": "canonical_output_contract",
    },)


def test_projection_contract_03_unnamed_aggregate_gets_canonical_alias() -> None:
    result = _validate(_plan("SELECT SUM(o.revenue) FROM orders o", metrics=["revenue"]))
    assert "AS revenue" in result.plan.generated_sql
    assert result.normalization_actions[0]["from"] == "<none>"


def test_projection_contract_04_multiple_exact_aliases_pass() -> None:
    result = _validate(_plan(
        "SELECT SUM(o.revenue) AS revenue, SUM(o.cost) AS cost FROM orders o",
        metrics=["revenue", "cost"],
    ))
    assert result.normalization_actions == ()
    assert [item.canonical_name for item in result.plan.canonical_output_schema.metrics] == ["revenue", "cost"]


def test_projection_contract_05_multiple_unique_semantic_mappings_normalize() -> None:
    result = _validate(_plan(
        "SELECT SUM(o.cost) AS total_cost, SUM(o.revenue) AS total_revenue FROM orders o",
        metrics=["revenue", "cost"],
    ))
    assert {item["to"] for item in result.normalization_actions} == {"revenue", "cost"}
    assert "AS cost" in result.plan.generated_sql
    assert "AS revenue" in result.plan.generated_sql


def test_projection_contract_06_ambiguous_aggregate_outputs_fail_closed() -> None:
    context = _context(duplicate_metric_expression=True)
    plan = _plan(
        "SELECT SUM(o.revenue) AS total_a, SUM(o.revenue) AS total_b FROM orders o",
        metrics=["revenue", "gross_revenue"],
    )
    with pytest.raises(ProjectionContractError, match="PROJECTION_AMBIGUOUS_SEMANTIC_MAPPING"):
        _validate(plan, context=context)


def test_projection_contract_07_duplicate_canonical_alias_fails_closed() -> None:
    with pytest.raises(ProjectionContractError, match="PROJECTION_DUPLICATE_CANONICAL_ALIAS"):
        _validate(_plan("SELECT SUM(o.revenue) AS revenue FROM orders o", metrics=["revenue", "revenue"]))


def test_projection_contract_08_unknown_extra_output_fails_closed() -> None:
    plan = _plan(
        "SELECT SUM(o.revenue) AS revenue, SUM(o.cost) AS cost FROM orders o",
        metrics=["revenue"],
    )
    with pytest.raises(ProjectionContractError, match="PROJECTION_UNDECLARED_OUTPUT"):
        _validate(plan)


def test_projection_contract_09_missing_expected_metric_fails_closed() -> None:
    plan = _plan("SELECT SUM(o.revenue) AS revenue FROM orders o", metrics=["revenue", "cost"])
    with pytest.raises(ProjectionContractError, match="PROJECTION_MISSING_EXPECTED_OUTPUT"):
        _validate(plan)


def test_projection_contract_10_dimension_alias_normalizes_by_source_expression() -> None:
    plan = _plan(
        "SELECT r.province AS province_name FROM regions r",
        dimensions=["province"],
    )
    result = _validate(plan)
    assert "AS province" in result.plan.generated_sql
    assert result.normalization_actions[0]["semantic_dimension"] == "province"


def test_projection_contract_11_order_by_alias_is_rewritten_through_ast() -> None:
    original = "SELECT SUM(o.revenue) AS total_revenue FROM orders o ORDER BY total_revenue DESC"
    result = _validate(_plan(original, metrics=["revenue"]))
    assert "SUM(o.revenue) AS revenue" in result.plan.generated_sql
    assert "ORDER BY revenue DESC" in result.plan.generated_sql
    assert "o.revenue" in result.plan.generated_sql


def test_projection_contract_12_unsafe_alias_dependency_fails_closed() -> None:
    sql = "SELECT SUM(o.revenue) AS total_revenue FROM orders o WHERE total_revenue > 0"
    with pytest.raises(ProjectionContractError, match="PROJECTION_ALIAS_DEPENDENCY_UNSAFE"):
        _validate(_plan(sql, metrics=["revenue"]))


def test_group_by_alias_is_rewritten_when_not_a_source_column() -> None:
    sql = "SELECT r.province AS province_name FROM regions r GROUP BY province_name"
    result = _validate(_plan(sql, dimensions=["province"]))
    assert "AS province" in result.plan.generated_sql
    assert "GROUP BY province" in result.plan.generated_sql
    assert "r.province" in result.plan.generated_sql


def test_year_grain_dimension_normalizes_only_with_ast_plan_and_semantic_binding() -> None:
    plan = _plan(
        "SELECT YEAR(o.order_date) AS year, SUM(o.revenue) AS total_revenue, "
        "SUM(o.cost) AS total_cost FROM orders o GROUP BY YEAR(o.order_date) "
        "ORDER BY YEAR(o.order_date)",
        dimensions=["order_date"],
        metrics=["revenue", "cost"],
        dialect="mysql",
    ).model_copy(update={
        "group_by": ["YEAR(orders.order_date)"],
        "order_by": ["YEAR(orders.order_date)"],
    })
    result = _validate(plan, context=_context(dialect="mysql"))
    assert "YEAR(o.order_date) AS order_date" in result.plan.generated_sql
    assert "SUM(o.revenue) AS revenue" in result.plan.generated_sql
    assert "SUM(o.cost) AS cost" in result.plan.generated_sql
    assert {item["to"] for item in result.normalization_actions} == {"order_date", "revenue", "cost"}


def test_year_grain_dimension_without_matching_plan_group_by_fails_closed() -> None:
    plan = _plan(
        "SELECT YEAR(o.order_date) AS year, SUM(o.revenue) AS revenue "
        "FROM orders o GROUP BY YEAR(o.order_date)",
        dimensions=["order_date"],
        metrics=["revenue"],
        dialect="mysql",
    )
    with pytest.raises(ProjectionContractError, match="PROJECTION_MISSING_EXPECTED_OUTPUT"):
        _validate(plan, context=_context(dialect="mysql"))


def test_server_bound_provider_year_grain_uses_exact_ast_group_without_duplicate_call() -> None:
    plan = _plan(
        "SELECT EXTRACT(YEAR FROM orders.order_date) AS year, "
        "SUM(orders.revenue) AS revenue, SUM(orders.cost) AS cost "
        "FROM orders GROUP BY EXTRACT(YEAR FROM orders.order_date) ORDER BY year",
        dimensions=["order_date"],
        metrics=["revenue", "cost"],
    ).model_copy(update={
        "selected_tables": ["orders"],
        "model_trace": {
            "provider_response_bound": True,
            "resolved_provider": "mimo",
            "resolved_model": "mimo-v2.5",
        },
    })

    result = _validate(plan)

    assert "EXTRACT(YEAR FROM orders.order_date) AS order_date" in result.plan.generated_sql
    assert "ORDER BY order_date" in result.plan.generated_sql
    assert {item["to"] for item in result.normalization_actions} == {"order_date"}


def test_unbound_provider_year_grain_cannot_claim_server_response_binding() -> None:
    plan = _plan(
        "SELECT EXTRACT(YEAR FROM orders.order_date) AS year, "
        "SUM(orders.revenue) AS revenue FROM orders "
        "GROUP BY EXTRACT(YEAR FROM orders.order_date)",
        dimensions=["order_date"],
        metrics=["revenue"],
    ).model_copy(update={
        "selected_tables": ["orders"],
        "model_trace": {
            "provider_response_bound": True,
            "resolved_provider": "deepseek",
            "resolved_model": "deepseek-v4-flash",
        },
    })

    with pytest.raises(ProjectionContractError, match="PROJECTION_MISSING_EXPECTED_OUTPUT"):
        _validate(plan)


def test_unique_cte_lineage_normalizes_recorded_deepseek_year_and_metric_aliases() -> None:
    plan = _plan(
        "WITH yearly AS (SELECT EXTRACT(YEAR FROM order_date) AS yr, "
        "SUM(revenue) AS total_revenue, SUM(cost) AS total_cost "
        "FROM demo_business.orders GROUP BY EXTRACT(YEAR FROM order_date)) "
        "SELECT yr, total_revenue, total_cost FROM yearly ORDER BY yr",
        dimensions=["order_date"],
        metrics=["revenue", "cost"],
        dialect="postgresql",
    )

    result = _validate(plan, context=_context(dialect="postgresql"))

    assert "SELECT yr AS order_date, total_revenue AS revenue, total_cost AS cost FROM yearly" in result.plan.generated_sql
    assert "ORDER BY order_date" in result.plan.generated_sql
    assert {item["to"] for item in result.normalization_actions} == {"order_date", "revenue", "cost"}


def test_cte_year_lineage_without_matching_group_expression_fails_closed() -> None:
    plan = _plan(
        "WITH yearly AS (SELECT EXTRACT(YEAR FROM order_date) AS yr, "
        "SUM(revenue) AS total_revenue FROM demo_business.orders) "
        "SELECT yr, total_revenue FROM yearly",
        dimensions=["order_date"],
        metrics=["revenue"],
        dialect="postgresql",
    )

    with pytest.raises(ProjectionContractError, match="PROJECTION_MISSING_EXPECTED_OUTPUT"):
        _validate(plan, context=_context(dialect="postgresql"))


def test_unqualified_projection_resolves_only_with_one_visible_ast_owner() -> None:
    context = _context(shared_revenue_column=True)
    plan = _plan("SELECT SUM(revenue) AS total_revenue FROM orders", metrics=["revenue"])

    result = _validate(plan, context=context)

    assert result.plan.generated_sql == "SELECT SUM(revenue) AS revenue FROM orders"
    assert result.normalization_actions[0]["to"] == "revenue"


def test_unqualified_projection_with_two_visible_ast_owners_fails_closed() -> None:
    context = _context(shared_revenue_column=True)
    plan = _plan(
        "SELECT SUM(revenue) AS total_revenue FROM orders "
        "JOIN daily_kpi ON orders.id = daily_kpi.id",
        metrics=["revenue"],
    ).model_copy(update={"selected_tables": ["orders", "daily_kpi"]})

    with pytest.raises(ProjectionContractError, match="PROJECTION_MISSING_EXPECTED_OUTPUT"):
        _validate(plan, context=context)


def test_wren_comparison_auxiliary_outputs_are_explicitly_declared() -> None:
    plan = _plan(
        "WITH compared AS (SELECT SUM(o.revenue) AS revenue FROM orders o) "
        "SELECT revenue, revenue AS previous_revenue, 0 AS comparison_rate FROM compared",
        metrics=["revenue"],
    ).model_copy(update={"provider": "wren-clean-room-runtime"})
    result = _validate(plan)
    assert result.normalization_actions == ()
    assert result.plan.generated_sql == plan.generated_sql
    assert [item.canonical_name for item in result.plan.canonical_output_schema.auxiliary] == [
        "previous_revenue",
        "comparison_rate",
    ]


class _FakeResult:
    @staticmethod
    def keys() -> list[str]:
        return ["revenue"]

    def mappings(self) -> "_FakeResult":
        return self

    @staticmethod
    def fetchmany(_limit: int) -> list[dict[str, float]]:
        return [{"revenue": 1725750.0}]


class _FakeConnection:
    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    @staticmethod
    def exec_driver_sql(_sql: str) -> None:
        return None

    @staticmethod
    def commit() -> None:
        return None

    @staticmethod
    def begin():
        return nullcontext()

    @staticmethod
    def execute(_sql: object) -> _FakeResult:
        return _FakeResult()


class _FakeEngine:
    @staticmethod
    def connect() -> _FakeConnection:
        return _FakeConnection()

    @staticmethod
    def dispose() -> None:
        return None


def test_recorded_real_mimo_alias_mismatch_full_contract_regression(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = json.loads(
        (FIXTURES / "mimo_nl2sql_recorded_real_alias_mismatch.json").read_text(encoding="utf-8")
    )
    assert fixture["provenance"] == "RECORDED_REAL_SANITIZED_PROVIDER_RESPONSE_2026-08-26"
    assert fixture["source_evidence"]["candidate_sha"] == "e42eb8a0df0b0df299e7fcca3f0addb744bfdc38"
    response = normalize_chat_completion(fixture["response"])
    plan = normalize_nl2sql_response(response.content)
    context = _context(dialect="mysql")
    contract = _validate(plan, context=context)
    guard = SqlGuard().validate(
        contract.plan.generated_sql,
        dialect="mysql",
        policy=context.security_policy,
    )
    assert guard.allowed is True, guard.issues

    monkeypatch.setattr(
        "app.query.executor.build_connector",
        lambda _datasource: SimpleNamespace(_engine=lambda: _FakeEngine()),
    )
    datasource = SimpleNamespace(id="datasource", type="mysql", schema=None)
    execution = QueryExecutor().execute(
        datasource=datasource,
        normalized_sql=guard.normalized_sql or "",
        row_limit=1,
        timeout_ms=1000,
    )
    expected = ExpectedResult(
        columns=fixture["expected_result"]["columns"],
        rows=fixture["expected_result"]["rows"],
        metric_names=["revenue"],
    )
    oracle = ResultOracle().verify(plan=contract.plan, guard=guard, execution=execution, expected=expected)

    assert response.resolved_model == "mimo-v2.5"
    assert contract.plan.generated_sql == "SELECT SUM(orders.revenue) AS revenue FROM orders"
    assert execution == ExecutionResult.model_validate(execution.model_dump())
    assert execution.columns == ["revenue"]
    assert execution.rows == [{"revenue": 1725750.0}]
    assert oracle.status == "PASSED", oracle.checks


def test_recorded_real_deepseek_unqualified_alias_full_contract_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = json.loads(
        (FIXTURES / "deepseek_nl2sql_recorded_real_unqualified_alias.json").read_text(encoding="utf-8")
    )
    assert fixture["provenance"] == "RECORDED_REAL_SANITIZED_PROVIDER_RESPONSE_2026-08-26"
    assert fixture["source_evidence"]["candidate_sha"] == "67cdfa88d2d9a1eb239d74183b36551eb58b78d4"
    response = normalize_chat_completion(fixture["response"])
    plan = normalize_nl2sql_response(response.content)
    context = _context(shared_revenue_column=True)
    contract = _validate(plan, context=context)
    guard = SqlGuard().validate(
        contract.plan.generated_sql,
        dialect="postgresql",
        policy=context.security_policy,
    )
    assert guard.allowed is True, guard.issues

    monkeypatch.setattr(
        "app.query.executor.build_connector",
        lambda _datasource: SimpleNamespace(_engine=lambda: _FakeEngine()),
    )
    datasource = SimpleNamespace(id="datasource", type="postgresql", schema=None)
    execution = QueryExecutor().execute(
        datasource=datasource,
        normalized_sql=guard.normalized_sql or "",
        row_limit=1,
        timeout_ms=1000,
    )
    expected = ExpectedResult(
        columns=fixture["expected_result"]["columns"],
        rows=fixture["expected_result"]["rows"],
        metric_names=["revenue"],
    )
    oracle = ResultOracle().verify(plan=contract.plan, guard=guard, execution=execution, expected=expected)

    assert response.resolved_model == "deepseek-v4-flash"
    assert contract.plan.generated_sql == "SELECT SUM(revenue) AS revenue FROM orders"
    assert execution.columns == ["revenue"]
    assert execution.rows == [{"revenue": 1725750.0}]
    assert oracle.status == "PASSED", oracle.checks
