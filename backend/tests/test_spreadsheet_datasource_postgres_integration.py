from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.routes.security import set_resource_permission
from app.core.access import Principal
from app.core.config import get_settings
from app.db.deployment_state import (
    _postgres_helper_checks,
    _postgres_schema_usable,
    spreadsheet_helper_state,
)
from app.models import AppUser, DataSource, DataSourceImport, ResourceGrant, SemanticModel, Workspace
from app.query.context_builder import ContextBuilder
from app.query.executor import QueryExecutor
from app.services.spreadsheet_datasources import delete_managed_datasource, import_spreadsheet
from app.services.datasources import build_connector
from app.schemas.security import ResourcePermissionUpdate


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


def test_datasource_delete_serializes_with_concurrent_resource_grant():
    settings = get_settings()
    assert settings.database_url.startswith("postgresql+psycopg://")
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    datasource_id: str | None = None
    analyst_id: str | None = None
    try:
        with Session(engine, expire_on_commit=False) as delete_db:
            workspace = delete_db.scalar(select(Workspace).order_by(Workspace.created_at))
            assert workspace is not None
            admin = delete_db.scalar(select(AppUser).where(
                AppUser.workspace_id == workspace.id,
                AppUser.role == "ADMIN",
                AppUser.status == "ACTIVE",
            ).order_by(AppUser.created_at))
            assert admin is not None
            analyst = AppUser(
                workspace_id=workspace.id,
                email=f"spreadsheet-lock-{uuid.uuid4().hex[:12]}@example.test",
                display_name="Spreadsheet lock analyst",
                role="ANALYST",
                status="ACTIVE",
            )
            delete_db.add(analyst)
            delete_db.flush()
            datasource, _ = import_spreadsheet(
                delete_db,
                workspace_id=workspace.id,
                name=f"Spreadsheet grant lock {uuid.uuid4().hex[:8]}",
                filename="grant-lock.csv",
                declared_mime="text/csv",
                data=b"id,value\n1,10\n",
            )
            datasource_id = datasource.id
            analyst_id = analyst.id
            delete_db.commit()
            principal = Principal(
                admin.id, workspace.id, admin.email, admin.display_name, admin.role,
            )

            # Hold the same datasource row lock used by the HTTP delete path.
            delete_managed_datasource(delete_db, datasource, commit=False)
            marker = f"chatbi_grant_lock_{uuid.uuid4().hex}"
            started = threading.Event()

            def attempt_grant() -> tuple[int, str]:
                with Session(engine) as grant_db:
                    grant_db.execute(
                        text("SELECT set_config('application_name', :marker, true)"),
                        {"marker": marker},
                    )
                    started.set()
                    try:
                        set_resource_permission(
                            analyst_id,
                            "DATASOURCE",
                            datasource_id,
                            ResourcePermissionUpdate(can_read=True, can_query=True),
                            db=grant_db,
                            principal=principal,
                        )
                    except HTTPException as exc:
                        grant_db.rollback()
                        return exc.status_code, str(exc.detail)
                    return 200, "unexpected grant success"

            with ThreadPoolExecutor(max_workers=1) as pool:
                pending_grant = pool.submit(attempt_grant)
                assert started.wait(timeout=5)
                observed_row_lock_wait = False
                deadline = time.monotonic() + 5
                with Session(engine) as monitor:
                    while time.monotonic() < deadline and not pending_grant.done():
                        wait_type = monitor.scalar(text(
                            "SELECT wait_event_type FROM pg_stat_activity "
                            "WHERE application_name = :marker"
                        ), {"marker": marker})
                        monitor.rollback()
                        if wait_type == "Lock":
                            observed_row_lock_wait = True
                            break
                        threading.Event().wait(0.05)

                # Releasing the delete transaction must make the waiting grant
                # re-check the row and fail because the datasource is gone.
                delete_db.commit()
                outcome = pending_grant.result(timeout=5)

            assert observed_row_lock_wait is True
            assert outcome == (404, "Permission resource not found")
            datasource_id = None

        with Session(engine) as verify_db:
            assert verify_db.scalar(select(ResourceGrant.id).where(
                ResourceGrant.user_id == analyst_id,
                ResourceGrant.resource_type == "DATASOURCE",
            )) is None
            analyst = verify_db.get(AppUser, analyst_id)
            if analyst is not None:
                verify_db.delete(analyst)
                verify_db.commit()
            analyst_id = None
    finally:
        if datasource_id is not None:
            with Session(engine) as cleanup:
                remaining = cleanup.get(DataSource, datasource_id)
                if remaining is not None:
                    delete_managed_datasource(cleanup, remaining)
        if analyst_id is not None:
            with Session(engine) as cleanup:
                remaining_user = cleanup.get(AppUser, analyst_id)
                if remaining_user is not None:
                    cleanup.delete(remaining_user)
                    cleanup.commit()
        engine.dispose()


