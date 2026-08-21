from __future__ import annotations

from app.models import DataSource
from app.query.contracts import (
    ExecutionResult,
    QueryTimeRange,
    SQLPlan,
    SecurityPolicy,
)
from app.query.explain_cost import ExplainCostGuard
from app.query.oracle import ResultOracle
from app.query.sql_guard import SqlGuard
from app.query.verification import VerificationQueryRunner


def execution(*, signature: str = "a" * 64, plan=None, status: str = "SUCCEEDED") -> ExecutionResult:
    rows = [{"plan": plan}] if plan is not None else [{"revenue": 100.0}]
    columns = ["plan"] if plan is not None else ["revenue"]
    return ExecutionResult(
        status=status,
        columns=columns,
        column_types=["json" if plan is not None else "numeric"],
        rows=rows,
        row_count=1,
        duration_ms=3,
        datasource_id="datasource",
        dialect="postgresql",
        normalized_sql="SELECT SUM(revenue) AS revenue FROM demo_business.orders LIMIT 100",
        result_signature=signature if status == "SUCCEEDED" else None,
        error_code=None if status == "SUCCEEDED" else "QUERY_EXPLAIN_ERROR",
    )


def sql_plan(*, metrics: list[str] | None = None) -> SQLPlan:
    return SQLPlan(
        question="统计收入",
        intent="AGGREGATE",
        dialect="postgresql",
        provider="phase2-test",
        semantic_model_id="model",
        semantic_model_version=1,
        selected_entities=["orders"],
        selected_tables=["orders"],
        selected_columns=["orders.revenue", "orders.order_date"],
        metrics=metrics or ["revenue"],
        dimensions=[],
        joins=[],
        filters=[],
        time_range=QueryTimeRange(kind="YEAR", start="2025-01-01", end_exclusive="2026-01-01"),
        limit=100,
        generated_sql="SELECT SUM(revenue) AS revenue FROM demo_business.orders",
        confidence=1.0,
    )


def policy() -> SecurityPolicy:
    return SecurityPolicy(
        allowed_schemas=["demo_business"],
        allowed_tables=["orders"],
        allowed_columns={"orders": ["revenue", "order_date"]},
        row_limit=100,
        timeout_ms=5000,
    )


def test_explain_cost_guard_parses_postgres_and_mysql_and_blocks_high_cost():
    guard = ExplainCostGuard()
    postgres = guard.assess(
        execution(plan=[{"Plan": {"Node Type": "Limit", "Total Cost": 42.5}}]),
        maximum_cost=100,
    )
    mysql = guard.assess(
        execution(plan='{"query_block":{"cost_info":{"query_cost":"12.75"}}}'),
        maximum_cost=100,
    )
    blocked = guard.assess(
        execution(plan=[{"Plan": {"Total Cost": 101.0}}]),
        maximum_cost=100,
    )

    assert postgres.status == "PASS" and postgres.estimated_cost == 42.5
    assert mysql.status == "PASS" and mysql.estimated_cost == 12.75
    assert blocked.status == "BLOCKED" and blocked.reason == "QUERY_COST_LIMIT_EXCEEDED"


def test_explain_cost_guard_fails_closed_without_database_cost():
    result = ExplainCostGuard().assess(
        execution(plan={"Node Type": "Limit"}),
        maximum_cost=100,
    )
    assert result.status == "ERROR"
    assert result.reason == "QUERY_COST_NOT_AVAILABLE"


def test_critical_verification_query_is_guarded_and_compares_real_signatures():
    class RecordingExecutor:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def execute(self, *, datasource, normalized_sql, row_limit, timeout_ms):
            self.calls.append(normalized_sql)
            return execution(signature="a" * 64)

    executor = RecordingExecutor()
    runner = VerificationQueryRunner(guard=SqlGuard(), executor=executor)
    datasource = DataSource(
        id="datasource", workspace_id="workspace", name="Demo", type="postgresql",
        host="127.0.0.1", port=5432, database="chatbi", username="readonly",
        password_encrypted="not-used", ssl=False, schema="demo_business",
    )
    result = runner.run(
        plan=sql_plan(),
        datasource=datasource,
        normalized_sql="SELECT SUM(revenue) AS revenue FROM demo_business.orders LIMIT 100",
        primary=execution(signature="a" * 64),
        policy=policy(),
        row_limit=100,
        timeout_ms=5000,
    )

    assert result.required is True
    assert result.executed is True
    assert result.passed is True
    assert result.query_sha256 and len(result.query_sha256) == 64
    assert len(executor.calls) == 1


def test_noncritical_query_does_not_add_a_database_call():
    class NoCallExecutor:
        def execute(self, **kwargs):
            raise AssertionError("noncritical query must not be replayed")

    runner = VerificationQueryRunner(guard=SqlGuard(), executor=NoCallExecutor())
    result = runner.run(
        plan=sql_plan(metrics=["inventory_label"]),
        datasource=DataSource(
            id="datasource", workspace_id="workspace", name="Demo", type="postgresql",
            host="127.0.0.1", port=5432, database="chatbi", username="readonly",
            password_encrypted="not-used", ssl=False, schema="demo_business",
        ),
        normalized_sql="SELECT revenue FROM demo_business.orders LIMIT 100",
        primary=execution(),
        policy=policy(),
        row_limit=100,
        timeout_ms=5000,
    )
    assert result.kind == "NOT_REQUIRED"
    assert result.executed is False


def test_result_oracle_checks_chart_and_narrative_result_binding():
    primary = execution(signature="a" * 64)
    oracle = ResultOracle().verify(
        plan=sql_plan(),
        guard=SqlGuard().validate(
            "SELECT SUM(revenue) AS revenue FROM demo_business.orders",
            dialect="postgresql",
            policy=policy(),
        ),
        execution=primary,
    )
    checked = ResultOracle().verify_presentation(
        oracle=oracle,
        query_id="query-1",
        execution=primary,
        chart_spec={
            "data_source_query_id": "query-1",
            "result_signature": "a" * 64,
            "bound_columns": ["revenue"],
            "bound_row_count": 1,
        },
        narrative={
            "source_query_id": "query-1",
            "result_signature": "a" * 64,
            "evidence": [{"fields": ["revenue"], "row_indexes": [0]}],
        },
    )
    assert checked.status == "PASSED"
    assert next(item for item in checked.checks if item.name == "chart_accuracy").passed is True
    assert next(item for item in checked.checks if item.name == "narrative_accuracy").passed is True

    tampered = ResultOracle().verify_presentation(
        oracle=ResultOracle().verify(
            plan=sql_plan(),
            guard=SqlGuard().validate(
                "SELECT SUM(revenue) AS revenue FROM demo_business.orders",
                dialect="postgresql",
                policy=policy(),
            ),
            execution=primary,
        ),
        query_id="query-1",
        execution=primary,
        chart_spec={
            "data_source_query_id": "query-other",
            "result_signature": "a" * 64,
            "bound_columns": ["revenue"],
            "bound_row_count": 1,
        },
        narrative={
            "source_query_id": "query-1",
            "result_signature": "a" * 64,
            "evidence": [{"fields": ["secret_column"], "row_indexes": [0]}],
        },
    )
    assert tampered.status == "MISMATCH"
    assert tampered.mismatch_count == 2
