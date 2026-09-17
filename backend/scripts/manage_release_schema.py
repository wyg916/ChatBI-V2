from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import psycopg
from psycopg import sql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings


ROOT = BACKEND_ROOT.parent
SCHEMA_PATTERN = re.compile(r"^chatbi_release_[a-z0-9_]{8,64}$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "drop"))
    args = parser.parse_args()
    schema = os.environ.get("CHATBI_RELEASE_SCHEMA", "")
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise SystemExit("CHATBI_RELEASE_SCHEMA must use the guarded chatbi_release_ prefix")

    settings = Settings(_env_file=ROOT / ".env")
    password = settings.meta_password.get_secret_value()
    if not password:
        raise SystemExit("Local project metadata credential is not configured")

    with psycopg.connect(
        host="127.0.0.1",
        port=5432,
        dbname="chatbi_v2",
        user="chatbi_app",
        password=password,
        autocommit=True,
    ) as connection:
        with connection.cursor() as cursor:
            if args.action == "create":
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            else:
                cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
    print(f"RELEASE_SCHEMA_{args.action.upper()}=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
