from __future__ import annotations

import hashlib
from queue import Empty, Queue
from threading import Thread
from time import perf_counter
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.access import Principal, require_permission
from app.db.session import SessionLocal, get_db
from app.integration.contracts import AnalysisRequest, AnalysisResponse
from app.integration.service import AnalysisService
from app.model_gateway import BudgetMode, RequestContext
from app.model_gateway.ledger import bind_model_invocation_session
from app.core.config import get_settings
from app.services.answer_composer import AnswerComposer
from app.services.answer_envelope import build_answer_envelope
from app.services.answer_presentation import AnswerPresenter
from app.streaming import PHASE_LABELS, StreamCancelled, StreamEventFactory, format_sse, phase_for_stage, stream_registry


router = APIRouter(tags=["controlled analysis"])


def _analysis_request_context(
    *,
    data: AnalysisRequest,
    principal: Principal,
    request_id: str,
    trace_id: str,
    conversation_id: str,
) -> RequestContext:
    return RequestContext(
        request_id=request_id,
        trace_id=trace_id,
        conversation_id=conversation_id,
        route=data.route.value if data.route else None,
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


def _commit_presentation_ledger(db: Session) -> bool:
    """Persist presenter invocations without making analysis delivery depend on audit I/O."""

    try:
        db.commit()
        return True
    except Exception:
        # The analysis result has already passed its own publication gates.  A
        # ledger outage must not replace that result with an HTTP/SSE failure.
        try:
            db.rollback()
        except Exception:
            pass
        return False


def _primary_model_attribution(payload: dict) -> dict:
    """Return only the model call that actually authored the source answer."""

    primary = payload.get("primary") if isinstance(payload.get("primary"), dict) else {}
    candidates = []
    for key in ("data", "data_evidence", "knowledge"):
        value = primary.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    candidates.append(primary)

    for candidate in candidates:
        plan = candidate.get("plan") if isinstance(candidate.get("plan"), dict) else {}
        model_call = plan.get("model_trace") if isinstance(plan.get("model_trace"), dict) else {}
        provider = candidate.get("provider") or model_call.get("resolved_provider")
        model = model_call.get("resolved_model")
        if provider or model or model_call:
            return {
                "provider": provider,
                "model": model,
                "model_call": model_call,
            }

        gateway = candidate.get("model_gateway") if isinstance(candidate.get("model_gateway"), dict) else {}
        provider = gateway.get("provider")
        model = gateway.get("model")
        if provider not in {None, "", "none"} or model not in {None, "", "none"}:
            return {
                "provider": provider,
                "model": model,
                "model_call": gateway,
            }
    return {"provider": None, "model": None, "model_call": {}}


@router.post("/analysis", response_model=AnalysisResponse, status_code=status.HTTP_201_CREATED)
def analyze(
    data: AnalysisRequest,
    response: Response,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("query.ask")),
) -> AnalysisResponse:
    result = AnalysisService().execute(db, data, principal)
    response.headers["X-Trace-ID"] = result.trace_id
    payload = result.model_dump(mode="json", exclude={"answer_envelope"})
    request_id = data.idempotency_key or result.trace_id
    request_context = _analysis_request_context(
        data=data,
        principal=principal,
        request_id=request_id,
        trace_id=result.trace_id,
        conversation_id=f"analysis-{result.trace_id}",
    ).model_copy(update={"route": result.route.value})
    with bind_model_invocation_session(db):
        content, presentation_trace, model_attribution = _present_analysis(
            data=data,
            payload=payload,
            request_context=request_context,
        )
    _commit_presentation_ledger(db)
    composed = AnswerComposer().compose(
        answer=content,
        status=result.status,
        response_payload={"analysis": payload},
    )
    envelope = build_answer_envelope(
        answer_id=f"analysis-assistant-{result.trace_id}",
        conversation_id=f"analysis-{result.trace_id}",
        message_id=f"analysis-assistant-{result.trace_id}",
        source_question_id=request_id,
        request_id=request_id,
        workspace_id=principal.workspace_id or "SYSTEM",
        trace_id=result.trace_id,
        route=result.route,
        status=result.status,
        content=composed.content,
        response_payload={"analysis": payload, "message_parts": composed.message_parts},
        trace_payload={
            "trace_id": result.trace_id,
            "presentation_status": payload["presentation_status"],
            "answer_presentation": presentation_trace,
            "model_provider": model_attribution.get("provider"),
            "model_name": model_attribution.get("model"),
            "model_call": model_attribution.get("model_call", {}),
        },
        message_parts=composed.message_parts,
        result_semantic=composed.result_semantic,
    )
    return result.model_copy(update={"answer_envelope": envelope})


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


