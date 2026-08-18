from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sqlglot import exp, parse_one

from app.core.access import Principal, record_audit
from app.core.config import get_settings
from app.models import (
    DataSource,
    DataSourceColumn,
    DataSourceRelation,
    DataSourceSchema,
    DataSourceTable,
    SqlWorkspaceRun,
    VerifiedAnswer,
)
from app.query.contracts import ExecutionResult, GuardResult, OracleResult, SQLPlan, SecurityPolicy
from app.query.executor import QueryExecutor
from app.query.oracle import ResultOracle
from app.query.sql_guard import SqlGuard


SENSITIVE_COLUMN = re.compile(
    r"(^|_)(password|passwd|pwd|secret|token|api_key|private_key|id_card|ssn|phone|mobile|email|bank_account|card_number)(_|$)",
    re.IGNORECASE,
)


def datasource_or_error(db: Session, datasource_id: str, workspace_id: str) -> DataSource:
    datasource = db.get(DataSource, datasource_id)
    if datasource is None:
        raise LookupError("Datasource not found")
    if datasource.workspace_id != workspace_id:
        raise PermissionError("Datasource belongs to another workspace")
    if datasource.type not in {"postgresql", "mysql"}:
        raise ValueError("Only PostgreSQL and MySQL are supported")
    return datasource


def security_policy(db: Session, datasource_id: str, row_limit: int) -> SecurityPolicy:
    schemas = list(db.scalars(select(DataSourceSchema.name).where(DataSourceSchema.datasource_id == datasource_id)))
    rows = db.execute(
        select(DataSourceTable.name, DataSourceColumn.name)
        .join(DataSourceSchema, DataSourceTable.schema_id == DataSourceSchema.id)
        .join(DataSourceColumn, DataSourceColumn.table_id == DataSourceTable.id)
        .where(DataSourceSchema.datasource_id == datasource_id)
    )
    columns: dict[str, list[str]] = {}
    for table_name, column_name in rows:
        columns.setdefault(table_name.lower(), []).append(column_name.lower())
    return SecurityPolicy(
        row_limit=min(row_limit, get_settings().query_row_limit),
        timeout_ms=get_settings().query_timeout_ms,
        allowed_schemas=schemas,
        allowed_tables=sorted(columns),
        allowed_columns=columns,
    )


def format_sql(sql: str, dialect: str) -> str:
    sqlglot_dialect = {"postgresql": "postgres", "mysql": "mysql"}.get(dialect, dialect)
    return parse_one(sql, read=sqlglot_dialect).sql(dialect=sqlglot_dialect, pretty=True, comments=False)


