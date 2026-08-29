from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.access import Principal, ensure_resource_access, has_resource_access, record_audit, require_permission
from app.db.session import get_db
from app.core.config import get_settings
from app.models import DataSource, DataSourceColumn, DataSourceSchema, DataSourceTable
from app.schemas.datasource import (
    ColumnRead,
    DataSourceCreate,
    DataSourceRead,
    DataSourceUpdate,
    OperationResult,
    SchemaRead,
    SpreadsheetImportRead,
    SpreadsheetPreviewRead,
    TableRead,
)
from app.services import datasources as service
from app.services.spreadsheet_datasources import (
    SpreadsheetImportError,
    delete_managed_datasource,
    import_spreadsheet,
    spreadsheet_preview,
)

router = APIRouter(prefix="/datasources", tags=["datasources"])


def _get_or_404(db: Session, datasource_id: str) -> DataSource:
    datasource = db.get(DataSource, datasource_id)
    if datasource is None:
        raise HTTPException(status_code=404, detail="Datasource not found")
    return datasource


def _datasource_counts(db: Session) -> tuple[dict[str, int], dict[str, int]]:
    table_rows = db.execute(
        select(DataSourceSchema.datasource_id, func.count(DataSourceTable.id))
        .outerjoin(DataSourceTable, DataSourceTable.schema_id == DataSourceSchema.id)
        .group_by(DataSourceSchema.datasource_id)
    )
    column_rows = db.execute(
        select(DataSourceSchema.datasource_id, func.count(DataSourceColumn.id))
        .join(DataSourceTable, DataSourceTable.schema_id == DataSourceSchema.id)
        .outerjoin(DataSourceColumn, DataSourceColumn.table_id == DataSourceTable.id)
        .group_by(DataSourceSchema.datasource_id)
    )
    table_counts = {datasource_id: count for datasource_id, count in table_rows}
    column_counts = {datasource_id: count for datasource_id, count in column_rows}
    return table_counts, column_counts


def _read_datasource(datasource: DataSource, table_count: int = 0, column_count: int = 0) -> DataSourceRead:
    imported = datasource.spreadsheet_import
    updates = {
        "table_count": table_count,
        "column_count": column_count,
        "import_filename": imported.original_filename if imported else None,
        "import_row_count": imported.row_count if imported else None,
        "import_sheet_count": len(imported.sheet_metadata) if imported else None,
    }
    if imported:
        # The browser only needs managed-import provenance.  Runtime PostgreSQL
        # addressing and the read-only principal stay behind the Backend API.
        updates.update({
            "host": "Backend managed",
            "port": 0,
            "database": "Imported spreadsheet",
            "username": "Managed read-only",
        })
    return DataSourceRead.model_validate(datasource).model_copy(update=updates)


async def _read_spreadsheet_upload(upload: UploadFile) -> tuple[str, str, bytes]:
    filename = (upload.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="SPREADSHEET_FILENAME_REQUIRED")
    limit = get_settings().spreadsheet_import_max_bytes
    data = await upload.read(limit + 1)
    await upload.close()
    if len(data) > limit:
        raise HTTPException(status_code=413, detail="SPREADSHEET_FILE_SIZE_LIMIT_EXCEEDED")
    return filename, upload.content_type or "application/octet-stream", data


@router.post("", response_model=DataSourceRead, status_code=status.HTTP_201_CREATED)
def create_datasource(data: DataSourceCreate, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("datasource.manage"))):
    return service.create_datasource(db, data, principal.workspace_id)


@router.post("/import/preview", response_model=SpreadsheetPreviewRead)
async def preview_spreadsheet_datasource(
    file: UploadFile = File(...),
    principal: Principal = Depends(require_permission("datasource.manage")),
):
    del principal  # Permission dependency is the authorization boundary.
    filename, media_type, data = await _read_spreadsheet_upload(file)
    try:
        return spreadsheet_preview(filename, media_type, data)
    except SpreadsheetImportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


