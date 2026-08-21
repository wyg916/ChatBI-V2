from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from app.query.contracts import ExecutionResult, ExplainCostAssessment


def _decoded(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _cost_values(value: Any) -> Iterable[float]:
    value = _decoded(value)
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("_", " ")
            if normalized in {"total cost", "query cost"}:
                try:
                    yield float(item)
                except (TypeError, ValueError):
                    pass
            yield from _cost_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _cost_values(item)


class ExplainCostGuard:
    """Fail closed when EXPLAIN fails or the database estimate exceeds policy."""

    def assess(self, explain: ExecutionResult, *, maximum_cost: float) -> ExplainCostAssessment:
        if explain.status != "SUCCEEDED":
            return ExplainCostAssessment(
                status="ERROR",
                maximum_cost=maximum_cost,
                explain_duration_ms=explain.duration_ms,
                reason=explain.error_code or "QUERY_EXPLAIN_FAILED",
            )
        estimates = [cost for row in explain.rows for cost in _cost_values(row.get("plan"))]
        if not estimates:
            return ExplainCostAssessment(
                status="ERROR",
                maximum_cost=maximum_cost,
                explain_duration_ms=explain.duration_ms,
                reason="QUERY_COST_NOT_AVAILABLE",
            )
        estimated_cost = max(estimates)
        return ExplainCostAssessment(
            status="PASS" if estimated_cost <= maximum_cost else "BLOCKED",
            estimated_cost=estimated_cost,
            maximum_cost=maximum_cost,
            explain_duration_ms=explain.duration_ms,
            reason="QUERY_COST_WITHIN_LIMIT" if estimated_cost <= maximum_cost else "QUERY_COST_LIMIT_EXCEEDED",
        )