def catalog_search(
    db: Session,
    datasource_id: str,
    *,
    query: str,
    kind: str,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    needle = f"%{query.strip()}%"
    items: list[dict[str, Any]] = []
    if kind in {"all", "schema"}:
        statement = select(DataSourceSchema).where(DataSourceSchema.datasource_id == datasource_id)
        if query.strip():
            statement = statement.where(DataSourceSchema.name.ilike(needle))
        for item in db.scalars(statement.order_by(DataSourceSchema.name)):
            items.append({"kind": "schema", "id": item.id, "schema": item.name, "name": item.name, "qualified_name": item.qualified_name})
    if kind in {"all", "table"}:
        statement = (
            select(DataSourceTable, DataSourceSchema.name)
            .join(DataSourceSchema, DataSourceTable.schema_id == DataSourceSchema.id)
            .where(DataSourceSchema.datasource_id == datasource_id)
        )
        if query.strip():
            statement = statement.where(or_(DataSourceTable.name.ilike(needle), DataSourceTable.comment.ilike(needle)))
        for item, schema_name in db.execute(statement.order_by(DataSourceSchema.name, DataSourceTable.name)):
            items.append({"kind": "table", "id": item.id, "schema": schema_name, "name": item.name, "qualified_name": item.qualified_name, "comment": item.comment})
    if kind in {"all", "column"}:
        statement = (
            select(DataSourceColumn, DataSourceTable.name, DataSourceSchema.name)
            .join(DataSourceTable, DataSourceColumn.table_id == DataSourceTable.id)
            .join(DataSourceSchema, DataSourceTable.schema_id == DataSourceSchema.id)
            .where(DataSourceSchema.datasource_id == datasource_id)
        )
        if query.strip():
            statement = statement.where(or_(DataSourceColumn.name.ilike(needle), DataSourceColumn.comment.ilike(needle)))
        for item, table_name, schema_name in db.execute(statement.order_by(DataSourceSchema.name, DataSourceTable.name, DataSourceColumn.name)):
            items.append({
                "kind": "column", "id": item.id, "schema": schema_name, "table": table_name,
                "name": item.name, "qualified_name": item.qualified_name, "data_type": item.data_type,
                "primary_key": item.primary_key, "foreign_key": item.foreign_key,
            })
    items.sort(key=lambda item: (item["kind"], item.get("schema", ""), item.get("table", ""), item["name"]))
    total = len(items)
    start = (page - 1) * page_size
    return items[start:start + page_size], total


def relation_rows(db: Session, datasource_id: str) -> list[DataSourceRelation]:
    return list(db.scalars(
        select(DataSourceRelation)
        .where(DataSourceRelation.datasource_id == datasource_id)
        .order_by(DataSourceRelation.source_schema, DataSourceRelation.source_table)
    ))


def _manual_plan(datasource: DataSource, guard: GuardResult, execution: ExecutionResult) -> SQLPlan:
    return SQLPlan(
        question="SQL Workspace read-only execution", intent="MANUAL_SQL", dialect=datasource.type,
        provider="data-workspace", semantic_model_id="manual-sql", semantic_model_version=1,
        selected_entities=guard.tables, selected_tables=guard.tables, selected_columns=guard.columns,
        metrics=[], dimensions=[], joins=[], filters=[], group_by=[], order_by=[], limit=guard.applied_limit or 1,
        generated_sql=guard.normalized_sql or execution.normalized_sql, confidence=1.0,
    )


def execute_sql(
    db: Session,
    principal: Principal,
    datasource: DataSource,
    sql: str,
    *,
    row_limit: int,
    operation: str = "EXECUTE",
) -> SqlWorkspaceRun:
    policy = security_policy(db, datasource.id, row_limit)
    guard = SqlGuard().validate(sql, dialect=datasource.type, policy=policy)
    run = SqlWorkspaceRun(
        workspace_id=principal.workspace_id or "", user_id=principal.user_id or "",
        datasource_id=datasource.id, operation=operation, sql_text=sql,
        normalized_sql=guard.normalized_sql, status="SECURITY_REJECTED" if not guard.allowed else "PLANNING",
        guard_payload=guard.model_dump(mode="json"), execution_payload={}, oracle_payload={},
    )
    db.add(run)
    db.flush()
    if not guard.allowed:
        run.error_code = guard.issues[0].code if guard.issues else "SQL_GUARD_REJECTED"
        run.error_message = guard.issues[0].message if guard.issues else "SQL rejected"
    else:
        if operation == "EXPLAIN":
            execution = QueryExecutor().explain(
                datasource=datasource, normalized_sql=guard.normalized_sql or "", timeout_ms=policy.timeout_ms,
            )
            oracle = OracleResult(
                status="PASSED" if execution.status == "SUCCEEDED" else "NOT_RUN",
                confidence=1 if execution.status == "SUCCEEDED" else 0,
            )
        else:
            execution = QueryExecutor().execute(
                datasource=datasource, normalized_sql=guard.normalized_sql or "",
                row_limit=guard.applied_limit or policy.row_limit, timeout_ms=policy.timeout_ms,
            )
            oracle = ResultOracle().verify(plan=_manual_plan(datasource, guard, execution), guard=guard, execution=execution)
        run.execution_payload = execution.model_dump(mode="json")
        run.oracle_payload = oracle.model_dump(mode="json")
        run.duration_ms = execution.duration_ms
        if execution.status != "SUCCEEDED":
            run.status = "FAILED"
            run.error_code = execution.error_code
            run.error_message = execution.error_message
        else:
            run.status = "SUCCEEDED" if oracle.status == "PASSED" else "ORACLE_MISMATCH"
    record_audit(
        db, principal, action=f"SQL_WORKSPACE_{operation}", resource_type="DATASOURCE", resource_id=datasource.id,
        status="SUCCESS" if run.status == "SUCCEEDED" else run.status,
        details={"run_id": run.id, "guard_allowed": guard.allowed, "result_signature": (run.execution_payload or {}).get("result_signature")},
    )
    db.commit()
    db.refresh(run)
    return run


def mask_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    masked_columns = sorted({column for row in rows for column in row if SENSITIVE_COLUMN.search(column)})
    masked = []
    for row in rows:
        masked.append({column: ("***MASKED***" if column in masked_columns and value is not None else value) for column, value in row.items()})
    return masked, masked_columns


def sample_table(
    db: Session,
    principal: Principal,
    datasource: DataSource,
    schema_name: str,
    table_name: str,
    *,
    page: int,
    page_size: int,
) -> tuple[SqlWorkspaceRun, list[dict[str, Any]], list[str]]:
    columns = list(db.scalars(
        select(DataSourceColumn.name)
        .join(DataSourceTable, DataSourceColumn.table_id == DataSourceTable.id)
        .join(DataSourceSchema, DataSourceTable.schema_id == DataSourceSchema.id)
        .where(
            DataSourceSchema.datasource_id == datasource.id,
            DataSourceSchema.name == schema_name,
            DataSourceTable.name == table_name,
        )
        .order_by(DataSourceColumn.name)
    ))
    if not columns:
        raise LookupError("Table metadata not found; synchronize the datasource first")
    dialect = {"postgresql": "postgres", "mysql": "mysql"}[datasource.type]
    statement = exp.select(*(exp.column(column) for column in columns)).from_(
        exp.Table(this=exp.to_identifier(table_name), db=exp.to_identifier(schema_name))
    ).limit(page_size).offset((page - 1) * page_size)
    sql = statement.sql(dialect=dialect, comments=False)
    run = execute_sql(db, principal, datasource, sql, row_limit=page_size, operation="SAMPLE")
    rows, masked_columns = mask_rows((run.execution_payload or {}).get("rows", []))
    return run, rows, masked_columns


def save_verified_sql(
    db: Session,
    principal: Principal,
    run: SqlWorkspaceRun,
    *,
    owner_name: str,
    status: str,
) -> VerifiedAnswer:
    execution = run.execution_payload or {}
    if run.workspace_id != principal.workspace_id or run.user_id != principal.user_id:
        raise PermissionError("SQL workspace run access denied")
    if run.status != "SUCCEEDED" or (run.oracle_payload or {}).get("status") != "PASSED":
        raise ValueError("Only a successful, Oracle-passed SQL run can be saved")
    if not execution.get("result_signature"):
        raise ValueError("The SQL run has no result signature")
    sort_order = int(db.scalar(select(func.count(VerifiedAnswer.id))) or 0) + 1
    answer = VerifiedAnswer(
        workspace_id=principal.workspace_id or "", question=f"SQL 工作台验证：{run.sql_text[:180]}", module="数据源",
        sql_synced=True, model_name="SQL Workspace", owner_name=owner_name, status=status,
        accuracy_percent=100, sort_order=sort_order, query_run_id=None, sql_text=run.normalized_sql,
        result_signature=execution["result_signature"], semantic_model_version=None,
        semantic_intent={"intent": "MANUAL_SQL", "datasource_id": run.datasource_id},
        sql_plan={"provider": "data-workspace", "guard": run.guard_payload}, result_snapshot=execution,
        chart_spec={}, narrative={"conclusion": "该 SQL 已通过只读校验并保存为 Verified SQL。"},
        datasource_id=run.datasource_id, semantic_model_id=None, oracle_status="PASSED",
        feedback={"source": "SQL_WORKSPACE", "verified_by": principal.user_id},
    )
    db.add(answer)
    db.flush()
    run.verified_answer_id = answer.id
    record_audit(
        db, principal, action="SQL_WORKSPACE_VERIFY", resource_type="ANSWER", resource_id=answer.id,
        details={"workspace_run_id": run.id, "result_signature": answer.result_signature},
    )
    db.commit()
    db.refresh(answer)
    return answer
