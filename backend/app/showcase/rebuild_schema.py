"""Recreate only the local ChatBI metadata schema for a clean showcase.

This command is intentionally separate from the normal application startup,
requires an explicit confirmation flag, and refuses non-local/non-development
database targets.  The read-only ``demo_business`` schema is not touched.
"""

from __future__ import annotations

import argparse

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.db.session import engine


LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "host.docker.internal"})


def validate_local_showcase_target(database_url: str, *, environment: str) -> None:
    url = make_url(database_url)
    if environment != "development":
        raise RuntimeError("Showcase schema rebuild requires development environment")
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("Showcase schema rebuild requires PostgreSQL metadata")
    if url.host not in LOCAL_HOSTS or url.database != "chatbi_v2":
        raise RuntimeError("Refusing to rebuild a non-local ChatBI metadata target")


def rebuild_local_metadata_schema() -> None:
    settings = get_settings()
    validate_local_showcase_target(settings.database_url, environment=settings.environment)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public AUTHORIZATION CURRENT_USER"))
    print("SHOWCASE_METADATA_SCHEMA_REBUILD=PASS")
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
