from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.deployment_state import (
    _postgres_helper_checks,
    _postgres_schema_usable,
    spreadsheet_helper_state,
)
from app.models import DataSourceImport, SemanticModel, Workspace
from app.query.context_builder import ContextBuilder
from app.query.executor import QueryExecutor
from app.services.spreadsheet_datasources import delete_managed_datasource, import_spreadsheet
from app.services.datasources import build_connector


pytestmark = pytest.mark.skipif(
    os.getenv("CHATBI_RUN_LOCAL_POSTGRES_SPREADSHEET_TEST") != "YES",
    reason="requires the authorized local PostgreSQL baseline",
)


def test_local_postgres_spreadsheet_materialization_is_queryable_and_cleanup_is_scoped():
    settings = get_settings()
    assert settings.database_url.startswith("postgresql+psycopg://")
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    datasource = None
    second_datasource = None
    storage_schema = None
    try:
        with Session(engine, expire_on_commit=False) as db:
            assert spreadsheet_helper_state(db)["available"] is True
            assert _postgres_helper_checks(
                db, ("chatbi_admin.missing_excel_reader(text)",)
            ) == [{
                "signature": "chatbi_admin.missing_excel_reader(text)",
                "available": False,
            }]
            assert _postgres_schema_usable(db, "chatbi_admin") is True
            assert _postgres_schema_usable(db, "chatbi_admin_missing") is False
            workspace = db.scalar(select(Workspace).order_by(Workspace.created_at))
            assert workspace is not None
            datasource, preview = import_spreadsheet(
                db,
                workspace_id=workspace.id,
                name=f"Spreadsheet integration {uuid.uuid4().hex[:8]}",
                filename="integration.csv",
                declared_mime="text/csv",
                data="order_id,revenue,region\n1,88.5,华东\n2,120.0,华南\n".encode("utf-8"),
            )
            storage_schema = preview["storage_schema"]
            import_row = db.scalar(
                select(DataSourceImport).where(DataSourceImport.datasource_id == datasource.id)
            )
            assert import_row is not None
            table_name = import_row.sheet_metadata[0]["table_name"]

            semantic_model = SemanticModel(
                workspace_id=workspace.id,
                datasource_id=datasource.id,
                name=f"Spreadsheet integration {uuid.uuid4().hex[:8]}",
                description="temporary managed spreadsheet integration model",
                status="DRAFT",
            )
            db.add(semantic_model)
            db.commit()
            context = ContextBuilder().build(
                db,
                question="收入有多少",
                workspace=workspace,
                datasource=datasource,
                semantic_model=semantic_model,
                row_limit=10,
            )
            assert context.dialect == "postgresql"
            assert table_name in context.security_policy.allowed_tables

            execution = QueryExecutor().execute(
                datasource=datasource,
                normalized_sql=f'SELECT COUNT(*) AS row_count FROM "{table_name}" LIMIT 10',
                row_limit=10,
                timeout_ms=10_000,
            )
            assert execution.status == "SUCCEEDED", execution.error_message
            assert execution.dialect == "postgresql"
            assert execution.rows == [{"row_count": 2}]

            second_datasource, second_preview = import_spreadsheet(
                db,
                workspace_id=workspace.id,
                name=f"Spreadsheet isolation {uuid.uuid4().hex[:8]}",
                filename="isolation.csv",
                declared_mime="text/csv",
                data="item_id,amount\n1,42\n".encode("utf-8"),
            )
            second_import = db.scalar(
                select(DataSourceImport).where(DataSourceImport.datasource_id == second_datasource.id)
            )
            assert second_import is not None
            second_table = second_import.sheet_metadata[0]["table_name"]
            assert datasource.username.startswith("chatbi_excel_")
            assert datasource.username != second_datasource.username
            role_flags = db.execute(text(
                "SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication "
                "FROM pg_roles WHERE rolname = :role"
            ), {"role": datasource.username}).one()
            assert tuple(role_flags) == (False, False, False, False)
            connector = build_connector(datasource)
            reader_engine = connector._engine()
            try:
                with reader_engine.connect() as reader:
                    assert reader.execute(text(
                        f'SELECT COUNT(*) FROM "{storage_schema}"."{table_name}"'
                    )).scalar_one() == 2
                with pytest.raises(DBAPIError):
                    with reader_engine.connect() as reader:
                        reader.execute(text(
                            f'SELECT COUNT(*) FROM "{second_preview["storage_schema"]}"."{second_table}"'
                        )).scalar_one()
            finally:
                reader_engine.dispose()

            datasource_id = datasource.id
            reader_role = datasource.username
            semantic_model_id = semantic_model.id
            delete_managed_datasource(db, datasource)
            db.expire_all()
            assert db.get(DataSourceImport, import_row.id) is None
            assert db.execute(text(
                "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = :schema"
            ), {"schema": storage_schema}).scalar_one() == 0
            assert db.get(SemanticModel, semantic_model_id) is None
            assert db.execute(text(
                "SELECT COUNT(*) FROM pg_roles WHERE rolname = :role"
            ), {"role": reader_role}).scalar_one() == 0
            assert datasource_id
            delete_managed_datasource(db, second_datasource)
            second_datasource = None
    finally:
        if datasource is not None:
            with Session(engine) as cleanup:
                still_present = cleanup.get(type(datasource), datasource.id)
                if still_present is not None:
                    delete_managed_datasource(cleanup, still_present)
        if second_datasource is not None:
            with Session(engine) as cleanup:
                still_present = cleanup.get(type(second_datasource), second_datasource.id)
                if still_present is not None:
                    delete_managed_datasource(cleanup, still_present)
        engine.dispose()