def _present_analysis(
    *,
    data: AnalysisRequest,
    payload: dict,
    request_context: RequestContext,
    cancellation_event=None,
) -> tuple[str, dict, dict]:
    """Apply the same guarded final-presentation stage used by the Chat UI."""

    primary = payload.get("primary") if isinstance(payload.get("primary"), dict) else {}
    source_answer = _answer_text(payload)
    try:
        presentation = AnswerPresenter().present(
            route=str(payload.get("route") or (data.route.value if data.route else "DATA_QUERY")),
            status=str(payload.get("status") or "FAILED"),
            answer=source_answer,
            response_payload={"analysis": payload},
            request_context=request_context,
            error_code=primary.get("error_code"),
            cancellation_event=cancellation_event,
        )
    except StreamCancelled:
        raise
    except Exception:
        presentation_trace = {
            "status": "FALLBACK_PRESENTATION_ERROR",
            "mode": "SOURCE_PASSTHROUGH",
            "applied": False,
            "source_verified": False,
            "provider": None,
            "model": None,
            "guard": "SOURCE_FALLBACK",
            "purpose": "verified_answer_presentation",
            "model_call": {},
        }
        payload["answer_presentation"] = presentation_trace
        payload["presentation_status"] = presentation_trace["status"]
        return source_answer, presentation_trace, _primary_model_attribution(payload)
    presentation_trace = presentation.public_trace()
    payload["answer_presentation"] = presentation_trace
    payload["presentation_status"] = presentation.status
    primary_attribution = _primary_model_attribution(payload)
    if presentation.applied:
        presentation_model_call = presentation.trace or {}
        model_attribution = {
            "provider": presentation.provider,
            "model": presentation.model,
            "model_call": {
                **presentation_model_call,
                "purpose": "verified_answer_presentation",
                "primary_model_call": primary_attribution["model_call"],
                "presentation_model_call": presentation_model_call,
            },
        }
    else:
        # A rejected/failed presenter attempted a call but did not author the
        # published source answer.  Keep the attempt in answer_presentation,
        # while final attribution stays with the primary analysis model.
        model_attribution = primary_attribution
    return presentation.content, presentation_trace, model_attribution


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
    model_attribution: dict,
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
            "presentation_status": payload.get("presentation_status"),
            "answer_presentation": payload.get("answer_presentation", {}),
            "model_provider": model_attribution.get("provider"),
            "model_name": model_attribution.get("model"),
            "model_call": model_attribution.get("model_call", {}),
        },
        "error_code": None,
        "created_at": timestamp,
    }
    envelope = build_answer_envelope(
        answer_id=assistant_message_id,
        conversation_id=conversation_id,
        message_id=assistant_message_id,
        source_question_id=user_message_id,
        request_id=request_id,
        workspace_id=principal.workspace_id or "SYSTEM",
        trace_id=str(payload.get("trace_id") or run_id),
        route=route,
        status=str(payload.get("status") or "SUCCEEDED"),
        content=content,
        response_payload={"analysis": payload, "message_parts": message_parts},
        trace_payload=assistant_message["trace_payload"],
        message_parts=message_parts,
        result_semantic=result_semantic,
    )
    assistant_message["response_payload"] = {
        **assistant_message["response_payload"],
        "answer_envelope": envelope.model_dump(mode="json"),
    }
    return {
        "conversation": conversation,
        "user_message": user_message,
        "assistant_message": assistant_message,
        "message_parts": message_parts,
        "result_semantic": result_semantic,
        "answer_envelope": envelope.model_dump(mode="json"),
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
    request_context = _analysis_request_context(
        data=data,
        principal=principal,
        request_id=request_id,
        trace_id=run_id,
        conversation_id=conversation_id,
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
                with bind_model_invocation_session(db):
                    result = AnalysisService().execute(
                        db,
                        data,
                        principal,
                        progress_callback=progress,
                        cancellation_event=lifecycle.cancel_event,
                        request_context=request_context,
                    )
                    payload = result.model_dump(mode="json")
                    presentation_context = request_context.model_copy(
                        update={"route": result.route.value},
                    )
                    content, _, model_attribution = _present_analysis(
                        data=data,
                        payload=payload,
                        request_context=presentation_context,
                        cancellation_event=lifecycle.cancel_event,
                    )
                _commit_presentation_ledger(db)
            lifecycle.checkpoint()
            events.put(("result", {
                "analysis": payload,
                "content": content,
                "model_attribution": model_attribution,
            }))
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
                    analysis_payload = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
                    primary = analysis_payload.get("primary") if isinstance(analysis_payload.get("primary"), dict) else {}
                    composed = AnswerComposer().compose(
                        answer=str(payload.get("content") or _answer_text(analysis_payload)),
                        status=str(analysis_payload.get("status") or "FAILED"),
                        response_payload={"analysis": analysis_payload},
                        error_code=primary.get("error_code"),
                        phases=[],
                    )
                    if str(analysis_payload.get("status")) in {"SUCCEEDED", "PARTIAL"}:
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
                            payload=analysis_payload,
                            content=composed.content,
                            message_parts=composed.message_parts,
                            result_semantic=composed.result_semantic.value,
                            model_attribution=(
                                payload.get("model_attribution")
                                if isinstance(payload.get("model_attribution"), dict)
                                else {"provider": None, "model": None, "model_call": {}}
                            ),
                        )
                        terminal = factory.create(
                            "run.completed",
                            status=analysis_payload["status"],
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
