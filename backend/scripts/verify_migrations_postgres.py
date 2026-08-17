from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings


SCHEMA = "chatbi_day2_migration_test"


def main() -> int:
    backend = Path(__file__).resolve().parents[1]
    root = backend.parent
    output = root / "docs" / "evidence" / "day2" / "migration-results.json"
    settings = get_settings()
    engine = create_engine(settings.database_url)
    results: list[dict] = []
    try:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
            connection.execute(text(f'CREATE SCHEMA "{SCHEMA}"'))
        isolated_url = make_url(settings.database_url).update_query_dict({"options": f"-csearch_path={SCHEMA}"})
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
        current_head = "20260817_0004" in results[-1]["stdout"]
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
        engine.dispose()
    evidence = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "database": "local PostgreSQL isolated temporary schema",
        "temporary_schema_removed": True,
        "single_head": one_head,
        "upgrade_base_upgrade_pass": passed and current_head,
        "commands": results,
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