def test_datasource_delete_preserves_model_and_grant_when_concurrent_migration_wins():
    settings = get_settings()
    assert settings.database_url.startswith("postgresql+psycopg://")
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    source_id: str | None = None
    target_id: str | None = None
    analyst_id: str | None = None
    try:
        with Session(engine, expire_on_commit=False) as setup_db:
            workspace = setup_db.scalar(select(Workspace).order_by(Workspace.created_at))
            assert workspace is not None
            analyst = AppUser(
                workspace_id=workspace.id,
                email=f"spreadsheet-model-lock-{uuid.uuid4().hex[:12]}@example.test",
                display_name="Spreadsheet model lock analyst",
                role="ANALYST",
                status="ACTIVE",
            )
            setup_db.add(analyst)
            setup_db.flush()
            source, _ = import_spreadsheet(
                setup_db,
                workspace_id=workspace.id,
                name=f"Spreadsheet migration source {uuid.uuid4().hex[:8]}",
                filename="migration-source.csv",
                declared_mime="text/csv",
                data=b"id,value\n1,10\n",
            )
            target, _ = import_spreadsheet(
                setup_db,
                workspace_id=workspace.id,
                name=f"Spreadsheet migration target {uuid.uuid4().hex[:8]}",
                filename="migration-target.csv",
                declared_mime="text/csv",
                data=b"id,value\n1,20\n",
            )
            model = SemanticModel(
                workspace_id=workspace.id,
                datasource_id=source.id,
                name=f"Concurrent migrated model {uuid.uuid4().hex[:8]}",
                description="temporary concurrency regression model",
                status="DRAFT",
            )
            setup_db.add(model)
            setup_db.flush()
            grant = ResourceGrant(
                user_id=analyst.id,
                resource_type="SEMANTIC_MODEL",
                resource_id=model.id,
                can_read=True,
                can_query=True,
            )
            setup_db.add(grant)
            setup_db.commit()
            source_id = source.id
            target_id = target.id
            model_id = model.id
            grant_id = grant.id
            analyst_id = analyst.id

        with Session(engine, expire_on_commit=False) as migration_db:
            migrating_model = migration_db.scalar(
                select(SemanticModel).where(SemanticModel.id == model_id).with_for_update()
            )
            assert migrating_model is not None
            migrating_model.datasource_id = target_id
            migration_db.flush()

            marker = f"chatbi_model_delete_lock_{uuid.uuid4().hex}"
            started = threading.Event()

            def attempt_delete() -> str:
                with Session(engine) as delete_db:
                    delete_db.execute(
                        text("SELECT set_config('application_name', :marker, true)"),
                        {"marker": marker},
                    )
                    deleting_source = delete_db.get(DataSource, source_id)
                    assert deleting_source is not None
                    started.set()
                    delete_managed_datasource(delete_db, deleting_source)
                    return "deleted"

            with ThreadPoolExecutor(max_workers=1) as pool:
                pending_delete = pool.submit(attempt_delete)
                assert started.wait(timeout=5)
                observed_model_lock_wait = False
                deadline = time.monotonic() + 5
                with Session(engine) as monitor:
                    while time.monotonic() < deadline and not pending_delete.done():
                        wait_type = monitor.scalar(text(
                            "SELECT wait_event_type FROM pg_stat_activity "
                            "WHERE application_name = :marker"
                        ), {"marker": marker})
                        monitor.rollback()
                        if wait_type == "Lock":
                            observed_model_lock_wait = True
                            break
                        threading.Event().wait(0.05)

                migration_db.commit()
                assert pending_delete.result(timeout=5) == "deleted"

            assert observed_model_lock_wait is True
            source_id = None

        with Session(engine) as verify_db:
            surviving_model = verify_db.get(SemanticModel, model_id)
            surviving_grant = verify_db.get(ResourceGrant, grant_id)
            assert surviving_model is not None
            assert surviving_model.datasource_id == target_id
            assert surviving_grant is not None
            assert surviving_grant.resource_id == model_id

            target = verify_db.get(DataSource, target_id)
            assert target is not None
            delete_managed_datasource(verify_db, target)
            target_id = None
            analyst = verify_db.get(AppUser, analyst_id)
            if analyst is not None:
                verify_db.delete(analyst)
                verify_db.commit()
            analyst_id = None
    finally:
        for remaining_id in (source_id, target_id):
            if remaining_id is None:
                continue
            with Session(engine) as cleanup:
                remaining = cleanup.get(DataSource, remaining_id)
                if remaining is not None:
                    delete_managed_datasource(cleanup, remaining)
        if analyst_id is not None:
            with Session(engine) as cleanup:
                remaining_user = cleanup.get(AppUser, analyst_id)
                if remaining_user is not None:
                    cleanup.delete(remaining_user)
                    cleanup.commit()
        engine.dispose()