@router.post("/import", response_model=SpreadsheetImportRead, status_code=status.HTTP_201_CREATED)
async def import_spreadsheet_datasource(
    name: str = Form(..., min_length=1, max_length=255),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("datasource.manage")),
):
    filename, media_type, data = await _read_spreadsheet_upload(file)
    try:
        datasource, preview = import_spreadsheet(
            db,
            workspace_id=principal.workspace_id,
            name=name,
            filename=filename,
            declared_mime=media_type,
            data=data,
        )
        record_audit(
            db,
            principal,
            action="IMPORT",
            resource_type="DATASOURCE",
            resource_id=datasource.id,
            details={
                "format": preview["format"],
                "file_sha256": preview["file_sha256"],
                "rows": preview["row_count"],
                "columns": preview["column_count"],
                "sheets": preview["sheet_count"],
            },
        )
        table_counts, column_counts = _datasource_counts(db)
        result = SpreadsheetImportRead(
            datasource=_read_datasource(
                datasource,
                table_counts.get(datasource.id, 0),
                column_counts.get(datasource.id, 0),
            ),
            preview=SpreadsheetPreviewRead.model_validate(preview),
        )
        db.commit()
        return result
    except SpreadsheetImportError as exc:
        db.rollback()
        record_audit(
            db,
            principal,
            action="IMPORT",
            resource_type="DATASOURCE",
            status="FAILED",
            details={"error_code": exc.code},
        )
        db.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    except Exception as exc:
        db.rollback()
        record_audit(
            db,
            principal,
            action="IMPORT",
            resource_type="DATASOURCE",
            status="FAILED",
            details={"error_type": type(exc).__name__},
        )
        db.commit()
        raise HTTPException(status_code=400, detail="SPREADSHEET_IMPORT_FAILED") from exc


@router.get("", response_model=list[DataSourceRead])
def list_datasources(
    query: str = "",
    datasource_type: str = Query(default="all", alias="type", pattern="^(all|postgresql|mysql|excel)$"),
    connection_status: str = Query(default="all", alias="status", pattern="^(all|normal|attention)$"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("datasource.read")),
):
    statement = select(DataSource).where(DataSource.workspace_id == principal.workspace_id)
    if query.strip():
        keyword = f"%{query.strip()}%"
        statement = statement.where(or_(
            DataSource.name.ilike(keyword),
            DataSource.database.ilike(keyword),
            DataSource.type.ilike(keyword),
        ))
    if datasource_type != "all":
        statement = statement.where(DataSource.type == datasource_type)
    normal_statuses = ("CONNECTED", "SYNCED")
    if connection_status == "normal":
        statement = statement.where(DataSource.status.in_(normal_statuses))
    elif connection_status == "attention":
        statement = statement.where(~DataSource.status.in_(normal_statuses))
    datasources = list(db.scalars(statement.order_by(DataSource.created_at.desc())))
    datasources = [item for item in datasources if has_resource_access(db, principal, resource_type="DATASOURCE", resource_id=item.id)]
    table_counts, column_counts = _datasource_counts(db)
    return [
        _read_datasource(item, table_counts.get(item.id, 0), column_counts.get(item.id, 0))
        for item in datasources
    ]


@router.get("/{datasource_id}", response_model=DataSourceRead)
def get_datasource(datasource_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("datasource.read"))):
    ensure_resource_access(db, principal, resource_type="DATASOURCE", resource_id=datasource_id)
    datasource = _get_or_404(db, datasource_id)
    table_counts, column_counts = _datasource_counts(db)
    return _read_datasource(datasource, table_counts.get(datasource_id, 0), column_counts.get(datasource_id, 0))


@router.put("/{datasource_id}", response_model=DataSourceRead)
def update_datasource(datasource_id: str, data: DataSourceUpdate, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("datasource.manage"))):
    ensure_resource_access(db, principal, resource_type="DATASOURCE", resource_id=datasource_id)
    try:
        datasource = service.update_datasource(db, _get_or_404(db, datasource_id), data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    table_counts, column_counts = _datasource_counts(db)
    return _read_datasource(
        datasource,
        table_counts.get(datasource_id, 0),
        column_counts.get(datasource_id, 0),
    )


@router.delete("/{datasource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_datasource(datasource_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("datasource.manage"))):
    ensure_resource_access(db, principal, resource_type="DATASOURCE", resource_id=datasource_id)
    try:
        delete_managed_datasource(db, _get_or_404(db, datasource_id))
    except SpreadsheetImportError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{datasource_id}/test", response_model=OperationResult)
def test_datasource(datasource_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("datasource.read"))):
    ensure_resource_access(db, principal, resource_type="DATASOURCE", resource_id=datasource_id)
    datasource = _get_or_404(db, datasource_id)
    try:
        service.test_datasource(db, datasource)
        return OperationResult(success=True, message="Connection successful")
    except Exception as exc:
        return OperationResult(success=False, message=f"Connection failed: {type(exc).__name__}")


@router.post("/{datasource_id}/sync", response_model=OperationResult)
def sync_datasource(
    datasource_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("datasource.manage")),
):
    ensure_resource_access(db, principal, resource_type="DATASOURCE", resource_id=datasource_id)
    datasource = _get_or_404(db, datasource_id)
    try:
        counts = service.sync_datasource(db, datasource)
        record_audit(db, principal, action="SYNC", resource_type="DATASOURCE", resource_id=datasource_id, details=counts)
        db.commit()
        return OperationResult(success=True, message="Metadata synchronized", **counts)
    except Exception as exc:
        db.rollback()
        record_audit(
            db, principal, action="SYNC", resource_type="DATASOURCE", resource_id=datasource_id,
            status="FAILED", details={"error_type": type(exc).__name__},
        )
        db.commit()
        return OperationResult(success=False, message=f"Metadata synchronization failed: {type(exc).__name__}")


