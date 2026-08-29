from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlglot.errors import ParseError

from app.core.access import Principal, ensure_resource_access, require_permission
from app.core.config import get_settings
from app.core.data_safety import redact_public_sql, redact_public_sql_payload
from app.db.session import get_db
from app.models import ResourceGrant, SqlWorkspaceRun
from app.schemas.data_workspace import (
    CatalogSearchResponse,
    FormatSqlRequest,
    RelationshipRead,
    SampleResponse,
    SqlFormatResponse,
    SqlWorkspaceRequest,
    VerifyWorkspaceRunRequest,
    VerifyWorkspaceRunResponse,
    WorkspaceHistoryResponse,
    WorkspaceRunRead,
)
from app.services import data_workspace as service
from app.services.datasources import runtime_dialect


router = APIRouter(prefix="/data-workspace", tags=["data workspace"])


def _datasource(db: Session, principal: Principal, datasource_id: str, *, query_access: bool = False):
    ensure_resource_access(
        db, principal, resource_type="DATASOURCE", resource_id=datasource_id, query=query_access,
    )
    try:
        return service.datasource_or_error(db, datasource_id, principal.workspace_id or "")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _run_read(db: Session, run: SqlWorkspaceRun) -> WorkspaceRunRead:
    dialect = str((run.guard_payload or {}).get("dialect") or "postgresql")
    try:
        sensitive_columns = service.security_policy(
            db, run.datasource_id, get_settings().query_row_limit,
        ).sensitive_columns
    except (LookupError, ValueError):
        # A historical run must remain safe to read even if its catalog has
        # since been removed or is no longer available.
        sensitive_columns = []
    public_error = redact_public_sql_payload({
        "error_code": run.error_code,
        "error_message": run.error_message,
    }, sensitive_columns, dialect=dialect)
    return WorkspaceRunRead(
        id=run.id, datasource_id=run.datasource_id, operation=run.operation,
        sql_text=redact_public_sql(
            run.sql_text, sensitive_columns, dialect=dialect,
        ) or "",
        normalized_sql=redact_public_sql(
            run.normalized_sql, sensitive_columns, dialect=dialect,
        ),
        status=run.status,
        guard=redact_public_sql_payload(
            run.guard_payload or {}, sensitive_columns, dialect=dialect,
        ),
        execution=redact_public_sql_payload(
            run.execution_payload or {}, sensitive_columns, dialect=dialect,
        ),
        oracle=redact_public_sql_payload(
            run.oracle_payload or {}, sensitive_columns, dialect=dialect,
        ),
        duration_ms=run.duration_ms,
        error_code=public_error["error_code"], error_message=public_error["error_message"],
        verified_answer_id=run.verified_answer_id, created_at=run.created_at,
    )


def _run_or_404(db: Session, principal: Principal, run_id: str) -> SqlWorkspaceRun:
    run = db.get(SqlWorkspaceRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="SQL workspace run not found")
    if run.workspace_id != principal.workspace_id or run.user_id != principal.user_id:
        raise HTTPException(status_code=403, detail="SQL workspace run access denied")
    ensure_resource_access(
        db, principal, resource_type="DATASOURCE", resource_id=run.datasource_id, query=True,
    )
    return run


@router.get("/datasources/{datasource_id}/search", response_model=CatalogSearchResponse)
def search_catalog(
    datasource_id: str,
    q: str = Query(default="", max_length=255),
    kind: str = Query(default="all", pattern="^(all|schema|table|column)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("datasource.read")),
):
    _datasource(db, principal, datasource_id)
    items, total = service.catalog_search(
        db, datasource_id, query=q, kind=kind, page=page, page_size=page_size,
    )
    return CatalogSearchResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/datasources/{datasource_id}/relationships", response_model=list[RelationshipRead])
def relationships(
    datasource_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("datasource.read")),
):
    _datasource(db, principal, datasource_id)
    return [RelationshipRead.model_validate(item, from_attributes=True) for item in service.relation_rows(db, datasource_id)]


