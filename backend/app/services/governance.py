from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as model_module
from app.core.config import get_settings
from app.model_gateway.configuration import PROVIDER_DEFINITIONS, configured_providers, load_control_config
from app.models import (
    ChatMessage,
    EvaluationRun,
    KnowledgeRetrievalRun,
    OrchestrationRun,
    OrchestrationStep,
    QueryAuditEvent,
    QueryRun,
    ToolCall,
)


_REPO_ROOT = Path(__file__).resolve().parents[3]
_NAMED_PROVIDERS = {"mimo", "deepseek", "kimi", "openai-compatible"}
_MODEL_INVOCATION_FIELDS = (
    "id", "workspace_id", "user_id", "trace_id", "request_id", "conversation_id", "route", "capability",
    "provider", "model", "status", "input_tokens", "cached_input_tokens",
    "output_tokens", "cost_cny", "latency_ms", "cache_hit", "fallback_count", "retry_count",
    "premium_escalation", "error_code", "circuit_state", "pricing_version", "created_at",
)
_TRACE_METADATA_KEYS = {
    "statement_type", "issue_codes", "row_count", "truncated", "duration_ms",
    "estimated_cost", "maximum_cost", "reason", "confidence", "mismatch_count",
    "provider", "repair_count", "link_count", "estimated_tokens", "citation_count",
    "agent_role", "grounded", "verified", "shadow",
}
_EVIDENCE_PATHS = (
    "docs/v2_1/day2/IBM_EVAL_EVIDENCE.json",
    "docs/v2_1/day2/D_AGENT_PRODUCT_EVIDENCE.json",
    "docs/v2_1/day2/D_FILE_PRODUCT_EVIDENCE.json",
    "docs/v2_1/day2/D_SANDBOX_SECURITY_EVIDENCE.json",
    "docs/evidence/day5/rag-golden-120.json",
    "docs/evidence/day5/complex-e2e-10.json",
    "docs/evidence/day5/rag-multiagent-final-acceptance.json",
)


def model_invocation_contract_fields() -> tuple[str, ...]:
    """Expose the exact shared-model contract without defining a second model."""
    return _MODEL_INVOCATION_FIELDS


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _in_window(value: datetime, from_at: datetime | None, to_at: datetime | None) -> bool:
    current = _as_datetime(value)
    lower = _as_datetime(from_at) if from_at else None
    upper = _as_datetime(to_at) if to_at else None
    return (lower is None or current >= lower) and (upper is None or current <= upper)


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _cost_entry_from_model(row: Any) -> dict[str, Any]:
    missing = [field for field in _MODEL_INVOCATION_FIELDS if not hasattr(row, field)]
    if missing:
        raise RuntimeError(f"ModelInvocation contract mismatch: {', '.join(missing)}")
    return {
        "id": str(row.id),
        "workspace_id": row.workspace_id,
        "user_id": row.user_id,
        "trace_id": row.trace_id,
        "request_id": row.request_id,
        "conversation_id": row.conversation_id,
        "route": row.route,
        "capability": row.capability,
        "provider": row.provider,
        "model": row.model,
        "status": row.status,
        "input_tokens": _int(row.input_tokens),
        "cached_input_tokens": _int(row.cached_input_tokens),
        "output_tokens": _int(row.output_tokens),
        "cost_cny": _float(row.cost_cny),
        "latency_ms": _int(row.latency_ms),
        "cache_hit": bool(row.cache_hit),
        "fallback_count": _int(row.fallback_count),
        "premium_escalation": bool(row.premium_escalation),
        "retry_count": _int(row.retry_count),
        "error_code": row.error_code,
        "circuit_state": getattr(row, "circuit_state", None),
        "pricing_version": getattr(row, "pricing_version", None),
        "source": "MODEL_INVOCATION_LEDGER",
        "created_at": row.created_at,
    }


