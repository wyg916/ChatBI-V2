from __future__ import annotations

import math
from typing import Any

from app.query.contracts import (
    ExecutionResult,
    ExpectedResult,
    GuardResult,
    OracleCheck,
    OracleResult,
    SQLPlan,
)
from app.query.executor import result_signature


def _equal_value(actual: Any, expected: Any, tolerance: float) -> bool:
    if actual is None or expected is None:
        return actual is expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return math.isclose(float(actual), float(expected), rel_tol=tolerance, abs_tol=tolerance)
    return str(actual) == str(expected)


def _canonical_rows(rows: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: tuple(str(row.get(column)) for column in columns))


def _join_uses_selected_entities(item: dict[str, Any], selected_tables: set[str]) -> bool:
    left = str(item.get("left") or "")
    right = str(item.get("right") or "")
    if left and right:
        return left.split(".")[0] in selected_tables and right.split(".")[0] in selected_tables

    left_table = str(item.get("left_table") or "")
    right_table = str(item.get("right_table") or "")
    left_column = str(item.get("left_column") or "")
    right_column = str(item.get("right_column") or "")
    if any((left_table, right_table, left_column, right_column)):
        return (
            left_table in selected_tables
            and right_table in selected_tables
            and bool(left_column)
            and bool(right_column)
        )

    left_entity = str(item.get("left_entity") or "")
    right_entity = str(item.get("right_entity") or "")
    join_keys = item.get("join_keys") or []
    return (
        left_entity in selected_tables
        and right_entity in selected_tables
        and bool(join_keys)
        and all(isinstance(key, dict) and key.get("left") and key.get("right") for key in join_keys)
    )