@router.get("/{datasource_id}/schemas", response_model=list[SchemaRead])
def list_schemas(datasource_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("datasource.read"))):
    ensure_resource_access(db, principal, resource_type="DATASOURCE", resource_id=datasource_id)
    _get_or_404(db, datasource_id)
    rows = db.execute(
        select(DataSourceSchema, func.count(DataSourceTable.id))
        .outerjoin(DataSourceTable, DataSourceTable.schema_id == DataSourceSchema.id)
        .where(DataSourceSchema.datasource_id == datasource_id)
        .group_by(DataSourceSchema.id)
        .order_by(DataSourceSchema.name)
    )
    return [
        SchemaRead.model_validate(schema).model_copy(update={"table_count": table_count})
        for schema, table_count in rows
    ]


@router.get("/{datasource_id}/tables", response_model=list[TableRead])
def list_tables(
    datasource_id: str,
    schema: str | None = None,
    query: str = "",
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("datasource.read")),
):
    ensure_resource_access(db, principal, resource_type="DATASOURCE", resource_id=datasource_id)
    _get_or_404(db, datasource_id)
    statement = (
        select(DataSourceTable, DataSourceSchema.name, func.count(DataSourceColumn.id))
        .join(DataSourceSchema, DataSourceTable.schema_id == DataSourceSchema.id)
        .outerjoin(DataSourceColumn, DataSourceColumn.table_id == DataSourceTable.id)
        .where(DataSourceSchema.datasource_id == datasource_id)
        .group_by(DataSourceTable.id, DataSourceSchema.name)
        .order_by(DataSourceSchema.name, DataSourceTable.name)
    )
    if schema:
        statement = statement.where(DataSourceSchema.name == schema)
    if query.strip():
        keyword = f"%{query.strip()}%"
        statement = statement.where(or_(DataSourceTable.name.ilike(keyword), DataSourceTable.comment.ilike(keyword)))
    return [
        TableRead(
            id=table.id,
            schema_name=schema_name,
            name=table.name,
            qualified_name=table.qualified_name,
            comment=table.comment,
            column_count=column_count,
        )
        for table, schema_name, column_count in db.execute(statement)
    ]


@router.get("/{datasource_id}/tables/{table}/columns", response_model=list[ColumnRead])
def list_columns(datasource_id: str, table: str, schema: str | None = None, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("datasource.read"))):
    ensure_resource_access(db, principal, resource_type="DATASOURCE", resource_id=datasource_id)
    _get_or_404(db, datasource_id)
    can_query = has_resource_access(
        db, principal, resource_type="DATASOURCE", resource_id=datasource_id, query=True,
    )
    query = (
        select(DataSourceColumn)
        .join(DataSourceTable, DataSourceColumn.table_id == DataSourceTable.id)
        .join(DataSourceSchema, DataSourceTable.schema_id == DataSourceSchema.id)
        .where(DataSourceSchema.datasource_id == datasource_id, DataSourceTable.name == table)
        .order_by(DataSourceColumn.name)
    )
    if schema:
        query = query.where(DataSourceSchema.name == schema)
    return [
        ColumnRead.model_validate(column).model_copy(
            update={"sample_values": list(column.sample_values or []) if can_query else []},
        )
        for column in db.scalars(query)
    ]
