from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable


ACCURACY_DIMENSIONS = (
    "metric",
    "dimension",
    "time",
    "filter",
    "join",
    "result_value",
    "chart",
    "narrative",
)


def _equal_value(actual: Any, expected: Any, tolerance: float) -> bool:
    if actual is None or expected is None:
        return actual is expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return math.isclose(float(actual), float(expected), rel_tol=tolerance, abs_tol=tolerance)
    return str(actual) == str(expected)


def _canonical_rows(rows: Iterable[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: tuple(str(row.get(column)) for column in columns))


class IbmText2SqlEvaluationAdapter:
    """ChatBI adapter for IBM toolkit evaluation semantics.

    The adapter intentionally owns no database connection. It receives results
    produced by ChatBI's guarded QueryPipeline and performs execution-based,
    order-independent result comparison, including multiple accepted ground
    truths. No IBM source code is copied into the runtime.
    """

    adapter_id = "ibm-text2sql-eval-compatible"
    upstream_commit = "60dd4515236adb335f2053b7c069397d7d88fe0a"
    implementation_origin = "chatbi-clean-room"
    upstream_runtime_status = "BLOCKED_LICENSE_METADATA_CONFLICT"
    upstream_runtime_calls = 0

    def provenance(self) -> dict[str, Any]:
        """Return an auditable boundary between compatibility and reuse.

        The locked IBM revision declares Apache-2.0 in its root LICENSE while
        its distribution metadata declares MIT. Until upstream resolves that
        conflict, ChatBI must not package or invoke the official runtime. This
        adapter remains independently authored and must never be counted as an
        upstream runtime call.
        """
        return {
            "implementation_origin": self.implementation_origin,
            "upstream_repository": "https://github.com/IBM/text2sql-eval-toolkit",
            "upstream_commit": self.upstream_commit,
            "upstream_runtime_status": self.upstream_runtime_status,
            "upstream_runtime_calls": self.upstream_runtime_calls,
            "license_evidence": {
                "root_license": "Apache-2.0",
                "distribution_metadata_license": "MIT",
                "closure": "CONFLICT_UNRESOLVED",
            },
        }

    def compare_results(
        self,
        *,
        actual: dict[str, Any],
        ground_truths: list[dict[str, Any]],
        tolerance: float = 0.0001,
    ) -> dict[str, Any]:
        attempts: list[dict[str, Any]] = []
        actual_columns = list(actual.get("columns") or [])
        actual_rows = list(actual.get("rows") or [])
        for index, truth in enumerate(ground_truths):
            truth_id = str(truth.get("id") or f"ground-truth-{index + 1}")
            expected_rows = list(truth.get("rows") or [])
            expected_columns = list(truth.get("columns") or (list(expected_rows[0]) if expected_rows else []))
            order_independent = bool(truth.get("order_independent", True))
            column_set_ok = set(actual_columns) == set(expected_columns)
            compared_actual = actual_rows
            compared_expected = expected_rows
            if order_independent:
                compared_actual = _canonical_rows(actual_rows, expected_columns)
                compared_expected = _canonical_rows(expected_rows, expected_columns)
            row_count_ok = len(compared_actual) == len(compared_expected)
            value_diffs: list[dict[str, Any]] = []
            if column_set_ok and row_count_ok:
                for row_index, (actual_row, expected_row) in enumerate(zip(compared_actual, compared_expected)):
                    for column in expected_columns:
                        if not _equal_value(actual_row.get(column), expected_row.get(column), tolerance):
                            value_diffs.append({
                                "row": row_index,
                                "column": column,
                                "expected": expected_row.get(column),
                                "actual": actual_row.get(column),
                            })
            attempt = {
                "ground_truth_id": truth_id,
                "column_set_ok": column_set_ok,
                "row_count_ok": row_count_ok,
                "value_diff_count": len(value_diffs),
                "value_diffs": value_diffs[:20],
                "expected_row_count": len(expected_rows),
                "actual_row_count": len(actual_rows),
                "expected_signature": truth.get("result_signature"),
                "actual_signature": actual.get("result_signature"),
            }
            attempt["passed"] = column_set_ok and row_count_ok and not value_diffs
            attempts.append(attempt)
            if attempt["passed"]:
                return {
                    "passed": True,
                    "matched_ground_truth_id": truth_id,
                    "attempts": attempts,
                    "result_diff": [],
                }
        return {
            "passed": False,
            "matched_ground_truth_id": None,
            "attempts": attempts,
            "result_diff": attempts,
        }

    def error_analysis(
        self,
        *,
        execution_ok: bool,
        guard_allowed: bool,
        checks: dict[str, bool],
        error_code: str | None = None,
    ) -> dict[str, Any]:
        categories: list[str] = []
        if not guard_allowed:
            categories.append("SQL_GUARD")
        elif not execution_ok:
            categories.append("SQL_EXECUTION")
        for dimension in ACCURACY_DIMENSIONS:
            if not checks.get(dimension, False):
                categories.append(f"{dimension.upper()}_ACCURACY")
        if error_code and not categories:
            categories.append(error_code)
        return {
            "primary": categories[0] if categories else None,
            "categories": categories,
            "failed_dimensions": [dimension for dimension in ACCURACY_DIMENSIONS if not checks.get(dimension, False)],
        }

    def summarize(self, cases: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(cases)
        dimension_counts = {
            dimension: sum(bool((case.get("accuracy_checks") or {}).get(dimension)) for case in cases)
            for dimension in ACCURACY_DIMENSIONS
        }
        error_counts = Counter(
            category
            for case in cases
            for category in ((case.get("error_analysis") or {}).get("categories") or [])
        )
        return {
            "adapter": self.adapter_id,
            "upstream_commit": self.upstream_commit,
            "provenance": self.provenance(),
            "execution_based": True,
            "multiple_ground_truth": any(int(case.get("ground_truth_count") or 0) > 1 for case in cases),
            "total": total,
            "accuracy": {
                dimension: round(dimension_counts[dimension] / total, 4) if total else 0.0
                for dimension in ACCURACY_DIMENSIONS
            },
            "pass_counts": dimension_counts,
            "error_counts": dict(sorted(error_counts.items())),
        }
