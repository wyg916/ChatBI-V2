from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from scripts import run_v13_ibm_ci_bootstrap as bootstrap


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "v21-eval-golden-feedback.yml"


def test_ephemeral_environment_uses_local_postgres_and_distinct_credentials() -> None:
    values = bootstrap.build_ephemeral_environment(
        host="127.0.0.1",
        port=5432,
        database="chatbi_v2",
    )

    assert values["CHATBI_DATABASE_URL"].startswith(
        "postgresql+psycopg://chatbi_app:"
    )
    assert values["CHATBI_DATABASE_URL"].endswith("@127.0.0.1:5432/chatbi_v2")
    assert values["CHATBI_DEMO_POSTGRES_USERNAME"] == "chatbi_reader"
    assert values["CHATBI_META_PASSWORD"] != values["CHATBI_DEMO_POSTGRES_PASSWORD"]
    assert values["CHATBI_BOOTSTRAP_ADMIN_PASSWORD"]
    assert values["CHATBI_DATASOURCE_SECRET_KEY"]


def test_fixed_seed_replaces_wall_clock_date_without_changing_source(tmp_path: Path) -> None:
    source = tmp_path / "seed.sql"
    source.write_text("SELECT current_date, CURRENT_DATE - 364;\n", encoding="utf-8")

    rendered = bootstrap.frozen_seed_sql(source, date(2026, 8, 17))

    assert rendered == "SELECT DATE '2026-08-17', DATE '2026-08-17' - 364;\n"
    assert source.read_text(encoding="utf-8") == "SELECT current_date, CURRENT_DATE - 364;\n"


def test_github_environment_export_rejects_multiline_values(tmp_path: Path) -> None:
    destination = tmp_path / "github-env"
    with pytest.raises(ValueError, match="single-line"):
        bootstrap.export_github_environment({"CHATBI_TEST": "unsafe\nvalue"}, destination)
    assert destination.read_text(encoding="utf-8") == ""


def test_artifact_sanitizer_redacts_exact_and_pattern_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    raw_log = tmp_path / "backend.raw.log"
    monkeypatch.setenv("CHATBI_BOOTSTRAP_ADMIN_PASSWORD", "generated-ci-password")
    raw_log.write_text(
        "password=generated-ci-password\n"
        "Authorization: Bearer live-token-value\n"
        "postgresql+psycopg://chatbi_app:db-password@127.0.0.1:5432/chatbi_v2\n",
        encoding="utf-8",
    )
    (artifacts / "gate.json").write_text('{"status":"PASS"}\n', encoding="utf-8")

    receipt = bootstrap.sanitize_artifacts(artifacts, raw_log)

    sanitized = (artifacts / "backend.log").read_text(encoding="utf-8")
    assert receipt["status"] == "PASS"
    assert "generated-ci-password" not in sanitized
    assert "live-token-value" not in sanitized
    assert "db-password" not in sanitized
    assert sanitized.count("<REDACTED>") >= 3


def test_artifact_sanitizer_fails_closed_on_secret_in_non_log_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("CHATBI_DATASOURCE_SECRET_KEY", "generated-secret-key")
    (artifacts / "gate.json").write_text(
        '{"leak":"generated-secret-key"}\n', encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="CI_ARTIFACT_SECRET_SCAN_FAILED"):
        bootstrap.sanitize_artifacts(artifacts)


def test_api_preparation_authenticates_and_syncs_only_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, object]] = []
    monkeypatch.setenv("CHATBI_BOOTSTRAP_ADMIN_PASSWORD", "ephemeral-ci-password")

    def fake_api(opener, base_url, method, path, body=None):
        calls.append((method, path, body))
        if path == "/datasources":
            return [
                {"id": "pg-ci", "type": "postgresql"},
                {"id": "mysql-unused", "type": "mysql"},
            ]
        if path.endswith("/test") or path.endswith("/sync"):
            return {"success": True}
        return {"authenticated": True}

    monkeypatch.setattr(bootstrap, "_api_request", fake_api)

    result = bootstrap.prepare_live_api("http://127.0.0.1:18080/api/v1")

    assert result["status"] == "PASS"
    assert calls == [
        (
            "POST",
            "/auth/login",
            {"email": "admin@chatbi.local", "password": "ephemeral-ci-password"},
        ),
        ("GET", "/datasources", None),
        ("POST", "/datasources/pg-ci/test", None),
        ("POST", "/datasources/pg-ci/sync", None),
    ]


def test_workflow_is_self_contained_and_has_no_repository_secret_dependency() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'branches: ["codex/v1.3.0-data-semantic-upstream"]' in workflow
    assert "image: postgres:16.9-alpine@sha256:" in workflow
    assert "run_v13_ibm_ci_bootstrap.py" in workflow
    assert "python -m alembic upgrade head" in workflow
    assert "--prepare-api http://127.0.0.1:18080/api/v1" in workflow
    assert "http://127.0.0.1:18080/api/v1" in workflow
    assert "CHATBI_MODEL_PROVIDER: deterministic" in workflow
    assert "PGTZ: Asia/Shanghai" in workflow
    assert "IBM/text2sql-eval-toolkit" in workflow
    assert "60dd4515236adb335f2053b7c069397d7d88fe0a" in workflow
    assert "--no-install-project" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "--sanitize-artifacts" in workflow
    assert "steps.collect_evidence.outcome == 'success'" in workflow
    assert 'gate_status == "PASS" and release_status == "PASS"' in workflow
    assert '"ENFORCED_FAIL" if gate_path.exists() else "NOT_PRODUCED"' in workflow
    assert "inputs.api_base" not in workflow
    assert "secrets." not in workflow
    assert not re.search(r"Bearer\s+[A-Za-z0-9._-]+", workflow)
