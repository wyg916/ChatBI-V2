"""Import a sanitized legacy snapshot into ChatBI V2.

The script deliberately accepts no legacy database URL. Dry-run is the default
and apply/rollback always target the configured ChatBI metadata database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, delete

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.session import SessionLocal
from app.models import (
    Citation,
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
)


SOURCE_COMMIT = "b6be894a7153f7ce8d31dfc65da7222bd7af1b5f"
SNAPSHOT_SCHEMA_VERSION = "legacy-rag-agent-snapshot-v1"
MODELS = {
    "knowledge_source": KnowledgeSource,
    "knowledge_document": KnowledgeDocument,
    "knowledge_document_version": KnowledgeDocumentVersion,
    "knowledge_chunk": KnowledgeChunk,
    "knowledge_acl": KnowledgeAcl,
    "knowledge_ingestion_run": KnowledgeIngestionRun,
    "knowledge_retrieval_run": KnowledgeRetrievalRun,
    "citation": Citation,
    "orchestration_profile": OrchestrationProfile,
    "orchestration_run": OrchestrationRun,
    "orchestration_step": OrchestrationStep,
    "tool_binding": ToolBinding,
    "tool_call": ToolCall,
    "prompt_template": PromptTemplate,
    "prompt_version": PromptVersion,
}
APPLY_ORDER = tuple(MODELS)
ROLLBACK_ORDER = tuple(reversed(APPLY_ORDER))
SENSITIVE_KEY_PARTS = ("password", "secret", "token", "credential", "api_key", "connection_url")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--batch-id")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--rollback-batch")
    return parser.parse_args()


def _scan(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = key.lower()
            if any(part in lowered for part in SENSITIVE_KEY_PARTS):
                raise ValueError(f"sensitive field is forbidden: {path}.{key}")
            _scan(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan(item, f"{path}[{index}]")


def load_snapshot(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if payload.get("source_commit") != SOURCE_COMMIT:
        raise ValueError("snapshot source_commit is not the audited product commit")
    if payload.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("unsupported snapshot schema_version")
    unknown = set(payload) - {"schema_version", "source_commit", "tables"}
    if unknown:
        raise ValueError(f"unexpected snapshot keys: {sorted(unknown)}")
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("snapshot tables must be an object")
    unknown_tables = set(tables) - set(MODELS)
    if unknown_tables:
        raise ValueError(f"forbidden tables: {sorted(unknown_tables)}")
    for name, rows in tables.items():
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"{name} must be a list of objects")
    _scan(tables)
    payload["sha256"] = hashlib.sha256(raw).hexdigest()
    return payload


def plan(payload: dict[str, Any], batch_id: str | None) -> dict[str, Any]:
    tables = payload["tables"]
    return {
        "mode": "dry-run",
        "source_commit": payload["source_commit"],
        "snapshot_sha256": payload["sha256"],
        "batch_id": batch_id,
        "rows": {name: len(tables.get(name, [])) for name in APPLY_ORDER},
        "old_database_connected": False,
        "target_tables_only": True,
    }


def _normalize_row(model: type, source_row: dict[str, Any]) -> dict[str, Any]:
    row = dict(source_row)
    allowed = set(model.__table__.columns.keys())
    unknown = set(row) - allowed
    if unknown:
        raise ValueError(f"{model.__tablename__} contains unknown fields: {sorted(unknown)}")
    for column in model.__table__.columns:
        value = row.get(column.name)
        if value is not None and isinstance(column.type, DateTime) and isinstance(value, str):
            row[column.name] = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return row


def apply(payload: dict[str, Any], batch_id: str) -> dict[str, Any]:
    counts = {name: 0 for name in APPLY_ORDER}
    with SessionLocal.begin() as db:
        for name in APPLY_ORDER:
            model = MODELS[name]
            for source_row in payload["tables"].get(name, []):
                row = _normalize_row(model, source_row)
                row["migration_batch_id"] = batch_id
                if "id" not in row:
                    raise ValueError(f"{name} row is missing id")
                existing = db.get(model, row["id"])
                if existing is not None:
                    if existing.migration_batch_id != batch_id:
                        raise ValueError(f"{name}:{row['id']} already exists outside this batch")
                    continue
                db.add(model(**row))
                db.flush()
                counts[name] += 1
    return {"mode": "apply", "batch_id": batch_id, "inserted": counts, "old_database_connected": False}


def rollback(batch_id: str) -> dict[str, Any]:
    counts: dict[str, int] = {}
    with SessionLocal.begin() as db:
        for name in ROLLBACK_ORDER:
            model = MODELS[name]
            result = db.execute(delete(model).where(model.migration_batch_id == batch_id))
            counts[name] = int(result.rowcount or 0)
    return {"mode": "rollback", "batch_id": batch_id, "deleted": counts, "old_database_connected": False}


def main() -> None:
    args = _args()
    if args.rollback_batch:
        result = rollback(args.rollback_batch)
    else:
        if args.snapshot is None:
            raise SystemExit("--snapshot is required for dry-run/apply")
        payload = load_snapshot(args.snapshot)
        if args.apply:
            if not args.batch_id:
                raise SystemExit("--batch-id is required with --apply")
            result = apply(payload, args.batch_id)
        else:
            result = plan(payload, args.batch_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
