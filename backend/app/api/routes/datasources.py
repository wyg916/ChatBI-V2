from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.access import Principal, ensure_resource_access, has_resource_access, record_audit, require_permission
from app.db.session import get_db
from app.models import DataSource, DataSourceColumn, DataSourceSchema, DataSourceTable
from app.schemas.datasource import (
    ColumnRead,
    DataSourceCreate,
    DataSourceRead,
    DataSourceUpdate,
    OperationResult,
    SchemaRead,
    TableRead,
)
from app.services import datasources as service

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
    return DataSourceRead.model_validate(datasource).model_copy(update={
        "table_count": table_count,
        "column_count": column_count,
    })


@router.post("", response_model=DataSourceRead, status_code=status.HTTP_201_CREATED)
def create_datasource(data: DataSourceCreate, db: Session = Depends(get_db), _: Principal = Depends(require_permission("datasource.manage"))):
    return service.create_datasource(db, data)


@router.get("", response_model=list[DataSourceRead])
def list_datasources(db: Session = Depends(get_db), principal: Principal = Depends(require_permission("datasource.read"))):
    datasources = list(db.scalars(select(DataSource).order_by(DataSource.created_at.desc())))
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
def update_datasource(datasource_id: str, data: DataSourceUpdate, db: Session = Depends(get_db), _: Principal = Depends(require_permission("datasource.manage"))):
    datasource = service.update_datasource(db, _get_or_404(db, datasource_id), data)
    table_counts, column_counts = _datasource_counts(db)
    return _read_datasource(
        datasource,
        table_counts.get(datasource_id, 0),
        column_counts.get(datasource_id, 0),
    )


@router.delete("/{datasource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_datasource(datasource_id: str, db: Session = Depends(get_db), _: Principal = Depends(require_permission("datasource.manage"))):
    db.delete(_get_or_404(db, datasource_id))
    db.commit()
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
def list_tables(datasource_id: str, schema: str | None = None, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("datasource.read"))):
    ensure_resource_access(db, principal, resource_type="DATASOURCE", resource_id=datasource_id)
    _get_or_404(db, datasource_id)
    query = (
        select(DataSourceTable, DataSourceSchema.name, func.count(DataSourceColumn.id))
        .join(DataSourceSchema, DataSourceTable.schema_id == DataSourceSchema.id)
        .outerjoin(DataSourceColumn, DataSourceColumn.table_id == DataSourceTable.id)
        .where(DataSourceSchema.datasource_id == datasource_id)
        .group_by(DataSourceTable.id, DataSourceSchema.name)
        .order_by(DataSourceSchema.name, DataSourceTable.name)
    )
    if schema:
        query = query.where(DataSourceSchema.name == schema)
    return [
        TableRead(
            id=table.id,
            schema_name=schema_name,
            name=table.name,
            qualified_name=table.qualified_name,
            comment=table.comment,
            column_count=column_count,
        )
        for table, schema_name, column_count in db.execute(query)
    ]


@router.get("/{datasource_id}/tables/{table}/columns", response_model=list[ColumnRead])
def list_columns(datasource_id: str, table: str, schema: str | None = None, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("datasource.read"))):
    ensure_resource_access(db, principal, resource_type="DATASOURCE", resource_id=datasource_id)
    _get_or_404(db, datasource_id)
    query = (
        select(DataSourceColumn)
        .join(DataSourceTable, DataSourceColumn.table_id == DataSourceTable.id)
        .join(DataSourceSchema, DataSourceTable.schema_id == DataSourceSchema.id)
        .where(DataSourceSchema.datasource_id == datasource_id, DataSourceTable.name == table)
        .order_by(DataSourceColumn.name)
    )
    if schema:
        query = query.where(DataSourceSchema.name == schema)
    return list(db.scalars(query))
