from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

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


@router.post("", response_model=DataSourceRead, status_code=status.HTTP_201_CREATED)
def create_datasource(data: DataSourceCreate, db: Session = Depends(get_db)):
    return service.create_datasource(db, data)


@router.get("", response_model=list[DataSourceRead])
def list_datasources(db: Session = Depends(get_db)):
    return list(db.scalars(select(DataSource).order_by(DataSource.created_at.desc())))


@router.get("/{datasource_id}", response_model=DataSourceRead)
def get_datasource(datasource_id: str, db: Session = Depends(get_db)):
    return _get_or_404(db, datasource_id)


@router.put("/{datasource_id}", response_model=DataSourceRead)
def update_datasource(datasource_id: str, data: DataSourceUpdate, db: Session = Depends(get_db)):
    return service.update_datasource(db, _get_or_404(db, datasource_id), data)


@router.delete("/{datasource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_datasource(datasource_id: str, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, datasource_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{datasource_id}/test", response_model=OperationResult)
def test_datasource(datasource_id: str, db: Session = Depends(get_db)):
    datasource = _get_or_404(db, datasource_id)
    try:
        service.test_datasource(db, datasource)
        return OperationResult(success=True, message="Connection successful")
    except Exception as exc:
        return OperationResult(success=False, message=f"Connection failed: {type(exc).__name__}")


@router.post("/{datasource_id}/sync", response_model=OperationResult)
def sync_datasource(datasource_id: str, db: Session = Depends(get_db)):
    datasource = _get_or_404(db, datasource_id)
    try:
        counts = service.sync_datasource(db, datasource)
        return OperationResult(success=True, message="Metadata synchronized", **counts)
    except Exception as exc:
        db.rollback()
        return OperationResult(success=False, message=f"Metadata synchronization failed: {type(exc).__name__}")


@router.get("/{datasource_id}/schemas", response_model=list[SchemaRead])
def list_schemas(datasource_id: str, db: Session = Depends(get_db)):
    _get_or_404(db, datasource_id)
    return list(db.scalars(select(DataSourceSchema).where(DataSourceSchema.datasource_id == datasource_id).order_by(DataSourceSchema.name)))


@router.get("/{datasource_id}/tables", response_model=list[TableRead])
def list_tables(datasource_id: str, schema: str | None = None, db: Session = Depends(get_db)):
    _get_or_404(db, datasource_id)
    query = (
        select(DataSourceTable, DataSourceSchema.name)
        .join(DataSourceSchema, DataSourceTable.schema_id == DataSourceSchema.id)
        .where(DataSourceSchema.datasource_id == datasource_id)
        .order_by(DataSourceSchema.name, DataSourceTable.name)
    )
    if schema:
        query = query.where(DataSourceSchema.name == schema)
    return [
        TableRead(id=table.id, schema_name=schema_name, name=table.name, qualified_name=table.qualified_name, comment=table.comment)
        for table, schema_name in db.execute(query)
    ]


@router.get("/{datasource_id}/tables/{table}/columns", response_model=list[ColumnRead])
def list_columns(datasource_id: str, table: str, schema: str | None = None, db: Session = Depends(get_db)):
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
