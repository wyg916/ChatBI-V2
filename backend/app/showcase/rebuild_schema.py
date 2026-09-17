"""Recreate only the local ChatBI metadata schema for a clean showcase.

This command is intentionally separate from the normal application startup,
requires an explicit confirmation flag, and refuses non-local/non-development
database targets.  The read-only ``demo_business`` schema is not touched.
"""

from __future__ import annotations

import argparse
import os
import re

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.models import DataSource
from app.services.spreadsheet_datasources import delete_managed_datasource


LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "host.docker.internal"})
LOCAL_SHOWCASE_DATABASE = re.compile(r"^chatbi_v2(?:_[a-z0-9_]+)?$")
LOCAL_SHOWCASE_SCHEMA = re.compile(r"^(?:public|chatbi_[a-z0-9_]+)$")


def validate_local_showcase_target(
    database_url: str,
    *,
    environment: str,
    expected_database: str = "chatbi_v2",
    expected_schema: str = "public",
) -> None:
    url = make_url(database_url)
    if environment != "development":
        raise RuntimeError("Showcase schema rebuild requires development environment")
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("Showcase schema rebuild requires PostgreSQL metadata")
    if not LOCAL_SHOWCASE_DATABASE.fullmatch(expected_database):
        raise RuntimeError("Showcase database name is outside the local ChatBI allowlist")
    if not LOCAL_SHOWCASE_SCHEMA.fullmatch(expected_schema):
        raise RuntimeError("Showcase schema name is outside the local ChatBI allowlist")
    if url.host not in LOCAL_HOSTS or url.database != expected_database:
        raise RuntimeError("Refusing to rebuild a non-local ChatBI metadata target")
    options = str(url.query.get("options", ""))
    if expected_schema != "public" and not re.search(
        rf"(?:^|\s)-c\s*search_path={re.escape(expected_schema)}(?:\s|$)",
        options,
    ):
        raise RuntimeError("Showcase database URL search_path does not match the isolated schema")


def rebuild_local_metadata_schema() -> None:
    settings = get_settings()
    expected_schema = os.getenv("CHATBI_DATABASE_SCHEMA", "").strip() or "public"
    validate_local_showcase_target(
        settings.database_url,
        environment=settings.environment,
        expected_database=os.getenv("CHATBI_SHOWCASE_DATABASE_NAME", "chatbi_v2"),
        expected_schema=expected_schema,
    )
    # Managed imports own schemas and login roles outside the metadata schema.
    # Reclaim them while their provenance rows and the locked chatbi_admin
    # helper functions still exist; dropping metadata first would orphan both.
    with SessionLocal() as db:
        managed_sources = list(db.scalars(select(DataSource).where(DataSource.type == "excel")))
        for datasource in managed_sources:
            delete_managed_datasource(db, datasource)
    with engine.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{expected_schema}" CASCADE'))
        connection.execute(text(f'CREATE SCHEMA "{expected_schema}" AUTHORIZATION CURRENT_USER'))
    print("SHOWCASE_METADATA_SCHEMA_REBUILD=PASS")
    print(f"METADATA_SCHEMA={expected_schema}")
    print("BUSINESS_SCHEMA_PRESERVED=YES")


def main() -> None:
    parser = argparse.ArgumentParser(description="Recreate the local ChatBI metadata schema")
    parser.add_argument("--confirm-local-showcase-schema-rebuild", action="store_true")
    args = parser.parse_args()
    if not args.confirm_local_showcase_schema_rebuild:
        parser.error("explicit local showcase schema rebuild confirmation is required")
    rebuild_local_metadata_schema()


if __name__ == "__main__":
    main()
