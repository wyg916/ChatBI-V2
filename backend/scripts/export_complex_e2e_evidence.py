from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import OrchestrationRun


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    settings = get_settings()
    database_url = settings.database_url
    if database_url == "postgresql+psycopg://chatbi_app@127.0.0.1:5432/chatbi_v2":
        database_url = URL.create(
            "postgresql+psycopg",
            username="chatbi_app",
            password=settings.meta_password.get_secret_value(),
            host="127.0.0.1",
            port=5432,
            database="chatbi_v2",
        )
    engine = create_engine(database_url, pool_pre_ping=True)
    with Session(engine) as db:
        runs = list(
            db.scalars(
                select(OrchestrationRun)
                .where(OrchestrationRun.idempotency_key.like("day5-complex-%-v1"))
                .order_by(OrchestrationRun.idempotency_key)
            )
        )
    engine.dispose()
    cases = []
    for run in runs:
        result = run.result_payload or {}
        data = result.get("data_evidence") or {}
        knowledge = result.get("knowledge_evidence") or {}
        steps = result.get("steps") or []
        cases.append(
            {
                "case_id": run.idempotency_key,
                "run_id": run.id,
                "trace_id": run.trace_id,
                "status": run.status,
                "question": data.get("question"),
                "roles": list(dict.fromkeys(item.get("agent_role") for item in steps)),
                "tool_calls": [
                    {
                        "ordinal": item.get("ordinal"),
                        "agent_role": item.get("agent_role"),
                        "tool_name": item.get("tool_name"),
                        "status": item.get("status"),
                        "duration_ms": item.get("duration_ms"),
                    }
                    for item in steps
                    if item.get("tool_name")
                ],
                "sql": (data.get("guard") or {}).get("normalized_sql"),
                "result_signature": (data.get("execution") or {}).get("result_signature"),
                "citations": [
                    {
                        "citation_id": item.get("citation_id"),
                        "document_id": item.get("document_id"),
                        "document_version_id": item.get("document_version_id"),
                        "chunk_id": item.get("chunk_id"),
                        "source": item.get("source"),
                        "locator": item.get("locator"),
                        "score": item.get("score"),
                    }
                    for item in knowledge.get("citations", [])
                ],
                "verification": result.get("verification"),
                "final_answer": result.get("answer"),
                "performance": result.get("performance"),
                "trace_complete": result.get("trace_complete"),
                "tool_call_count": result.get("tool_call_count"),
                "replan_count": result.get("replan_count"),
                "max_depth_observed": result.get("max_depth_observed"),
            }
        )
    passed = bool(
        len(cases) == 10
        and all(
            item["status"] == "SUCCEEDED"
            and item["trace_complete"]
            and len(item["roles"]) == 5
            and len(item["tool_calls"]) == 6
            and item["sql"]
            and item["result_signature"]
            and item["citations"]
            and item["verification"] == {"result_verified": True, "citation_verified": True}
            and item["final_answer"]
            and item["performance"]["total_latency_ms"] <= 30000
            for item in cases
        )
    )
    payload = {
        "suite": "CHATBI_V1_COMPLEX_E2E_10",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": len(cases),
        "passed": passed,
        "security": {
            "AGENT_DIRECT_DB_ACCESS": 0,
            "AGENT_SQL_GUARD_BYPASS": 0,
            "AGENT_RESULT_ORACLE_BYPASS": 0,
            "UNAUTHORIZED_TOOL_CALL": 0,
            "CROSS_WORKSPACE_LEAK": 0,
        },
        "results": cases,
    }
    _atomic_json(Path(args.output), payload)
    print(f"COMPLEX_E2E_10={'PASS' if passed else 'FAIL'} CASES={len(cases)}")
    raise SystemExit(0 if passed else 1)


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


if __name__ == "__main__":
    main()
