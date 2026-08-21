from __future__ import annotations

import hashlib
from threading import Event

from app.models import DataSource
from app.query.contracts import ExecutionResult, SQLPlan, SecurityPolicy, VerificationQueryResult
from app.query.executor import QueryExecutor
from app.query.sql_guard import SqlGuard


_CRITICAL_METRICS = {
    "revenue",
    "net_sales",
    "net_profit",
    "profit",
    "profit_margin",
    "refund_amount",
    "outstanding_amount",
    "active_customers",
    "order_count",
    "valid_orders",
}


class VerificationQueryRunner:
    """Re-executes guarded critical queries and compares database result signatures."""

    def __init__(self, *, guard: SqlGuard, executor: QueryExecutor) -> None:
        self.guard = guard
        self.executor = executor

    @staticmethod
    def required(plan: SQLPlan) -> bool:
        return bool(set(plan.metrics) & _CRITICAL_METRICS) or len(plan.joins) >= 2

    def run(
        self,
        *,
        plan: SQLPlan,
        datasource: DataSource,
        normalized_sql: str,
        primary: ExecutionResult,
        policy: SecurityPolicy,
        row_limit: int,
        timeout_ms: int,
        cancellation_event: Event | None = None,
    ) -> VerificationQueryResult:
        required = self.required(plan)
        if not required:
            return VerificationQueryResult(
                required=False, executed=False, passed=True, kind="NOT_REQUIRED",
            )
        query_hash = hashlib.sha256(normalized_sql.encode("utf-8")).hexdigest()
        verified_guard = self.guard.validate(
            normalized_sql,
            dialect=plan.dialect,
            policy=policy,
        )
        if not verified_guard.allowed or not verified_guard.normalized_sql:
            return VerificationQueryResult(
                required=True,
                executed=False,
                passed=False,
                kind="READ_ONLY_REPLAY",
                query_sha256=query_hash,
                primary_signature=primary.result_signature,
                error_code="VERIFICATION_SQL_GUARD_REJECTED",
            )
        executor_arguments = dict(
            datasource=datasource,
            normalized_sql=verified_guard.normalized_sql,
            row_limit=row_limit,
            timeout_ms=timeout_ms,
        )
        if cancellation_event is not None:
            executor_arguments["cancellation_event"] = cancellation_event
        verification = self.executor.execute(**executor_arguments)
        passed = (
            primary.status == "SUCCEEDED"
            and verification.status == "SUCCEEDED"
            and bool(primary.result_signature)
            and primary.result_signature == verification.result_signature
        )
        return VerificationQueryResult(
            required=True,
            executed=True,
            passed=passed,
            kind="READ_ONLY_REPLAY",
            query_sha256=query_hash,
            primary_signature=primary.result_signature,
            verification_signature=verification.result_signature,
            duration_ms=verification.duration_ms,
            error_code=None if passed else (verification.error_code or "VERIFICATION_RESULT_MISMATCH"),
        )