class ResultOracle:
    """Independent result contract checks; never judges correctness from SQL string equality."""

    def verify(
        self,
        *,
        plan: SQLPlan,
        guard: GuardResult,
        execution: ExecutionResult,
        expected: ExpectedResult | None = None,
    ) -> OracleResult:
        checks: list[OracleCheck] = []
        checks.append(OracleCheck(
            name="execution_status", passed=execution.status == "SUCCEEDED",
            message=f"Execution status is {execution.status}",
        ))
        checks.append(OracleCheck(
            name="guard_status", passed=guard.allowed,
            message="SQL passed AST authorization" if guard.allowed else "SQL was rejected by the AST guard",
        ))
        metric_aliases = set(plan.metrics)
        dimension_aliases = set(plan.dimensions)
        columns = set(execution.columns)
        metric_ok = metric_aliases.issubset(columns)
        dimension_ok = all(item in columns for item in dimension_aliases)
        checks.append(OracleCheck(
            name="metric_columns", passed=metric_ok,
            message="All selected metric columns are present" if metric_ok else "One or more selected metric columns are missing",
        ))
        checks.append(OracleCheck(
            name="dimension_columns", passed=dimension_ok,
            message="Selected dimension columns are present" if dimension_ok else "Selected dimension columns are missing",
        ))
        time_ok = plan.time_range is None or plan.time_range.field in plan.selected_columns
        checks.append(OracleCheck(
            name="time_semantics", passed=time_ok,
            message="Time range is bound to the semantic time column" if time_ok else "Time range has no authorized time column",
        ))
        filter_ok = all(item.field in plan.selected_columns or item.field.split(".")[0] in plan.selected_tables for item in plan.filters)
        checks.append(OracleCheck(
            name="filter_semantics", passed=filter_ok,
            message="Filters reference selected/authorized objects" if filter_ok else "A filter references an unselected object",
        ))
        selected_tables = set(plan.selected_tables)
        join_ok = all(_join_uses_selected_entities(item, selected_tables) for item in plan.joins)
        checks.append(OracleCheck(
            name="join_semantics", passed=join_ok,
            message="Join endpoints are selected semantic entities" if join_ok else "Join endpoint is outside the selected entities",
        ))
        null_ok = all(set(row) == columns for row in execution.rows)
        checks.append(OracleCheck(
            name="row_shape_and_nulls", passed=null_ok,
            message="Every row has the declared column set" if null_ok else "One or more rows have inconsistent columns",
        ))
        grain_keys = [item for item in plan.dimensions if item in columns]
        grain_values = [tuple(row.get(key) for key in grain_keys) for row in execution.rows]
        duplicate_grain_ok = not grain_keys or len(grain_values) == len(set(grain_values))
        checks.append(OracleCheck(
            name="duplicate_grain", passed=duplicate_grain_ok,
            message="Result grain is unique" if duplicate_grain_ok else "Duplicate rows were detected at the declared dimension grain",
        ))

        mismatch_count = 0
        expected_signature: str | None = None
        if expected is not None:
            metric_contract_ok = not expected.metric_names or set(expected.metric_names) == metric_aliases
            dimension_contract_ok = not expected.dimension_names or set(expected.dimension_names) == dimension_aliases
            checks.append(OracleCheck(
                name="expected_metric_semantics", passed=metric_contract_ok,
                message="Metric semantics match the frozen contract" if metric_contract_ok else "Metric semantics differ from the frozen contract",
            ))
            checks.append(OracleCheck(
                name="expected_dimension_semantics", passed=dimension_contract_ok,
                message="Dimension semantics match the frozen contract" if dimension_contract_ok else "Dimension semantics differ from the frozen contract",
            ))
            expected_columns = expected.columns or list(expected.rows[0]) if expected.rows else expected.columns
            column_set_ok = set(expected_columns) == columns
            checks.append(OracleCheck(
                name="expected_column_set", passed=column_set_ok,
                message="Result columns match the frozen contract" if column_set_ok else "Result columns differ from the frozen contract",
            ))
            actual_rows = execution.rows
            expected_rows = expected.rows
            if expected.order_independent:
                actual_rows = _canonical_rows(actual_rows, expected_columns)
                expected_rows = _canonical_rows(expected_rows, expected_columns)
            row_count_ok = len(actual_rows) == len(expected_rows)
            checks.append(OracleCheck(
                name="expected_row_count", passed=row_count_ok,
                message=f"Actual/expected row count: {len(actual_rows)}/{len(expected_rows)}",
            ))
            if row_count_ok and column_set_ok:
                for actual_row, expected_row in zip(actual_rows, expected_rows):
                    for column in expected_columns:
                        if not _equal_value(actual_row.get(column), expected_row.get(column), expected.tolerance):
                            mismatch_count += 1
            else:
                mismatch_count += abs(len(actual_rows) - len(expected_rows)) + 1
            checks.append(OracleCheck(
                name="expected_values", passed=mismatch_count == 0,
                message="Values match within tolerance" if mismatch_count == 0 else f"Detected {mismatch_count} value mismatches",
            ))
            expected_signature = expected.expected_signature or result_signature(expected_columns, expected.rows, order_independent=expected.order_independent)
            if expected.expected_signature:
                checks.append(OracleCheck(
                    name="expected_signature", passed=execution.result_signature == expected.expected_signature,
                    message="Result signature matches" if execution.result_signature == expected.expected_signature else "Result signature differs",
                ))

        passed = all(check.passed for check in checks)
        if execution.status != "SUCCEEDED":
            status = "NOT_RUN"
        else:
            status = "PASSED" if passed else "MISMATCH"
        confidence = sum(1 for check in checks if check.passed) / len(checks) if checks else 0.0
        return OracleResult(
            status=status,
            confidence=round(confidence, 4),
            checks=checks,
            actual_signature=execution.result_signature,
            expected_signature=expected_signature,
            mismatch_count=mismatch_count,
        )

    def verify_presentation(
        self,
        *,
        oracle: OracleResult,
        query_id: str,
        execution: ExecutionResult,
        chart_spec: dict[str, Any],
        narrative: dict[str, Any],
    ) -> OracleResult:
        """Bind chart and narrative to the verified result without model confidence."""
        columns = set(execution.columns)
        chart_fields = set(chart_spec.get("bound_columns") or [])
        chart_ok = (
            chart_spec.get("data_source_query_id") == query_id
            and chart_spec.get("result_signature") == execution.result_signature
            and chart_fields == columns
            and int(chart_spec.get("bound_row_count", -1)) == execution.row_count
        )
        oracle.checks.append(OracleCheck(
            name="chart_accuracy",
            passed=chart_ok,
            message="Chart is bound to the verified query result" if chart_ok else "Chart binding differs from the verified result",
        ))

        evidence_ok = True
        for item in narrative.get("evidence") or []:
            if not set(item.get("fields") or []).issubset(columns):
                evidence_ok = False
            if any(not isinstance(index, int) or index < 0 or index >= execution.row_count for index in item.get("row_indexes") or []):
                evidence_ok = False
        narrative_ok = (
            narrative.get("source_query_id") == query_id
            and narrative.get("result_signature") == execution.result_signature
            and evidence_ok
        )
        oracle.checks.append(OracleCheck(
            name="narrative_accuracy",
            passed=narrative_ok,
            message="Narrative evidence is bound to verified rows" if narrative_ok else "Narrative evidence is not bound to the verified result",
        ))
        if not chart_ok or not narrative_ok:
            oracle.status = "MISMATCH"
            oracle.mismatch_count += int(not chart_ok) + int(not narrative_ok)
        oracle.confidence = round(
            sum(1 for check in oracle.checks if check.passed) / len(oracle.checks),
            4,
        )
        return oracle
