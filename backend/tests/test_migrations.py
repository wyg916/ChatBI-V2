import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone


def run_alembic(database_url: str, *args: str):
    env = os.environ.copy()
    env["CHATBI_DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_single_head_and_upgrade_rollback_upgrade(tmp_path):
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'migration.db').as_posix()}"
    heads = run_alembic(database_url, "heads")
    assert heads.returncode == 0, heads.stderr
    assert heads.stdout.count("(head)") == 1
    for command in [("upgrade", "head"), ("downgrade", "base"), ("upgrade", "head")]:
        result = run_alembic(database_url, *command)
        assert result.returncode == 0, result.stderr


def test_spreadsheet_migration_upgrades_existing_0013_and_blocks_unsafe_downgrade(tmp_path):
    database_path = tmp_path / "spreadsheet-migration.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"

    previous = run_alembic(database_url, "upgrade", "20260828_0013")
    assert previous.returncode == 0, previous.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='datasource_import'"
        ).fetchone()[0] == 0

    upgraded = run_alembic(database_url, "upgrade", "20260829_0014")
    assert upgraded.returncode == 0, upgraded.stderr
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO workspace(id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("ws-migration", "Migration workspace", now, now),
        )
        connection.execute(
            """INSERT INTO datasource(
                id, workspace_id, name, type, host, port, database, username,
                password_encrypted, ssl, schema, status, last_sync_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "ds-migration", "ws-migration", "Managed sheet", "excel", "localhost", 5432,
                "chatbi_v2", "chatbi_excel_migration", "encrypted", 0, "excel_migration",
                "READY", now, now, now,
            ),
        )
        connection.execute(
            """INSERT INTO datasource_import(
                id, datasource_id, original_filename, file_sha256, media_type,
                file_size_bytes, storage_schema, row_count, column_count,
                sheet_metadata, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "import-migration", "ds-migration", "migration.xlsx", "a" * 64,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                128, "excel_migration", 1, 1, "[]", "READY", now,
            ),
        )
        connection.commit()

    blocked = run_alembic(database_url, "downgrade", "20260828_0013")
    assert blocked.returncode != 0
    assert "managed spreadsheet datasources exist" in blocked.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "20260829_0014"
        assert connection.execute("SELECT COUNT(*) FROM datasource_import").fetchone()[0] == 1
        connection.execute("DELETE FROM datasource_import")
        connection.execute("DELETE FROM datasource WHERE id = 'ds-migration'")
        connection.execute("DELETE FROM workspace WHERE id = 'ws-migration'")
        connection.commit()

    allowed = run_alembic(database_url, "downgrade", "20260828_0013")
    assert allowed.returncode == 0, allowed.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "20260828_0013"
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='datasource_import'"
        ).fetchone()[0] == 0


def test_workspace_history_migration_detaches_runs_and_blocks_lossy_downgrade(tmp_path):
    database_path = tmp_path / "workspace-history-migration.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"

    previous = run_alembic(database_url, "upgrade", "20260829_0014")
    assert previous.returncode == 0, previous.stderr
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO workspace(id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("ws-history", "History workspace", now, now),
        )
        connection.execute(
            """INSERT INTO app_user(
                id, workspace_id, email, display_name, role, status,
                last_active_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "user-history", "ws-history", "history@example.test", "History user",
                "ADMIN", "ACTIVE", None, now, now,
            ),
        )
        connection.execute(
            """INSERT INTO datasource(
                id, workspace_id, name, type, host, port, database, username,
                password_encrypted, ssl, schema, status, last_sync_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "ds-history", "ws-history", "Historical source", "postgresql", "localhost",
                5432, "chatbi_v2", "reader", "encrypted", 0, "public", "SYNCED",
                None, now, now,
            ),
        )
        connection.execute(
            """INSERT INTO sql_workspace_run(
                id, workspace_id, user_id, datasource_id, operation, sql_text,
                normalized_sql, status, guard_payload, execution_payload,
                oracle_payload, duration_ms, error_code, error_message,
                verified_answer_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "run-history", "ws-history", "user-history", "ds-history", "EXECUTE",
                "SELECT 1", "SELECT 1", "SUCCEEDED", "{}", "{}", "{}", 1,
                None, None, None, now,
            ),
        )
        connection.commit()

    upgraded = run_alembic(database_url, "upgrade", "20260829_0015")
    assert upgraded.returncode == 0, upgraded.stderr
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        datasource_column = next(
            row for row in connection.execute("PRAGMA table_info(sql_workspace_run)")
            if row[1] == "datasource_id"
        )
        assert datasource_column[3] == 0
        datasource_fk = next(
            row for row in connection.execute("PRAGMA foreign_key_list(sql_workspace_run)")
            if row[3] == "datasource_id"
        )
        assert datasource_fk[6] == "SET NULL"
        connection.execute("DELETE FROM datasource WHERE id = 'ds-history'")
        connection.commit()
        assert connection.execute(
            "SELECT datasource_id FROM sql_workspace_run WHERE id = 'run-history'"
        ).fetchone()[0] is None

    blocked = run_alembic(database_url, "downgrade", "20260829_0014")
    assert blocked.returncode != 0
    assert "detached SQL workspace history exists" in blocked.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "20260829_0015"
