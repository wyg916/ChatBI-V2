from __future__ import annotations

import hashlib
import hmac
import json
import time
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import (
    AppUser,
    KnowledgeAcl,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIngestionRun,
    KnowledgeRetrievalRun,
    KnowledgeSource,
    OrchestrationProfile,
    OrchestrationRun,
    OrchestrationStep,
    PromptTemplate,
    PromptVersion,
    ToolBinding,
    ToolCall,
    Citation,
)
from app.rag_runtime.main import app as rag_app
from app.rag_runtime import legacy_selected_source
from app.rag_runtime.legacy_selected_source import SelectedSourceIntegrityError
from app.rag_runtime.service import RuntimeIdentity, retrieve
from app.services.runtime_seed import PROMPTS, V1_TOOLS, seed_v1_runtime
from app.services.seed import seed_demo_semantic_model


def _seed(db_session):
    model = seed_demo_semantic_model(db_session)
    seed_v1_runtime(db_session, model.workspace_id)
    admin = db_session.scalar(select(AppUser).where(AppUser.email == "admin@chatbi.local"))
    return model.workspace_id, admin


def test_runtime_seed_uses_all_15_governance_tables(db_session):
    workspace_id, _ = _seed(db_session)
    assert db_session.scalar(select(func.count()).select_from(KnowledgeSource)) == 1
    assert db_session.scalar(select(func.count()).select_from(KnowledgeDocument)) == 6
    assert db_session.scalar(select(func.count()).select_from(KnowledgeDocumentVersion)) == 6
    assert db_session.scalar(select(func.count()).select_from(KnowledgeChunk)) == 6
    assert db_session.scalar(select(func.count()).select_from(KnowledgeAcl)) == 6
    assert db_session.scalar(select(func.count()).select_from(KnowledgeIngestionRun)) == 1
    profile = db_session.scalar(
        select(OrchestrationProfile).where(OrchestrationProfile.workspace_id == workspace_id)
    )
    assert profile.allowed_tools == list(V1_TOOLS)
    assert (profile.max_steps, profile.max_tool_calls, profile.max_replan, profile.max_agent_depth) == (8, 12, 2, 2)
    assert db_session.scalar(select(func.count()).select_from(ToolBinding)) == 6
    assert db_session.scalar(select(func.count()).select_from(PromptTemplate)) == 6
    versions = list(db_session.scalars(select(PromptVersion)))
    assert len(versions) == len(PROMPTS) == 6
    assert all(item.source == "CHATBI_V1_REIMPLEMENTED" for item in versions)
    assert all(item.checksum_sha256 == hashlib.sha256(item.content.encode()).hexdigest() for item in versions)

    # These five execution tables are deliberately populated by live route execution,
    # not by migration or seed fabrication.
    assert all(
        db_session.scalar(select(func.count()).select_from(table)) == 0
        for table in (KnowledgeRetrievalRun, Citation, OrchestrationRun, OrchestrationStep, ToolCall)
    )


def test_selected_source_integrity_accepts_windows_crlf_and_rejects_tamper(tmp_path, monkeypatch):
    source_root = tmp_path / "selected"
    source_path = source_root / "app" / "knowledge" / "indexer.py"
    source_path.parent.mkdir(parents=True)
    canonical = b"def selected_source():\n    return 'locked'\n"
    source_path.write_bytes(canonical.replace(b"\n", b"\r\n"))
    lock_path = source_root / "LOCK.json"
    lock_path.write_text(json.dumps({
        "source_commit": legacy_selected_source.SOURCE_COMMIT,
        "files": [{
            "vendored_path": "app/knowledge/indexer.py",
            "sha256": hashlib.sha256(canonical).hexdigest(),
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(legacy_selected_source, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(legacy_selected_source, "LOCK_PATH", lock_path)

    assert legacy_selected_source._verify_integrity()["source_commit"] == legacy_selected_source.SOURCE_COMMIT
    source_path.write_bytes(source_path.read_bytes() + b"tampered")
    with pytest.raises(SelectedSourceIntegrityError, match="checksum mismatch"):
        legacy_selected_source._verify_integrity()


def test_acl_retrieval_is_workspace_bound_and_injection_free(db_session):
    workspace_id, admin = _seed(db_session)
    identity = RuntimeIdentity(workspace_id, admin.id, frozenset({"ADMIN"}))
    result = retrieve(db_session, query="收入营收口径", identity=identity, limit=3)
    assert result
    assert result[0].title == "收入口径与退款处理"
    assert all(item.document_id and item.document_version_id and item.chunk_id for item in result)

    db_session.query(KnowledgeAcl).delete()
    db_session.commit()
    assert retrieve(db_session, query="收入营收口径", identity=identity, limit=3) == ()


def test_live_bridge_verifies_hmac_and_identity(db_session, monkeypatch):
    workspace_id, admin = _seed(db_session)
    secret = "rag-runtime-test-secret"
    monkeypatch.setenv("CHATBI_RAG_SHARED_SECRET", secret)
    get_settings.cache_clear()
    monkeypatch.setattr("app.rag_runtime.main.SessionLocal", lambda: nullcontext(db_session))
    payload = {
        "query": "利润成本口径",
        "scenario_id": "chatbi-v1",
        "limit": 3,
        "trace_id": "TRACE-RAG-12345678",
        "chatbi_context": {
            "workspace_id": workspace_id,
            "user_id": admin.id,
            "roles": ["ADMIN"],
            "allowed_datasources": [],
            "allowed_semantic_models": [],
            "allowed_tools": ["RETRIEVE_KNOWLEDGE"],
            "trace_id": "TRACE-RAG-12345678",
            "timeout_ms": 1000,
            "max_steps": 8,
            "token_budget": 1000,
        },
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode(), timestamp.encode("ascii") + b"." + raw, hashlib.sha256
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-ChatBI-Workspace-Id": workspace_id,
        "X-ChatBI-User-Id": admin.id,
        "X-ChatBI-Roles": "ADMIN",
        "X-ChatBI-Trace-Id": "TRACE-RAG-12345678",
        "X-ChatBI-Timestamp": timestamp,
        "X-ChatBI-Signature": signature,
    }
    try:
        with TestClient(rag_app) as client:
            response = client.post("/api/v1/retrieve", content=raw, headers=headers)
            assert response.status_code == 200
            assert response.headers["X-ChatBI-Workspace-Id"] == workspace_id
            assert response.json()["answer_guard_status"] == "PASSED"
            assert response.json()["citations"][0]["title"] == "利润与成本口径"

            invalid = client.post(
                "/api/v1/retrieve",
                content=raw,
                headers={**headers, "X-ChatBI-Signature": "0" * 64},
            )
            assert invalid.status_code == 401
    finally:
        get_settings.cache_clear()
