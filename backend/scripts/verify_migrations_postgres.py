from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings


def main() -> int:
    backend = Path(__file__).resolve().parents[1]
    root = backend.parent
    parser = argparse.ArgumentParser(description="Verify the current single Alembic head in an isolated PostgreSQL schema")
    parser.add_argument("--schema", default="chatbi_v21_migration_test")
    parser.add_argument("--output", type=Path, default=root / "docs" / "v2_1" / "day2" / "MIGRATION_EVIDENCE.json")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,62}", args.schema):
        raise ValueError("Migration test schema must be a lowercase PostgreSQL identifier")
    output = args.output
    settings = Settings(_env_file=root / ".env")
    database_url = make_url(settings.database_url)
    if database_url.password is None:
        database_url = database_url.set(password=settings.meta_password.get_secret_value())
    engine = create_engine(database_url)
    results: list[dict] = []
    one_head = False
    current_head = False
    expected_head = ""
    passed = False
    schema_created = False
    temporary_schema_removed = False
    try:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{args.schema}" CASCADE'))
            connection.execute(text(f'CREATE SCHEMA "{args.schema}"'))
        schema_created = True
        isolated_url = database_url.update_query_dict({"options": f"-csearch_path={args.schema}"})
        env = os.environ.copy()
        env["CHATBI_DATABASE_URL"] = isolated_url.render_as_string(hide_password=False)
        commands = [
            ("heads",),
            ("upgrade", "head"),
            ("downgrade", "base"),
            ("upgrade", "head"),
            ("current",),
        ]
        for command in commands:
            completed = subprocess.run(
                [sys.executable, "-m", "alembic", *command], cwd=backend, env=env,
                capture_output=True, text=True, check=False,
            )
            results.append({
                "command": "alembic " + " ".join(command), "returncode": completed.returncode,
                "stdout": completed.stdout.strip(), "stderr": completed.stderr.strip(),
            })
        passed = all(item["returncode"] == 0 for item in results)
        one_head = results[0]["stdout"].count("(head)") == 1
        expected_head = results[0]["stdout"].split(maxsplit=1)[0] if one_head else ""
        current_head = bool(expected_head and expected_head in results[-1]["stdout"])
    except Exception as exc:
        results.append({
            "command": "database setup",
            "returncode": 1,
            "error_type": type(exc).__name__,
        })
    finally:
        if schema_created:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{args.schema}" CASCADE'))
            temporary_schema_removed = True
        engine.dispose()
    evidence = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "tested_sha": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip(),
        "database": "local PostgreSQL isolated temporary schema",
        "migration_head": expected_head,
        "temporary_schema_removed": temporary_schema_removed,
        "single_head": one_head,
        "upgrade_base_upgrade_pass": passed and current_head,
        "commands": results,
        "failures": [item for item in results if item.get("returncode") != 0],
        "blockers": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "single_head": evidence["single_head"],
        "upgrade_base_upgrade_pass": evidence["upgrade_base_upgrade_pass"],
        "temporary_schema_removed": evidence["temporary_schema_removed"],
    }, ensure_ascii=False, indent=2))
    return 0 if evidence["single_head"] and evidence["upgrade_base_upgrade_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