def _trace_cost_entry(
    *, row_id: str, workspace_id: str, user_id: str | None, trace_id: str,
    request_id: str | None, route: str | None, trace: dict[str, Any], created_at: datetime,
    capability: str | None, source: str, conversation_id: str | None = None,
) -> dict[str, Any] | None:
    provider = str(trace.get("resolved_provider") or "").lower()
    if provider not in _NAMED_PROVIDERS:
        return None
    usage = trace.get("usage") if isinstance(trace.get("usage"), dict) else {}
    model = str(trace.get("resolved_model") or provider)
    fallback_count = _int(trace.get("fallback_count"))
    requested_alias = str(trace.get("requested_alias") or "auto").lower()
    return {
        "id": row_id,
        "workspace_id": workspace_id,
        "user_id": user_id,
        "trace_id": trace_id,
        "request_id": request_id,
        "conversation_id": conversation_id,
        "route": route,
        "capability": capability,
        "provider": provider,
        "model": model,
        "status": "SUCCEEDED",
        "input_tokens": _int(usage.get("input_tokens")),
        "cached_input_tokens": _int(usage.get("cached_input_tokens")),
        "output_tokens": _int(usage.get("output_tokens")),
        "cost_cny": _float(trace.get("cost_cny")),
        "latency_ms": _int(trace.get("latency_ms")),
        "cache_hit": _int(usage.get("cached_input_tokens")) > 0,
        "fallback_count": fallback_count,
        "premium_escalation": provider == "kimi" and requested_alias not in {"kimi", "kimi.premium", "kimi.vision"},
        "retry_count": _int(trace.get("retry_count")),
        "error_code": None,
        "circuit_state": None,
        "pricing_version": trace.get("pricing_version"),
        "source": source,
        "created_at": created_at,
    }


