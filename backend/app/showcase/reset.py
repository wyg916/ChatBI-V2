"""Reset the local ChatBI showcase to a reproducible metadata baseline.

The command is deliberately not exposed through HTTP.  It runs only from the
repository's local PowerShell launcher, using the application-owned metadata
database connection.  Business demo schemas remain read-only and untouched.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

import app.models as _models  # noqa: F401 - register every mapped table
from app.core.auth import hash_password
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import (
    AppUser,
    AuthSession,
    Dashboard,
    DataSource,
    DataSourceColumn,
    DataSourceRelation,
    DataSourceSchema,
    DataSourceTable,
    EvaluationRun,
    KnowledgeDocument,
    LoginAttempt,
    SemanticModel,
    VerifiedAnswer,
)
from app.services.datasources import sync_datasource
from app.services.runtime_seed import seed_v1_runtime
from app.services.seed import seed_demo_semantic_model
from app.services.spreadsheet_datasources import delete_managed_datasource


ADMIN_EMAIL = "admin@chatbi.local"
ANALYST_EMAIL = "analyst@chatbi.local"


def _validated_password(value: str, *, label: str) -> str:
    if len(value) < 10:
        raise RuntimeError(f"{label} must contain at least 10 characters")
    return value


def set_showcase_credentials(
    db: Session,
    *,
    admin_password: str,
    analyst_password: str,
    revoke_sessions: bool = True,
) -> None:
    """Rotate the two public local-demo accounts to the documented values."""

    credentials = {
        ADMIN_EMAIL: _validated_password(admin_password, label="admin password"),
        ANALYST_EMAIL: _validated_password(analyst_password, label="analyst password"),
    }
    users = {
        user.email: user
        for user in db.scalars(select(AppUser).where(AppUser.email.in_(credentials)))
    }
    missing = sorted(set(credentials) - set(users))
    if missing:
        raise RuntimeError(f"Showcase users are missing after seed: {', '.join(missing)}")

    changed_at = datetime.now(timezone.utc)
    for email, password in credentials.items():
        user = users[email]
        user.password_hash = hash_password(password)
        user.password_changed_at = changed_at
        user.status = "ACTIVE"

    if revoke_sessions:
        db.execute(delete(AuthSession).where(AuthSession.user_id.in_([item.id for item in users.values()])))
        db.execute(delete(LoginAttempt))
    db.commit()


def _truncate_metadata(db: Session) -> None:
    # Managed spreadsheet imports own database schemas and scoped reader roles
    # outside ORM metadata.  Reclaim them before truncating provenance rows so
    # a local Showcase reset cannot strand queryable data or login roles.
    managed_sources = list(db.scalars(select(DataSource).where(DataSource.type == "excel")))
    for datasource in managed_sources:
        delete_managed_datasource(db, datasource)
    tables = sorted(Base.metadata.tables.values(), key=lambda item: item.name)
    dialect = db.get_bind().dialect
    if dialect.name == "postgresql":
        names = ", ".join(dialect.identifier_preparer.format_table(table) for table in tables)
        db.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
    else:
        # Unit tests use an empty, isolated SQLite database.  Reverse dependency
        # order keeps this fallback deterministic without weakening production.
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
    db.commit()


def _summary(db: Session) -> dict[str, int | str]:
    return {
        "users": db.scalar(select(func.count(AppUser.id))) or 0,
        "datasources": db.scalar(select(func.count(DataSource.id))) or 0,
        "semantic_models": db.scalar(select(func.count(SemanticModel.id))) or 0,
        "verified_answers": db.scalar(select(func.count(VerifiedAnswer.id))) or 0,
        "dashboards": db.scalar(select(func.count(Dashboard.id))) or 0,
        "evaluation_runs": db.scalar(select(func.count(EvaluationRun.id))) or 0,
        "knowledge_documents": db.scalar(select(func.count(KnowledgeDocument.id))) or 0,
        "datasource_schemas": db.scalar(select(func.count(DataSourceSchema.id))) or 0,
        "datasource_tables": db.scalar(select(func.count(DataSourceTable.id))) or 0,
        "datasource_columns": db.scalar(select(func.count(DataSourceColumn.id))) or 0,
        "datasource_relationships": db.scalar(select(func.count(DataSourceRelation.id))) or 0,
        "business_data_reset": "NOT_NEEDED_READ_ONLY_FROZEN_SEED",
    }


def sync_showcase_catalogs(db: Session) -> None:
    """Refresh both read-only demo catalogs so SQL Guard has an allowlist."""

    datasources = list(db.scalars(select(DataSource).order_by(DataSource.name)))
    if len(datasources) != 2:
        raise RuntimeError(f"Expected two showcase datasources, found {len(datasources)}")
    for datasource in datasources:
        sync_datasource(db, datasource)


def reset_showcase_metadata(
    db: Session,
    *,
    admin_password: str,
    analyst_password: str,
    sync_catalogs: bool = True,
) -> dict[str, int | str]:
    """Replace local metadata and reseed the V1.3 showcase baseline."""

    _truncate_metadata(db)
    model = seed_demo_semantic_model(db)
    seed_v1_runtime(db, model.workspace_id)
    if sync_catalogs:
        sync_showcase_catalogs(db)
    set_showcase_credentials(
        db,
        admin_password=admin_password,
        analyst_password=analyst_password,
        revoke_sessions=True,
    )
    return _summary(db)


def main() -> None:
    parser = argparse.ArgumentParser(description="Maintain the local ChatBI job showcase")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--credentials-only", action="store_true")
    mode.add_argument("--confirm-local-showcase-reset", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    admin_password = settings.bootstrap_admin_password.get_secret_value()
    analyst_password = settings.bootstrap_analyst_password.get_secret_value()
    with SessionLocal() as db:
        if args.credentials_only:
            model = seed_demo_semantic_model(db)
            seed_v1_runtime(db, model.workspace_id)
            sync_showcase_catalogs(db)
            set_showcase_credentials(
                db,
                admin_password=admin_password,
                analyst_password=analyst_password,
                revoke_sessions=True,
            )
            print("SHOWCASE_CREDENTIALS=PASS")
            return

        summary = reset_showcase_metadata(
            db,
            admin_password=admin_password,
            analyst_password=analyst_password,
        )
        print("SHOWCASE_METADATA_RESET=PASS")
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
