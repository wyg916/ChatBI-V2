from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.models import KnowledgeSource, Workspace
from scripts import migrate_legacy_rag_agent_snapshot as migration


SOURCE_COMMIT = migration.SOURCE_COMMIT


def test_snapshot_dry_run_accepts_only_allowlisted_tables(tmp_path: Path):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({
        "schema_version": "legacy-rag-agent-snapshot-v1",
        "source_commit": SOURCE_COMMIT,
        "tables": {"knowledge_source": []},
    }), encoding="utf-8")
    payload = migration.load_snapshot(snapshot)
    result = migration.plan(payload, "batch-test")
    assert result["old_database_connected"] is False
    assert result["target_tables_only"] is True
    assert result["rows"]["knowledge_source"] == 0


def test_snapshot_rejects_unlisted_tables_and_sensitive_fields(tmp_path: Path):
    forbidden = tmp_path / "forbidden.json"
    forbidden.write_text(json.dumps({
        "schema_version": migration.SNAPSHOT_SCHEMA_VERSION,
        "source_commit": SOURCE_COMMIT,
        "tables": {"app_user": []},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden tables"):
        migration.load_snapshot(forbidden)
    sensitive = tmp_path / "sensitive.json"
    sensitive.write_text(json.dumps({
        "schema_version": migration.SNAPSHOT_SCHEMA_VERSION,
        "source_commit": SOURCE_COMMIT,
        "tables": {"knowledge_source": [{"id": "1", "api_token": "do-not-copy"}]},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="sensitive field"):
        migration.load_snapshot(sensitive)


def test_snapshot_apply_is_idempotent_and_rollback_is_scoped(tmp_path: Path, db_session, monkeypatch):
    workspace_id = str(uuid4())
    source_id = str(uuid4())
    db_session.add(Workspace(id=workspace_id, name="Migration Test Workspace"))
    db_session.commit()
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({
        "schema_version": migration.SNAPSHOT_SCHEMA_VERSION,
        "source_commit": SOURCE_COMMIT,
        "tables": {
            "knowledge_source": [{
                "id": source_id,
                "workspace_id": workspace_id,
                "name": "Approved Sanitized Source",
                "source_type": "LEGACY_SNAPSHOT",
                "status": "ACTIVE",
                "source_commit": SOURCE_COMMIT,
                "created_at": "2026-08-17T00:00:00Z",
            }],
        },
    }), encoding="utf-8")
    payload = migration.load_snapshot(snapshot)
    monkeypatch.setattr(migration, "SessionLocal", sessionmaker(bind=db_session.get_bind()))

    first = migration.apply(payload, "batch-one")
    second = migration.apply(payload, "batch-one")
    assert first["inserted"]["knowledge_source"] == 1
    assert second["inserted"]["knowledge_source"] == 0
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(KnowledgeSource)) == 1

    removed = migration.rollback("batch-one")
    repeated = migration.rollback("batch-one")
    assert removed["deleted"]["knowledge_source"] == 1
    assert repeated["deleted"]["knowledge_source"] == 0
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(KnowledgeSource)) == 0
