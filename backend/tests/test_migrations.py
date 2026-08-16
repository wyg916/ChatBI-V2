import os
import subprocess
import sys


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
