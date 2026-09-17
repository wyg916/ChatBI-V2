from __future__ import annotations

import ast
from pathlib import Path

from sqlalchemy import select

from app.models import AuditEvent, SqlWorkspaceRun
from app.query.contracts import ExecutionResult
from app.query.executor import QueryExecutor, result_signature
from app.query.sql_guard import SqlGuard
from app.services.seed import seed_demo_semantic_model


APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def test_business_sql_execution_has_one_allowlisted_gateway() -> None:
    allowlisted_raw_boundaries = {
        Path("connectors/sqlalchemy_connector.py"): {"test_connection", "sync_metadata"},
        Path("query/executor.py"): {"_prepare_postgres_transaction", "execute", "explain"},
        Path("model_gateway/test_cost_control.py"): {
            "_connect", "_schema_version", "reserve_attempt", "complete_attempt", "summary",
        },
        # Explicitly confirmed, local-development-only DDL maintenance. This is
        # not a business query path and preserves the read-only demo schema.
        Path("showcase/rebuild_schema.py"): {"rebuild_local_metadata_schema"},
    }
    violations: list[str] = []
    query_executor_classes = 0
    direct_connector_reads = 0
    trusted_policy_call_sites: list[str] = []

    for path in sorted(APP_ROOT.rglob("*.py")):
        relative = path.relative_to(APP_ROOT)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
        function_stack: list[str] = []

        class Visitor(ast.NodeVisitor):
            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                nonlocal query_executor_classes
                if node.name == "QueryExecutor":
                    query_executor_classes += 1
                self.generic_visit(node)

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                function_stack.append(node.name)
                self.generic_visit(node)
                function_stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, node: ast.Call) -> None:
                nonlocal direct_connector_reads
                if any(keyword.arg == "trusted_policy" for keyword in node.keywords):
                    trusted_policy_call_sites.append(f"{relative}:{node.lineno}")
                if isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                    if name == "read_rows":
                        direct_connector_reads += 1
                        violations.append(f"{relative}:{node.lineno}:connector.read_rows")
                    if name in {"exec_driver_sql", "_engine"} or (
                        name == "execute" and isinstance(node.func.value, ast.Name) and node.func.value.id == "connection"
                    ):
                        allowed = function_stack and function_stack[-1] in allowlisted_raw_boundaries.get(relative, set())
                        if not allowed:
                            violations.append(f"{relative}:{node.lineno}:{name}")
                self.generic_visit(node)

        Visitor().visit(tree)

    assert direct_connector_reads == 0
    assert query_executor_classes == 1
    assert violations == []
    assert len(trusted_policy_call_sites) == 1
    trusted_path, _line = trusted_policy_call_sites[0].rsplit(":", 1)
    assert Path(trusted_path) == Path("services/content.py")


def test_dashboard_runtime_uses_guard_executor_signature_trace_and_audit(
    client,
    db_session,
    monkeypatch,
) -> None:
    seed_demo_semantic_model(db_session)
    guard_calls: list[str] = []
    execution_calls: list[str] = []
    original_validate = SqlGuard.validate

    def validate(self, sql, *, dialect, policy):
        guard_calls.append(sql)
        return original_validate(self, sql, dialect=dialect, policy=policy)

    def execute(self, *, datasource, normalized_sql, row_limit, timeout_ms, cancellation_event=None):
        execution_calls.append(normalized_sql)
        if "active_customers" in normalized_sql:
            rows = [{
                "max_date": "2026-08-17",
                "revenue": 1000,
                "profit": 200,
                "order_count": 10,
                "charging_kwh": 300,
                "previous_revenue": 900,
                "previous_profit": 180,
                "customers": 8,
                "previous_customers": 7,
            }]
        elif "region_name" in normalized_sql:
            rows = [{
                "region": "华东",
                "order_count": 10,
                "revenue": 1000,
                "profit": 200,
                "charging_kwh": 300,
                "previous_revenue": 900,
            }]
        else:
            rows = [{"kpi_date": "2026-08-17", "revenue": 1000}]
        columns = list(rows[0])
        return ExecutionResult(
            status="SUCCEEDED",
            columns=columns,
            column_types=["unknown"] * len(columns),
            rows=rows,
            row_count=len(rows),
            duration_ms=1,
            datasource_id=datasource.id,
            dialect=datasource.type,
            normalized_sql=normalized_sql,
            result_signature=result_signature(columns, rows),
        )

    monkeypatch.setattr(SqlGuard, "validate", validate)
    monkeypatch.setattr(QueryExecutor, "execute", execute)
    dashboard = client.get("/api/v1/dashboards").json()["items"][0]

    response = client.get(f"/api/v1/dashboards/{dashboard['id']}")

    assert response.status_code == 200, response.text
    assert response.json()["data_as_of"] == "2026-08-17"
    assert len(guard_calls) == len(execution_calls) == 3
    runs = list(db_session.scalars(
        select(SqlWorkspaceRun).where(SqlWorkspaceRun.operation.like("DASHBOARD_DETAIL_%"))
    ))
    assert len(runs) == 3
    assert all(run.status == "SUCCEEDED" for run in runs)
    assert all((run.execution_payload or {}).get("result_signature") for run in runs)
    audits = list(db_session.scalars(
        select(AuditEvent).where(AuditEvent.action.like("SQL_WORKSPACE_DASHBOARD_DETAIL_%"))
    ))
    assert len(audits) == 3
    assert all(event.details.get("run_id") and event.details.get("result_signature") for event in audits)
