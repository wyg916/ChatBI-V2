from __future__ import annotations

import hashlib
from queue import Empty, Queue
from threading import Thread
from time import perf_counter
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.access import Principal, require_permission
from app.db.session import SessionLocal, get_db
from app.integration.contracts import AnalysisRequest, AnalysisResponse
from app.integration.service import AnalysisService
from app.model_gateway import BudgetMode, RequestContext
from app.core.config import get_settings
from app.services.answer_composer import AnswerComposer
from app.streaming import PHASE_LABELS, StreamCancelled, StreamEventFactory, format_sse, phase_for_stage, stream_registry


router = APIRouter(tags=["controlled analysis"])


@router.post("/analysis", response_model=AnalysisResponse, status_code=status.HTTP_201_CREATED)
def analyze(
    data: AnalysisRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("query.ask")),
) -> AnalysisResponse:
    return AnalysisService().execute(db, data, principal)


def _answer_text(payload: dict) -> str:
    primary = payload.get("primary") if isinstance(payload.get("primary"), dict) else {}
    if isinstance(primary.get("data"), dict):
        data_summary = str(primary["data"].get("summary") or "")
        knowledge = primary.get("knowledge") if isinstance(primary.get("knowledge"), dict) else {}
        knowledge_summary = str(knowledge.get("summary") or "")
        return "\n\n".join(item for item in (data_summary, knowledge_summary) if item)
    return str(
        primary.get("answer")
        or primary.get("summary")
        or primary.get("error_message")
        or primary.get("error_code")
        or "分析未形成可发布结论。"
    )