@router.get("/datasources/{datasource_id}/schemas/{schema_name}/tables/{table_name}/sample", response_model=SampleResponse)
def sample_values(
    datasource_id: str,
    schema_name: str,
    table_name: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("query.ask")),
):
    datasource = _datasource(db, principal, datasource_id, query_access=True)
    try:
        run, rows, masked_columns = service.sample_table(
            db, principal, datasource, schema_name, table_name, page=page, page_size=page_size,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if run.status != "SUCCEEDED":
        raise HTTPException(
            status_code=422,
            detail=f"Sample query failed ({run.error_code or run.status})",
        )
    return SampleResponse(
        datasource_id=datasource_id, schema_name=schema_name, table_name=table_name,
        columns=list((run.execution_payload or {}).get("columns", [])), rows=rows, row_count=len(rows),
        page=page, page_size=page_size, masked_columns=masked_columns,
        result_signature=(run.execution_payload or {}).get("result_signature"),
    )


@router.post("/sql/format", response_model=SqlFormatResponse)
def format_workspace_sql(
    data: FormatSqlRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("query.ask")),
):
    datasource = _datasource(db, principal, data.datasource_id, query_access=True)
    try:
        formatted = service.format_sql(data.sql, runtime_dialect(datasource))
    except (ParseError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail="SQL parse error; the statement could not be formatted",
        ) from exc
    return SqlFormatResponse(dialect=runtime_dialect(datasource), formatted_sql=formatted)


@router.post("/sql/execute", response_model=WorkspaceRunRead, status_code=status.HTTP_201_CREATED)
def execute_workspace_sql(
    data: SqlWorkspaceRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("query.ask")),
):
    datasource = _datasource(db, principal, data.datasource_id, query_access=True)
    return _run_read(db, service.execute_sql(db, principal, datasource, data.sql, row_limit=data.row_limit))


@router.post("/sql/explain", response_model=WorkspaceRunRead, status_code=status.HTTP_201_CREATED)
def explain_workspace_sql(
    data: SqlWorkspaceRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("query.ask")),
):
    datasource = _datasource(db, principal, data.datasource_id, query_access=True)
    return _run_read(db, service.execute_sql(
        db, principal, datasource, data.sql, row_limit=data.row_limit, operation="EXPLAIN",
    ))


@router.get("/sql/history", response_model=WorkspaceHistoryResponse)
def workspace_history(
    datasource_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("query.ask")),
):
    filters = [
        SqlWorkspaceRun.workspace_id == principal.workspace_id,
        SqlWorkspaceRun.user_id == principal.user_id,
    ]
    if principal.role != "ADMIN":
        authorized_datasources = select(ResourceGrant.resource_id).where(
            ResourceGrant.user_id == principal.user_id,
            ResourceGrant.resource_type == "DATASOURCE",
            ResourceGrant.can_query.is_(True),
        )
        filters.append(SqlWorkspaceRun.datasource_id.in_(authorized_datasources))
    if datasource_id:
        _datasource(db, principal, datasource_id, query_access=True)
        filters.append(SqlWorkspaceRun.datasource_id == datasource_id)
    total = int(db.scalar(select(func.count(SqlWorkspaceRun.id)).where(*filters)) or 0)
    items = list(db.scalars(
        select(SqlWorkspaceRun).where(*filters).order_by(SqlWorkspaceRun.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ))
    return WorkspaceHistoryResponse(items=[_run_read(db, item) for item in items], total=total, page=page, page_size=page_size)


@router.post("/sql/history/{run_id}/replay", response_model=WorkspaceRunRead, status_code=status.HTTP_201_CREATED)
def replay_workspace_sql(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("query.ask")),
):
    previous = _run_or_404(db, principal, run_id)
    datasource = _datasource(db, principal, previous.datasource_id, query_access=True)
    return _run_read(db, service.execute_sql(
        db, principal, datasource, previous.sql_text, row_limit=get_settings().query_row_limit,
        operation="EXPLAIN" if previous.operation == "EXPLAIN" else "REPLAY",
    ))


@router.post("/sql/history/{run_id}/verify", response_model=VerifyWorkspaceRunResponse, status_code=status.HTTP_201_CREATED)
def verify_workspace_sql(
    run_id: str,
    data: VerifyWorkspaceRunRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("answer.manage")),
):
    run = _run_or_404(db, principal, run_id)
    _datasource(db, principal, run.datasource_id, query_access=True)
    try:
        answer = service.save_verified_sql(
            db, principal, run, owner_name=data.owner_name, status=data.status,
        )
    except (PermissionError, ValueError) as exc:
        code = 403 if isinstance(exc, PermissionError) else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return VerifyWorkspaceRunResponse(
        run_id=run.id, answer_id=answer.id, status=answer.status,
        result_signature=answer.result_signature or "",
    )
