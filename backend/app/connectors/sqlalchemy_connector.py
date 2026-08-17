from typing import Any

from sqlalchemy import URL, create_engine, inspect, text

from app.connectors.base import (
    ColumnMetadata,
    ConnectorMetadata,
    DataSourceConnector,
    RelationMetadata,
    TableMetadata,
)


class SQLAlchemyConnector(DataSourceConnector):
    drivername: str

    def __init__(self, *, host: str, port: int, database: str, username: str, password: str, ssl: bool = False, schema: str | None = None):
        self.schema = schema
        query = self.ssl_query() if ssl else {}
        self.url = URL.create(
            drivername=self.drivername,
            username=username,
            password=password,
            host=host,
            port=port,
            database=database,
            query=query,
        )

    def ssl_query(self) -> dict[str, str]:
        return {}

    def _engine(self):
        return create_engine(self.url, pool_pre_ping=True, connect_args={"connect_timeout": 5})

    def test_connection(self) -> None:
        engine = self._engine()
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        finally:
            engine.dispose()

    def read_rows(self, statement: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        normalized = statement.strip().rstrip(";")
        if not normalized.upper().startswith(("SELECT ", "WITH ")) or ";" in normalized:
            raise ValueError("Only one SELECT or WITH ... SELECT statement is allowed")
        engine = self._engine()
        try:
            with engine.connect() as connection:
                return [dict(row) for row in connection.execute(text(normalized), parameters or {}).mappings()]
        finally:
            engine.dispose()

    def _schema_names(self, inspector) -> list[str]:
        if self.schema:
            return [self.schema]
        ignored = {"information_schema", "pg_catalog", "mysql", "performance_schema", "sys"}
        return [name for name in inspector.get_schema_names() if name not in ignored]

    def sync_metadata(self) -> ConnectorMetadata:
        engine = self._engine()
        result = ConnectorMetadata()
        try:
            inspector = inspect(engine)
            result.schemas = self._schema_names(inspector)
            for schema_name in result.schemas:
                for table_name in inspector.get_table_names(schema=schema_name):
                    pk_columns = set((inspector.get_pk_constraint(table_name, schema=schema_name) or {}).get("constrained_columns") or [])
                    foreign_keys = inspector.get_foreign_keys(table_name, schema=schema_name)
                    fk_columns = {column for item in foreign_keys for column in (item.get("constrained_columns") or [])}
                    table = TableMetadata(
                        schema=schema_name,
                        name=table_name,
                        comment=(inspector.get_table_comment(table_name, schema=schema_name) or {}).get("text"),
                    )
                    for column in inspector.get_columns(table_name, schema=schema_name):
                        table.columns.append(ColumnMetadata(
                            name=column["name"],
                            data_type=str(column["type"]),
                            nullable=bool(column.get("nullable", True)),
                            primary_key=column["name"] in pk_columns,
                            foreign_key=column["name"] in fk_columns,
                            default=None if column.get("default") is None else str(column["default"]),
                            comment=column.get("comment"),
                        ))
                    result.tables.append(table)
                    for item in foreign_keys:
                        result.relations.append(RelationMetadata(
                            source_schema=schema_name,
                            source_table=table_name,
                            source_columns=item.get("constrained_columns") or [],
                            target_schema=item.get("referred_schema"),
                            target_table=item["referred_table"],
                            target_columns=item.get("referred_columns") or [],
                        ))
            return result
        finally:
            engine.dispose()


class PostgreSQLConnector(SQLAlchemyConnector):
    drivername = "postgresql+psycopg"

    def ssl_query(self) -> dict[str, str]:
        return {"sslmode": "require"}


class MySQLConnector(SQLAlchemyConnector):
    drivername = "mysql+pymysql"

    def ssl_query(self) -> dict[str, str]:
        return {"ssl_verify_cert": "true"}


def connector_for(kind: str, **kwargs) -> DataSourceConnector:
    connector_type = {"postgresql": PostgreSQLConnector, "mysql": MySQLConnector}.get(kind)
    if connector_type is None:
        raise ValueError(f"Unsupported datasource type: {kind}")
    return connector_type(**kwargs)
