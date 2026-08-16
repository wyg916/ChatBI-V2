from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors import connector_for
from app.connectors.base import ConnectorMetadata
from app.core.security import decrypt_secret, encrypt_secret
from app.metadata import qualified_name
from app.models import (
    DataSource,
    DataSourceColumn,
    DataSourceRelation,
    DataSourceSchema,
    DataSourceTable,
    Workspace,
)
from app.schemas.datasource import DataSourceCreate, DataSourceUpdate


def default_workspace(db: Session) -> Workspace:
    workspace = db.scalar(select(Workspace).order_by(Workspace.created_at))
    if workspace is None:
        workspace = Workspace(name="Default Workspace")
        db.add(workspace)
        db.flush()
    return workspace


def create_datasource(db: Session, data: DataSourceCreate) -> DataSource:
    workspace = default_workspace(db)
    datasource = DataSource(
        workspace_id=workspace.id,
        name=data.name,
        type=data.type,
        host=data.host,
        port=data.port,
        database=data.database,
        username=data.username,
        password_encrypted=encrypt_secret(data.password.get_secret_value()),
        ssl=data.ssl,
        schema=data.schema_name,
    )
    db.add(datasource)
    db.commit()
    db.refresh(datasource)
    return datasource


def update_datasource(db: Session, datasource: DataSource, data: DataSourceUpdate) -> DataSource:
    values = data.model_dump(exclude_unset=True, exclude={"password"})
    for key, value in values.items():
        if key == "schema_name":
            key = "schema"
        setattr(datasource, key, value)
    if data.password is not None:
        datasource.password_encrypted = encrypt_secret(data.password.get_secret_value())
    db.commit()
    db.refresh(datasource)
    return datasource


def build_connector(datasource: DataSource):
    return connector_for(
        datasource.type,
        host=datasource.host,
        port=datasource.port,
        database=datasource.database,
        username=datasource.username,
        password=decrypt_secret(datasource.password_encrypted),
        ssl=datasource.ssl,
        schema=datasource.schema,
    )


def test_datasource(db: Session, datasource: DataSource) -> None:
    try:
        build_connector(datasource).test_connection()
    except Exception:
        datasource.status = "ERROR"
        db.commit()
        raise
    datasource.status = "CONNECTED"
    db.commit()


def store_metadata(db: Session, datasource: DataSource, metadata: ConnectorMetadata) -> dict[str, int]:
    db.execute(delete(DataSourceRelation).where(DataSourceRelation.datasource_id == datasource.id))
    for schema in list(datasource.schemas):
        db.delete(schema)
    db.flush()

    schema_models: dict[str, DataSourceSchema] = {}
    for schema_name in metadata.schemas:
        schema_model = DataSourceSchema(
            datasource_id=datasource.id,
            name=schema_name,
            qualified_name=qualified_name(datasource.id, schema_name),
        )
        db.add(schema_model)
        db.flush()
        schema_models[schema_name] = schema_model

    column_count = 0
    for table in metadata.tables:
        schema_model = schema_models.get(table.schema)
        if schema_model is None:
            schema_model = DataSourceSchema(
                datasource_id=datasource.id,
                name=table.schema,
                qualified_name=qualified_name(datasource.id, table.schema),
            )
            db.add(schema_model)
            db.flush()
            schema_models[table.schema] = schema_model
        table_model = DataSourceTable(
            schema_id=schema_model.id,
            name=table.name,
            qualified_name=qualified_name(schema_model.qualified_name, table.name),
            comment=table.comment,
        )
        db.add(table_model)
        db.flush()
        for column in table.columns:
            db.add(DataSourceColumn(
                table_id=table_model.id,
                name=column.name,
                qualified_name=qualified_name(table_model.qualified_name, column.name),
                data_type=column.data_type,
                nullable=column.nullable,
                primary_key=column.primary_key,
                foreign_key=column.foreign_key,
                default=column.default,
                comment=column.comment,
                sample_values=column.sample_values,
            ))
            column_count += 1

    for relation in metadata.relations:
        db.add(DataSourceRelation(
            datasource_id=datasource.id,
            source_schema=relation.source_schema,
            source_table=relation.source_table,
            source_columns=relation.source_columns,
            target_schema=relation.target_schema,
            target_table=relation.target_table,
            target_columns=relation.target_columns,
        ))

    datasource.status = "SYNCED"
    datasource.last_sync_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "schemas": len(schema_models),
        "tables": len(metadata.tables),
        "columns": column_count,
        "relationships": len(metadata.relations),
    }


def sync_datasource(db: Session, datasource: DataSource) -> dict[str, int]:
    metadata = build_connector(datasource).sync_metadata()
    return store_metadata(db, datasource, metadata)