def _fallback_cost_entries(db: Session, workspace_id: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for run in db.scalars(select(QueryRun).where(QueryRun.workspace_id == workspace_id)):
        context = (run.context_payload or {}).get("request_context") or {}
        trace = (run.plan_payload or {}).get("model_trace") or {}
        item = _trace_cost_entry(
            row_id=f"query:{run.id}", workspace_id=run.workspace_id,
            user_id=context.get("user_id"), trace_id=str(context.get("trace_id") or f"TRACE-{run.id}"),
            request_id=context.get("request_id") or run.id, route="DATA_QUERY", trace=trace,
            created_at=run.created_at, capability="nl2sql", source="QUERY_RUN_MODEL_TRACE",
            conversation_id=context.get("conversation_id"),
        )
        if item:
            entries.append(item)
    for message in db.scalars(select(ChatMessage).where(
        ChatMessage.workspace_id == workspace_id,
        ChatMessage.role == "assistant",
    )):
        payload = message.trace_payload or {}
        item = _trace_cost_entry(
            row_id=f"chat:{message.id}", workspace_id=message.workspace_id,
            user_id=message.user_id, trace_id=str(payload.get("trace_id") or payload.get("run_id") or message.id),
            request_id=payload.get("request_id"), route=message.route, trace=payload.get("model_call") or {},
            created_at=message.created_at, capability="chat", source="CHAT_MESSAGE_MODEL_TRACE",
            conversation_id=message.conversation_id,
        )
        if item:
            entries.append(item)
    # Prefer the more specific QueryRun record when the assistant trace repeats
    # the same provider response. This is a fallback only, never a claim of full
    # invocation coverage.
    deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in entries:
        key = (
            item["trace_id"], item["provider"], item["model"], item["input_tokens"],
            item["output_tokens"], round(item["cost_cny"], 8),
        )
        previous = deduped.get(key)
        if previous is None or item["source"] == "QUERY_RUN_MODEL_TRACE":
            deduped[key] = item
    return list(deduped.values())


def cost_ledger_entries(
    db: Session,
    *,
    workspace_id: str,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
    user_id: str | None = None,
    conversation_id: str | None = None,
    route: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    invocation_model = getattr(model_module, "ModelInvocation", None)
    if invocation_model is not None:
        statement = select(invocation_model).where(invocation_model.workspace_id == workspace_id)
        if from_at is not None:
            statement = statement.where(invocation_model.created_at >= from_at)
        if to_at is not None:
            statement = statement.where(invocation_model.created_at <= to_at)
        rows = list(db.scalars(statement.order_by(invocation_model.created_at.desc())))
        entries = [_cost_entry_from_model(row) for row in rows]
        coverage = {"source": "MODEL_INVOCATION_LEDGER", "complete": True, "warnings": []}
    else:
        entries = _fallback_cost_entries(db, workspace_id)
        coverage = {
            "source": "PERSISTED_MODEL_TRACE_FALLBACK",
            "complete": False,
            "warnings": [
                "ModelInvocation shared migration is not installed; failed and overwritten model calls are not reconstructable.",
                "Numbers below come only from persisted ONE_TRACE model receipts and must not be used as a billing ledger.",
            ],
        }
    entries = [
        item for item in entries
        if _in_window(item["created_at"], from_at, to_at)
        and (user_id is None or item["user_id"] == user_id)
        and (conversation_id is None or item["conversation_id"] == conversation_id)
        and (route is None or item["route"] == route)
        and (provider is None or item["provider"] == provider)
        and (model is None or item["model"] == model)
    ]
    entries.sort(key=lambda item: _as_datetime(item["created_at"]), reverse=True)
    return entries, coverage


def _breakdown(entries: Iterable[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in entries:
        groups[str(item.get(key) or "UNKNOWN")].append(item)
    result = []
    for name, rows in groups.items():
        result.append({
            "key": name,
            "requests": len(rows),
            "input_tokens": sum(item["input_tokens"] for item in rows),
            "output_tokens": sum(item["output_tokens"] for item in rows),
            "cost_cny": round(sum(item["cost_cny"] for item in rows), 8),
            "cache_hits": sum(bool(item["cache_hit"]) for item in rows),
            "fallbacks": sum(item["fallback_count"] > 0 for item in rows),
            "premium_escalations": sum(bool(item["premium_escalation"]) for item in rows),
            "errors": sum(item["status"] != "SUCCEEDED" for item in rows),
            "average_latency_ms": round(sum(item["latency_ms"] for item in rows) / len(rows), 2),
        })
    return sorted(result, key=lambda item: (-item["requests"], item["key"]))


def cost_dashboard(db: Session, **filters: Any) -> dict[str, Any]:
    entries, coverage = cost_ledger_entries(db, **filters)
    requests = len(entries)
    return {
        "coverage": coverage,
        "currency": "CNY",
        "requests": requests,
        "input_tokens": sum(item["input_tokens"] for item in entries),
        "output_tokens": sum(item["output_tokens"] for item in entries),
        "cost_cny": round(sum(item["cost_cny"] for item in entries), 8),
        "cache_hits": sum(bool(item["cache_hit"]) for item in entries),
        "fallbacks": sum(item["fallback_count"] > 0 for item in entries),
        "premium_escalations": sum(bool(item["premium_escalation"]) for item in entries),
        "errors": sum(item["status"] != "SUCCEEDED" for item in entries),
        "average_latency_ms": round(sum(item["latency_ms"] for item in entries) / requests, 2) if requests else 0.0,
        "by_workspace": _breakdown(entries, "workspace_id"),
        "by_user": _breakdown(entries, "user_id"),
        "by_conversation": _breakdown(entries, "conversation_id"),
        "by_provider": _breakdown(entries, "provider"),
        "by_model": _breakdown(entries, "model"),
        "by_route": _breakdown(entries, "route"),
        "entries": entries[:500],
    }


def _safe_metadata(details: dict[str, Any] | None) -> dict[str, Any]:
    return {key: value for key, value in (details or {}).items() if key in _TRACE_METADATA_KEYS}


def _trace_record(records: dict[str, dict[str, Any]], trace_id: str, workspace_id: str, created_at: datetime) -> dict[str, Any]:
    return records.setdefault(trace_id, {
        "trace_id": trace_id,
        "workspace_id": workspace_id,
        "user_id": None,
        "route": None,
        "status": "UNKNOWN",
        "started_at": _as_datetime(created_at),
        "duration_ms": 0,
        "provider": None,
        "model": None,
        "tools": set(),
        "has_sql": False,
        "has_rag": False,
        "has_agent": False,
        "has_file": False,
        "has_vision": False,
        "artifact_count": 0,
        "error_code": None,
        "stages": [],
        "stage_level": False,
    })


def _append_stage(record: dict[str, Any], **stage: Any) -> None:
    record["stages"].append(stage)
    if stage["timing_source"] in {"QUERY_AUDIT_EVENT", "ORCHESTRATION_STEP", "RAG_RUN", "CHAT_STAGE"}:
        record["stage_level"] = True


def _artifact_count(payload: dict[str, Any]) -> int:
    file_analysis = payload.get("file_analysis") or {}
    artifacts = file_analysis.get("artifacts") if isinstance(file_analysis, dict) else []
    parts = payload.get("message_parts") or []
    return len(artifacts or []) + sum(
        str(item.get("kind") or item.get("type") or "").lower() == "artifact"
        for item in parts if isinstance(item, dict)
    )


def _collect_trace_records(
    db: Session,
    workspace_id: str,
    *,
    candidate_limit: int | None = None,
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    query_runs_query = select(QueryRun).where(QueryRun.workspace_id == workspace_id)
    if candidate_limit is not None:
        query_runs_query = query_runs_query.order_by(QueryRun.created_at.desc()).limit(candidate_limit)
    query_runs = list(db.scalars(query_runs_query))
    query_by_id = {run.id: run for run in query_runs}
    events = list(db.scalars(
        select(QueryAuditEvent).where(QueryAuditEvent.query_run_id.in_(list(query_by_id))).order_by(QueryAuditEvent.created_at)
    )) if query_by_id else []
    events_by_run: dict[str, list[QueryAuditEvent]] = defaultdict(list)
    for event in events:
        events_by_run[event.query_run_id].append(event)
    for run in query_runs:
        context = (run.context_payload or {}).get("request_context") or {}
        trace_id = str(context.get("trace_id") or f"TRACE-{run.id}")
        record = _trace_record(records, trace_id, run.workspace_id, run.created_at)
        record.update({
            "user_id": context.get("user_id") or record["user_id"],
            "route": record["route"] or "DATA_QUERY",
            "status": run.status,
            "duration_ms": max(record["duration_ms"], _int(run.duration_ms)),
            "provider": run.provider or record["provider"],
            "has_sql": bool(run.normalized_sql or run.generated_sql),
            "error_code": run.error_code or record["error_code"],
        })
        model_trace = (run.plan_payload or {}).get("model_trace") or {}
        if model_trace:
            record["provider"] = model_trace.get("resolved_provider") or record["provider"]
            record["model"] = model_trace.get("resolved_model") or record["model"]
        for event in events_by_run.get(run.id, []):
            details = event.details or {}
            _append_stage(
                record,
                stage=event.event_type,
                status=event.status,
                started_at=_as_datetime(event.created_at),
                duration_ms=_int(details.get("duration_ms")),
                timing_source="QUERY_AUDIT_EVENT",
                provider=details.get("provider") if event.event_type == "SQL_PLAN_GENERATED" else None,
                model=None,
                tool=None,
                sql=(run.normalized_sql or run.generated_sql) if event.event_type in {"SQL_GUARD", "QUERY_EXECUTED"} else None,
                error_code=run.error_code if event.status in {"FAIL", "REJECTED"} else None,
                metadata=_safe_metadata(details),
            )

    messages_query = select(ChatMessage).where(
        ChatMessage.workspace_id == workspace_id,
        ChatMessage.role == "assistant",
    )
    if candidate_limit is not None:
        messages_query = messages_query.order_by(ChatMessage.created_at.desc()).limit(candidate_limit)
    messages = list(db.scalars(messages_query))
    for message in messages:
        payload = message.trace_payload or {}
        trace_id = str(payload.get("trace_id") or payload.get("run_id") or message.id)
        record = _trace_record(records, trace_id, message.workspace_id, message.created_at)
        model_call = payload.get("model_call") if isinstance(payload.get("model_call"), dict) else {}
        route = message.route or payload.get("route")
        response_payload = message.response_payload or {}
        record.update({
            "user_id": message.user_id or record["user_id"],
            "route": route or record["route"],
            "status": message.status or record["status"],
            "duration_ms": max(record["duration_ms"], _int(payload.get("elapsed_ms"))),
            "provider": payload.get("model_provider") or model_call.get("resolved_provider") or record["provider"],
            "model": payload.get("model_name") or model_call.get("resolved_model") or record["model"],
            "has_file": record["has_file"] or route == "FILE_QUERY" or bool(response_payload.get("file_analysis")),
            "has_vision": record["has_vision"] or route in {"VISION_QUERY", "MULTIMODAL_QUERY"} or bool(response_payload.get("visual_evidence")),
            "artifact_count": record["artifact_count"] + _artifact_count(response_payload),
            "error_code": message.error_code or record["error_code"],
        })
        existing_names = {item["stage"] for item in record["stages"]}
        for span in payload.get("operation_spans") or []:
            name = str(span.get("name") or "operation")
            if name in existing_names:
                continue
            _append_stage(
                record, stage=name, status=str(span.get("status") or "COMPLETED"),
                started_at=_as_datetime(span.get("started_at") or message.created_at),
                duration_ms=_int(span.get("duration_ms")),
                timing_source=str(span.get("timing_source") or "COMPLETION_RECEIPT"), provider=None, model=None, tool=None,
                sql=None, error_code=None, metadata={},
            )
        for step in payload.get("tool_calls") or []:
            if not isinstance(step, dict):
                continue
            tool = step.get("tool_name") or step.get("tool")
            if tool:
                record["tools"].add(str(tool))
                record["has_agent"] = True
        if model_call and "model.invoke" not in existing_names:
            _append_stage(
                record, stage="model.invoke", status="COMPLETED", started_at=_as_datetime(message.created_at),
                duration_ms=_int(model_call.get("latency_ms")), timing_source="MODEL_COMPLETION_RECEIPT",
                provider=model_call.get("resolved_provider"), model=model_call.get("resolved_model"),
                tool=None, sql=None, error_code=None,
                metadata={
                    "input_tokens": _int((model_call.get("usage") or {}).get("input_tokens")),
                    "output_tokens": _int((model_call.get("usage") or {}).get("output_tokens")),
                    "cost_cny": _float(model_call.get("cost_cny")),
                    "fallback_count": _int(model_call.get("fallback_count")),
                },
            )

    orchestration_query = select(OrchestrationRun).where(OrchestrationRun.workspace_id == workspace_id)
    if candidate_limit is not None:
        orchestration_query = orchestration_query.order_by(OrchestrationRun.created_at.desc()).limit(candidate_limit)
    orchestration_runs = list(db.scalars(orchestration_query))
    orchestration_ids = [run.id for run in orchestration_runs]
    steps = list(db.scalars(select(OrchestrationStep).where(
        OrchestrationStep.orchestration_run_id.in_(orchestration_ids)
    ).order_by(OrchestrationStep.ordinal))) if orchestration_ids else []
    calls = list(db.scalars(select(ToolCall).where(
        ToolCall.orchestration_run_id.in_(orchestration_ids)
    ))) if orchestration_ids else []
    steps_by_run: dict[str, list[OrchestrationStep]] = defaultdict(list)
    for step in steps:
        steps_by_run[step.orchestration_run_id].append(step)
    calls_by_run: dict[str, list[ToolCall]] = defaultdict(list)
    for call in calls:
        calls_by_run[call.orchestration_run_id].append(call)
    for run in orchestration_runs:
        record = _trace_record(records, run.trace_id, run.workspace_id, run.created_at)
        record.update({
            "user_id": run.user_id or record["user_id"], "route": run.route,
            "status": run.status, "duration_ms": max(record["duration_ms"], _int(run.total_latency_ms)),
            "has_agent": True, "error_code": run.error_code or record["error_code"],
        })
        for step in steps_by_run.get(run.id, []):
            details = step.details or {}
            if step.tool_name:
                record["tools"].add(step.tool_name)
            _append_stage(
                record, stage=step.code, status=step.status, started_at=_as_datetime(run.created_at),
                duration_ms=_int(step.duration_ms), timing_source="ORCHESTRATION_STEP",
                provider=None, model=None, tool=step.tool_name, sql=None,
                error_code=details.get("error_code"), metadata=_safe_metadata(details),
            )
        for call in calls_by_run.get(run.id, []):
            record["tools"].add(call.tool_name)

    knowledge_query = select(KnowledgeRetrievalRun).where(KnowledgeRetrievalRun.workspace_id == workspace_id)
    if candidate_limit is not None:
        knowledge_query = knowledge_query.order_by(KnowledgeRetrievalRun.created_at.desc()).limit(candidate_limit)
    for run in db.scalars(knowledge_query):
        record = _trace_record(records, run.trace_id, run.workspace_id, run.created_at)
        record["user_id"] = run.user_id or record["user_id"]
        record["has_rag"] = True
        if record["status"] == "UNKNOWN":
            record["status"] = run.status
        _append_stage(
            record, stage="rag.retrieve", status=run.status, started_at=_as_datetime(run.created_at),
            duration_ms=0, timing_source="RAG_RUN", provider=None, model=None, tool="RETRIEVE_KNOWLEDGE",
            sql=None, error_code=None,
            metadata={"citation_count": run.citation_count, **_safe_metadata(run.details or {})},
        )
    return records


def _finalize_trace(record: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    stages = sorted(record["stages"], key=lambda item: _as_datetime(item["started_at"]))
    for index, stage in enumerate(stages[:-1]):
        if stage["duration_ms"] == 0:
            delta = round((_as_datetime(stages[index + 1]["started_at"]) - _as_datetime(stage["started_at"])).total_seconds() * 1000)
            if delta > 0:
                stage["duration_ms"] = delta
                stage["timing_source"] = f"{stage['timing_source']}_DELTA"
    if stages:
        record["started_at"] = min(_as_datetime(item["started_at"]) for item in stages)
        elapsed = round((_as_datetime(stages[-1]["started_at"]) - record["started_at"]).total_seconds() * 1000)
        record["duration_ms"] = max(record["duration_ms"], elapsed + stages[-1]["duration_ms"])
    summary = {
        key: value for key, value in record.items()
        if key not in {"stages", "stage_level"}
    }
    summary["tools"] = sorted(record["tools"])
    summary["stage_count"] = len(stages)
    return summary, stages


def trace_dashboard(
    db: Session,
    *,
    workspace_id: str,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
    user_id: str | None = None,
    route: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    # The unfiltered dashboard needs only the newest ``limit`` traces.  A trace
    # outside the newest N rows of every persisted source cannot enter the
    # newest N union, so bounding each source preserves the exact result while
    # avoiding full-history ORM hydration after load tests.  Filtered views and
    # trace detail retain the complete-history path.
    unfiltered = all(value is None for value in (from_at, to_at, user_id, route, status))
    records = _collect_trace_records(
        db,
        workspace_id,
        candidate_limit=limit if unfiltered else None,
    )
    items: list[dict[str, Any]] = []
    stage_level = False
    for record in records.values():
        summary, _ = _finalize_trace(record)
        if not _in_window(summary["started_at"], from_at, to_at):
            continue
        if user_id is not None and summary["user_id"] != user_id:
            continue
        if route is not None and summary["route"] != route:
            continue
        if status is not None and summary["status"] != status:
            continue
        stage_level = stage_level or record["stage_level"]
        items.append(summary)
    items.sort(key=lambda item: _as_datetime(item["started_at"]), reverse=True)
    return {
        "coverage": {
            "source": "ONE_TRACE_PERSISTED_STORES",
            "complete": True,
            "warnings": [
                "Completion-only spans retain zero duration when no persisted stage timestamp exists.",
                "Only allowlisted execution metadata is exposed; prompts, reasoning and raw tool payloads are omitted.",
            ],
        },
        "trace_granularity": "STAGE_LEVEL" if stage_level else "COMPLETION_RECEIPT_LEVEL",
        "items": items[:limit],
    }


def trace_detail(db: Session, *, workspace_id: str, trace_id: str) -> dict[str, Any]:
    records = _collect_trace_records(db, workspace_id)
    record = records.get(trace_id)
    if record is None:
        raise LookupError("Trace not found")
    summary, stages = _finalize_trace(record)
    return {
        "coverage": {
            "source": "ONE_TRACE_PERSISTED_STORES", "complete": True,
            "warnings": ["Sensitive content is removed by an output allowlist."],
        },
        "trace": summary,
        "stages": stages,
    }


def model_dashboard(
    db: Session,
    *,
    workspace_id: str,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
) -> dict[str, Any]:
    entries, coverage = cost_ledger_entries(
        db, workspace_id=workspace_id, from_at=from_at, to_at=to_at,
    )
    settings = get_settings()
    configured = configured_providers(settings)
    policy = load_control_config("model_policy.yaml")
    health = load_control_config("provider_health.yaml")
    pricing = load_control_config("model_pricing.yaml")
    providers = []
    for definition in PROVIDER_DEFINITIONS:
        if definition.provider_id not in {"mimo", "deepseek", "kimi"}:
            continue
        rows = [item for item in entries if item["provider"] == definition.provider_id]
        successful = [item for item in rows if item["status"] == "SUCCEEDED"]
        errors = len(rows) - len(successful)
        latest = max(rows, key=lambda item: _as_datetime(item["created_at"])) if rows else None
        if definition.provider_id not in configured:
            observed_health = "UNCONFIGURED"
        elif latest is None:
            observed_health = "NO_CALLS"
        elif latest["status"] == "SUCCEEDED" and errors == 0:
            observed_health = "HEALTHY"
        else:
            observed_health = "DEGRADED"
        providers.append({
            "provider": definition.provider_id,
            "display_name": definition.display_name,
            "model": str(getattr(settings, definition.model_name_field) or "") or None,
            "configured": definition.provider_id in configured,
            "health": observed_health,
            "circuit_state": str((latest or {}).get("circuit_state") or "UNKNOWN"),
            "circuit_failure_threshold": int(health["circuit_failure_threshold"]),
            "circuit_cooldown_seconds": float(health["circuit_cooldown_seconds"]),
            "requests": len(rows),
            "errors": errors,
            "average_latency_ms": round(sum(item["latency_ms"] for item in rows) / len(rows), 2) if rows else 0.0,
            "cost_cny": round(sum(item["cost_cny"] for item in rows), 8),
            "fallback_rate": round(sum(item["fallback_count"] > 0 for item in rows) / len(rows), 4) if rows else 0.0,
            "premium_ratio": round(sum(bool(item["premium_escalation"]) for item in rows) / len(rows), 4) if rows else 0.0,
        })
    return {
        "coverage": coverage,
        "pricing_version": f"{pricing['schema_version']}@{pricing['effective_date']}",
        "default_routes": policy["provider_order"],
        "providers": providers,
    }


def _profile(run: EvaluationRun) -> dict[str, Any]:
    for item in run.trend_points or []:
        if item.get("kind") == "evaluation_profile":
            return item.get("profile") or {}
    return {}


def _database_evaluations(db: Session, workspace_id: str) -> list[dict[str, Any]]:
    rows = list(db.scalars(select(EvaluationRun).where(
        EvaluationRun.workspace_id == workspace_id,
    ).order_by(EvaluationRun.completed_at.desc())))
    result = []
    for run in rows:
        total = max(_int(run.golden_set_count), 1)
        profile = _profile(run)
        errors = [
            str(item.get("label")) for item in (run.error_distribution or [])
            if str(item.get("label") or "") not in {"", "无错误"} and _float(item.get("percent")) > 0
        ]
        result.append({
            "id": run.id,
            "source": "DATABASE",
            "suite": run.release_name,
            "version": str(profile.get("version") or "") or None,
            "source_sha": profile.get("source_sha"),
            "status": run.status,
            "pass_rate": round(min(_int(run.sql_execution_pass_count), _int(run.result_value_pass_count)) / total, 4),
            "result_accuracy": round(_float(run.result_accuracy) / 100, 4),
            "citation_accuracy": profile.get("citation_accuracy"),
            "runtime_calls": profile.get("runtime_calls"),
            "errors": errors,
            "artifacts": list(profile.get("artifacts") or []),
            "evidence_sha256": run.manifest_sha256,
            "executed_at": run.completed_at,
        })
    return result


def _evidence_status(payload: dict[str, Any]) -> str:
    raw = payload.get("status") or payload.get("day_5_status")
    if raw:
        return str(raw)
    return "PASS" if payload.get("passed") is True else "FAIL" if payload.get("passed") is False else "UNKNOWN"


def _evidence_metrics(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    actual = payload.get("actual_metrics") or {}
    rag = payload.get("rag") or {}
    suite = str(payload.get("suite") or payload.get("schema_version") or Path(path).stem)
    pass_rate = None
    result_accuracy = None
    citation_accuracy = None
    runtime_calls = payload.get("runtime_calls") or payload.get("upstream_runtime_calls")
    if "IBM_EVAL" in path:
        suite = "PHASE2_IBM_EVALUATION"
        result_accuracy = (payload.get("accuracy") or {}).get("result_value")
        pass_rate = 1.0 if payload.get("status") == "PASS" else 0.0
    elif "D_AGENT" in path:
        suite = "PHASE3_AGENT"
        pass_rate = actual.get("agent_success_rate")
    elif "D_FILE" in path:
        suite = "PHASE3_FILE"
        pass_rate = actual.get("file_result_accuracy")
        result_accuracy = actual.get("file_result_accuracy")
    elif "D_SANDBOX" in path:
        suite = "PHASE3_SANDBOX"
        pass_rate = 1.0 if payload.get("security_result") == "PASS" else 0.0
    elif payload.get("suite") == "CHATBI_V1_RAG_GOLDEN_120":
        pass_rate = 1.0 if payload.get("passed") else 0.0
        citation_accuracy = payload.get("citation_accuracy")
    elif payload.get("suite") == "CHATBI_V1_COMPLEX_E2E_10":
        pass_rate = 1.0 if payload.get("passed") else 0.0
    elif rag:
        suite = "PHASE3_RAG_AGENT_FINAL_ACCEPTANCE"
        pass_rate = 1.0 if payload.get("day_5_status") == "PASS" else 0.0
        citation_accuracy = rag.get("citation_accuracy")
    return {
        "suite": suite,
        "pass_rate": pass_rate,
        "result_accuracy": result_accuracy,
        "citation_accuracy": citation_accuracy,
        "runtime_calls": runtime_calls,
    }


def _evidence_evaluations() -> tuple[list[dict[str, Any]], list[str]]:
    rows = []
    warnings = []
    for relative in _EVIDENCE_PATHS:
        path = (_REPO_ROOT / relative).resolve()
        if _REPO_ROOT not in path.parents or not path.is_file():
            warnings.append(f"Missing allowlisted evidence: {relative}")
            continue
        raw = path.read_bytes()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            warnings.append(f"Invalid JSON evidence: {relative}")
            continue
        metrics = _evidence_metrics(relative, payload)
        failures = [str(item) for item in (payload.get("failures") or [])]
        blockers = [str(item) for item in (payload.get("blockers") or [])]
        evidence_paths = [relative]
        if payload.get("evidence_path"):
            evidence_paths.append(str(payload["evidence_path"]))
        rows.append({
            "id": f"evidence:{hashlib.sha256(relative.encode()).hexdigest()[:16]}",
            "source": "EVIDENCE",
            "suite": metrics["suite"],
            "version": payload.get("schema_version"),
            "source_sha": payload.get("tested_sha") or payload.get("git_sha") or payload.get("run_sha"),
            "status": _evidence_status(payload),
            "pass_rate": metrics["pass_rate"],
            "result_accuracy": metrics["result_accuracy"],
            "citation_accuracy": metrics["citation_accuracy"],
            "runtime_calls": metrics["runtime_calls"],
            "errors": failures + blockers,
            "artifacts": evidence_paths,
            "evidence_sha256": hashlib.sha256(raw).hexdigest(),
            "executed_at": payload.get("executed_at") or payload.get("generated_at") or payload.get("evaluated_at"),
        })
    return rows, warnings


def evaluation_governance_dashboard(db: Session, *, workspace_id: str) -> dict[str, Any]:
    evidence, warnings = _evidence_evaluations()
    rows = [*_database_evaluations(db, workspace_id), *evidence]
    rows.sort(key=lambda item: _as_datetime(item["executed_at"]) if item["executed_at"] else datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return {
        "coverage": {
            "source": "DATABASE_AND_CHECKSUMMED_ALLOWLISTED_EVIDENCE",
            "complete": not warnings,
            "warnings": warnings + [
                "Historical evidence is labeled EVIDENCE and is never presented as a live database run.",
            ],
        },
        "runs": rows,
    }