def _chat_response(
    *,
    data: AnalysisRequest,
    principal: Principal,
    run_id: str,
    conversation_id: str,
    payload: dict,
    content: str,
    message_parts: list[dict],
    result_semantic: str,
) -> dict:
    """Expose the canonical ChatResponse shape without inventing business facts."""
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    request_id = data.idempotency_key or run_id
    user_message_id = f"analysis-user-{request_id}"
    assistant_message_id = f"analysis-assistant-{run_id}"
    route = str(payload.get("route") or (data.route.value if data.route else "DATA_QUERY"))
    conversation = {
        "id": conversation_id,
        "title": " ".join(data.question.split())[:40] or "分析",
        "summary": "",
        "active_attachment_ids": [],
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    user_message = {
        "id": user_message_id,
        "conversation_id": conversation_id,
        "parent_message_id": None,
        "role": "user",
        "content": data.question,
        "route": route,
        "status": "COMPLETED",
        "attachment_ids": [],
        "context_payload": {
            "workspace_id": principal.workspace_id,
            "analysis_request_id": request_id,
        },
        "response_payload": {},
        "trace_payload": {"run_id": run_id},
        "error_code": None,
        "created_at": timestamp,
    }
    assistant_message = {
        "id": assistant_message_id,
        "conversation_id": conversation_id,
        "parent_message_id": user_message_id,
        "role": "assistant",
        "content": content,
        "route": route,
        "status": str(payload.get("status") or "SUCCEEDED"),
        "attachment_ids": [],
        "context_payload": {},
        "response_payload": {
            "analysis": payload,
            "message_parts": message_parts,
            "result_semantic": result_semantic,
        },
        "trace_payload": {
            "run_id": run_id,
            "trace_id": payload.get("trace_id"),
            "workspace_id": principal.workspace_id,
        },
        "error_code": None,
        "created_at": timestamp,
    }
    return {
        "conversation": conversation,
        "user_message": user_message,
        "assistant_message": assistant_message,
        "message_parts": message_parts,
        "result_semantic": result_semantic,
    }


@router.post("/analysis/stream")
def analyze_stream(
    data: AnalysisRequest,
    principal: Principal = Depends(require_permission("query.ask")),
) -> StreamingResponse:
    """Stream the same public business protocol as chat without internal reasoning."""
    run_id = f"TRACE-{uuid4()}"
    conversation_id = f"analysis-{run_id}"
    request_id = data.idempotency_key or f"REQ-{uuid4()}"
    message_id = request_id
    factory = StreamEventFactory(
        run_id, conversation_id, message_id, request_id=request_id,
    )
    request_context = RequestContext(
        request_id=request_id,
        trace_id=run_id,
        conversation_id=conversation_id,
        user_id=principal.user_id or principal.email,
        workspace_id=principal.workspace_id or "SYSTEM",
        datasource_id=data.datasource_id,
        roles=frozenset({principal.role}),
        permission_hash=hashlib.sha256(
            f"{principal.workspace_id}:{principal.user_id}:{principal.role}".encode("utf-8")
        ).hexdigest(),
        question=data.question,
        budget_mode=BudgetMode(get_settings().model_budget_mode),
    )
    lifecycle = stream_registry.register(run_id)
    events: Queue[tuple[str, dict] | None] = Queue()

    def progress(stage, detail):
        lifecycle.checkpoint()
        allowed = {key: detail[key] for key in ("elapsed_ms", "status") if key in detail}
        events.put(("stage", {"stage": stage.value, **allowed}))

    def worker() -> None:
        stream_registry.task_started(run_id)
        try:
            with SessionLocal() as db:
                result = AnalysisService().execute(
                    db,
                    data,
                    principal,
                    progress_callback=progress,
                    cancellation_event=lifecycle.cancel_event,
                    request_context=request_context,
                )
            lifecycle.checkpoint()
            events.put(("result", result.model_dump(mode="json")))
        except StreamCancelled:
            events.put(("cancelled", {"code": "RUN_CANCELLED", "message": "请求已取消。", "retryable": True}))
        except Exception as exc:
            events.put(("error", {
                "code": f"ANALYSIS_STREAM_{type(exc).__name__.upper()}",
                "message": "分析执行失败，请稍后重试。",
                "retryable": True,
            }))
        finally:
            stream_registry.task_finished(run_id)
            events.put(None)

    def event_stream():
        active_phase: str | None = None
        phase_started = perf_counter()
        terminal_sent = False

        def transition(next_phase: str | None):
            nonlocal active_phase, phase_started
            if next_phase == active_phase:
                return []
            result = []
            if active_phase is not None:
                result.append(factory.create(
                    "phase.completed",
                    phase=active_phase,
                    label=PHASE_LABELS[active_phase],
                    duration_ms=round((perf_counter() - phase_started) * 1000),
                    metadata={},
                ))
            active_phase = next_phase
            if active_phase is not None:
                phase_started = perf_counter()
                result.append(factory.create(
                    "phase.started",
                    phase=active_phase,
                    label=PHASE_LABELS[active_phase],
                    metadata={},
                ))
            return result

        def render_many(payloads):
            for payload in payloads:
                yield format_sse(payload["event_type"], payload)

        try:
            started = factory.create(
                "run.started",
                status="RUNNING",
                route=data.route.value if data.route else "AUTO",
            )
            yield format_sse("run.started", started)
            Thread(target=worker, name="chatbi-analysis-stream", daemon=True).start()
            while True:
                try:
                    item = events.get(timeout=0.5)
                except Empty:
                    continue
                if item is None:
                    break
                event, payload = item
                if event == "stage":
                    phase = phase_for_stage(str(payload.get("stage") or ""))
                    if phase:
                        yield from render_many(transition(phase))
                    continue
                if event == "result":
                    yield from render_many(transition("composing_answer"))
                    primary = payload.get("primary") if isinstance(payload.get("primary"), dict) else {}
                    composed = AnswerComposer().compose(
                        answer=_answer_text(payload),
                        status=str(payload.get("status") or "FAILED"),
                        response_payload={"analysis": payload},
                        error_code=primary.get("error_code"),
                        phases=[],
                    )
                    if str(payload.get("status")) in {"SUCCEEDED", "PARTIAL"}:
                        for delta in composed.deltas():
                            envelope = factory.create("answer.delta", delta=delta)
                            yield format_sse("answer.delta", envelope)
                        yield from render_many(transition(None))
                        for part in composed.message_parts:
                            if part.get("type") in {"kpi", "chart", "table", "evidence"}:
                                artifact = factory.create(
                                    "artifact.ready",
                                    artifact_type=part["type"],
                                    artifact=part,
                                )
                                yield format_sse("artifact.ready", artifact)
                        if composed.citations:
                            citations = factory.create("citations.ready", citations=composed.citations)
                            yield format_sse("citations.ready", citations)
                        response = _chat_response(
                            data=data,
                            principal=principal,
                            run_id=run_id,
                            conversation_id=conversation_id,
                            payload=payload,
                            content=composed.content,
                            message_parts=composed.message_parts,
                            result_semantic=composed.result_semantic.value,
                        )
                        terminal = factory.create(
                            "run.completed",
                            status=payload["status"],
                            result_semantic=composed.result_semantic.value,
                            message_parts=composed.message_parts,
                            response=response,
                        )
                        yield format_sse("run.completed", terminal)
                    else:
                        yield from render_many(transition(None))
                        error = composed.message_parts[0]
                        terminal = factory.create(
                            "run.failed",
                            code=error["code"],
                            message=error["message"],
                            retryable=error["retryable"],
                        )
                        yield format_sse("run.failed", terminal)
                    terminal_sent = True
                    break
                if event in {"cancelled", "error"}:
                    yield from render_many(transition(None))
                    terminal_type = "run.cancelled" if event == "cancelled" else "run.failed"
                    terminal = factory.create(terminal_type, **payload)
                    yield format_sse(terminal_type, terminal)
                    terminal_sent = True
                    break
            if not terminal_sent:
                yield from render_many(transition(None))
                cancelled = lifecycle.cancel_event.is_set()
                terminal_type = "run.cancelled" if cancelled else "run.failed"
                terminal = factory.create(
                    terminal_type,
                    code="RUN_CANCELLED" if cancelled else "STREAM_ENDED_WITHOUT_RESULT",
                    message="请求已取消。" if cancelled else "流式请求未返回结果。",
                    retryable=True,
                )
                yield format_sse(terminal_type, terminal)
        finally:
            stream_registry.connection_closed(run_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "X-Trace-ID": run_id},
    )
