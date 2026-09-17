from __future__ import annotations

import argparse
import os
import re

from sqlalchemy import create_engine, text


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare an isolated PostgreSQL schema for evaluation tests")
    parser.add_argument("--schema", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,62}", args.schema):
        raise ValueError("Schema must be a lowercase PostgreSQL identifier")
    url = os.environ.get("CHATBI_DATABASE_URL")
    if not url or not url.startswith("postgresql"):
        raise RuntimeError("CHATBI_DATABASE_URL must point to PostgreSQL")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{args.schema}" AUTHORIZATION chatbi_app'))
    engine.dispose()
    print(f"ISOLATED_SCHEMA={args.schema}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
