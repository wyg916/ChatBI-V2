from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access import Principal, get_conversation_principal, record_audit, require_permission
from app.core.config import get_settings
from app.db.session import SessionLocal, get_db
from app.models import Attachment, ChatMessage, Conversation
from app.model_gateway.ledger import bind_model_invocation_session
from app.schemas.chat import (
    ChatRequest,
    ChatCancelRequest,
    ChatResponse,
    ConversationCreate,
    ConversationDetail,
    ConversationRead,
    ConversationRename,
)
from app.services.chat import ChatService
from app.services.attachments import attachment_path
from app.services.conversations import get_conversation, list_conversations, list_messages
from app.streaming import PHASE_LABELS, StreamCancelled, StreamEventFactory, format_sse, phase_for_stage, stream_registry


router = APIRouter(tags=["authenticated chat"])
# Twenty clients may remain connected, but this two-core release topology runs
# at most six CPU/DB-heavy chat jobs at once. Queued streams have already
# received `accepted` and continue to receive heartbeats from reusable response
# stream workers, preventing business work from starving TTFE scheduling.
_CHAT_STREAM_EXECUTOR = ThreadPoolExecutor(max_workers=6, thread_name_prefix="chatbi-stream")


def _cleanup_cancelled_messages(conversation_id: str, client_message_id: str) -> None:
    """Remove only the messages created by one explicitly cancelled run."""
    with SessionLocal() as cleanup_db:
        user_message = cleanup_db.scalar(select(ChatMessage).where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.client_message_id == client_message_id,
        ))
        if user_message is None:
            return
        assistants = list(cleanup_db.scalars(select(ChatMessage).where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.parent_message_id == user_message.id,
            ChatMessage.role == "assistant",
        )))
        for assistant in assistants:
            cleanup_db.delete(assistant)
        cleanup_db.delete(user_message)
        cleanup_db.commit()


def _stream_principal(
    data: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> Principal:
    return get_conversation_principal(
        request, db, conversation_id=data.conversation_id, permission="query.ask",
    )


@router.post("/conversations", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
def create_conversation(data: ConversationCreate, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("conversation.manage"))):
    item = Conversation(workspace_id=principal.workspace_id, user_id=principal.user_id, title=data.title)
    db.add(item)
    db.flush()
    record_audit(db, principal, action="CONVERSATION_CREATE", resource_type="CONVERSATION", resource_id=item.id)
    db.commit()
    db.refresh(item)
    return item


@router.get("/conversations", response_model=list[ConversationRead])
def conversations(
    q: str = Query(default="", max_length=255),
    state: str = Query(default="active", pattern="^(active|archived|all)$"),
    project_id: str | None = Query(default=None, max_length=36),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("query.ask")),
):
    items = list_conversations(db, principal, query=q, state=state, project_id=project_id)
    record_audit(
        db, principal, action="CONVERSATION_SEARCH" if q else "CONVERSATION_LIST",
        resource_type="CONVERSATION", details={"state": state, "project_id": project_id, "query_length": len(q), "count": len(items)},
    )
    db.commit()
    return items


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def conversation_detail(conversation_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("query.ask"))):
    item = get_conversation(db, conversation_id, principal)
    detail = ConversationDetail.model_validate(item).model_copy(update={"messages": list_messages(db, item.id)})
    record_audit(db, principal, action="CONVERSATION_VIEW", resource_type="CONVERSATION", resource_id=item.id)
    db.commit()
    return detail


@router.patch("/conversations/{conversation_id}", response_model=ConversationRead)
def rename_conversation(
    conversation_id: str,
    data: ConversationRename,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("conversation.manage")),
):
    item = get_conversation(db, conversation_id, principal)
    item.title = data.title
    record_audit(db, principal, action="CONVERSATION_RENAME", resource_type="CONVERSATION", resource_id=item.id)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("conversation.manage"))):
    item = get_conversation(db, conversation_id, principal)
    attachments = list(db.scalars(select(Attachment).where(Attachment.conversation_id == item.id)))
    paths = [attachment_path(attachment) for attachment in attachments]
    record_audit(db, principal, action="CONVERSATION_DELETE", resource_type="CONVERSATION", resource_id=item.id)
    db.delete(item)
    db.commit()
    for path in paths:
        path.unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/chat", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
def chat(
    data: ChatRequest,
    response: Response,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("query.ask")),
):
    result = ChatService().execute(db, data, principal)
    if result.answer_envelope is not None:
        response.headers["X-Trace-ID"] = result.answer_envelope.trace_id
    return result


@router.post("/chat/stream")
def chat_stream(
    data: ChatRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(_stream_principal),
):
    # The joined dependency fails closed before the streaming response opens,
    # preserving the normal 401/403 boundary with one metadata round trip.
    # Yield dependencies otherwise retain this request-scoped Session for the
    # entire StreamingResponse. Release its transaction/connection before the
    # stream begins; the worker owns a separate bounded SessionLocal lifecycle.
    db.close()
    run_id = f"TRACE-{uuid4()}"
    factory = StreamEventFactory(
        run_id=run_id,
        conversation_id=data.conversation_id,
        message_id=data.client_message_id,
        request_id=data.client_message_id,
    )
    lifecycle = stream_registry.register(
        run_id,
        conversation_id=data.conversation_id,
        client_message_id=data.client_message_id,
    )
    events: Queue[tuple[str, dict] | None] = Queue()

    def progress(stage: str, detail: dict):
        lifecycle.checkpoint()
        public = {key: detail[key] for key in ("route", "status", "elapsed_ms") if key in detail}
        events.put(("stage", {"stage": stage, **public}))

    def answer_delta(delta: str) -> None:
        lifecycle.checkpoint()
        if delta:
            events.put(("delta", {"delta": delta}))

    def worker():
        stream_registry.task_started(run_id)
        try:
            with SessionLocal() as worker_db:
                with bind_model_invocation_session(worker_db):
                    result = ChatService().execute(
                        worker_db, data, principal, progress=progress,
                        cancellation_event=lifecycle.cancel_event,
                        answer_delta=answer_delta,
                        trace_id=run_id,
                        sse_streamed=True,
                    )
                lifecycle.checkpoint()
                events.put(("result", result.model_dump(mode="json")))
        except StreamCancelled:
            _cleanup_cancelled_messages(data.conversation_id, data.client_message_id)
            events.put(("cancelled", {"code": "RUN_CANCELLED", "message": "请求已取消。", "retryable": True}))
        except Exception as exc:
            code = str(exc.detail) if isinstance(exc, HTTPException) and isinstance(exc.detail, str) else f"CHAT_STREAM_{type(exc).__name__.upper()}"
            events.put(("error", {"code": code, "message": "请求执行失败，请稍后重试。", "retryable": True}))
        finally:
            stream_registry.task_finished(run_id)
            events.put(None)

    def stream():
        active_phase: str | None = None
        phase_started = perf_counter()
        terminal_sent = False

        def transition(next_phase: str | None):
            nonlocal active_phase, phase_started
            if next_phase == active_phase:
                return []
            phase_events = []
            if active_phase is not None:
                phase_events.append(factory.create(
                    "phase.completed",
                    phase=active_phase,
                    label=PHASE_LABELS[active_phase],
                    duration_ms=round((perf_counter() - phase_started) * 1000),
                    metadata={},
                ))
            active_phase = next_phase
            if active_phase is not None:
                phase_started = perf_counter()
                phase_events.append(factory.create(
                    "phase.started",
                    phase=active_phase,
                    label=PHASE_LABELS[active_phase],
                    metadata={},
                ))
            return phase_events

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
            # The public acknowledgement is the first yielded byte. Starting
            # database/model work only on the next generator iteration keeps
            # TTFE bounded even when the worker pool is under contention.
            # Reuse a bounded worker set. Creating an OS thread for every SSE
            # request leaves allocator arenas at an ever-rising RSS high-water
            # mark during sustained load, even after the threads exit.
            _CHAT_STREAM_EXECUTOR.submit(worker)
            while True:
                try:
                    item = events.get(timeout=0.5)
                except Empty:
                    continue
                if item is None:
                    break
                event, payload = item
                if event == "stage":
                    phase = phase_for_stage(str(payload.get("stage", "")))
                    if phase:
                        yield from render_many(transition(phase))
                    continue
                if event == "delta":
                    yield from render_many(transition("composing_answer"))
                    envelope = factory.create("answer.delta", delta=payload["delta"])
                    yield format_sse("answer.delta", envelope)
                    continue
                if event == "result":
                    yield from render_many(transition(None))
                    assistant = payload.get("assistant_message") or {}
                    assistant_status = str(assistant.get("status") or "FAILED")
                    if assistant_status in {"SUCCEEDED", "PARTIAL"}:
                        message_parts = payload.get("message_parts") or []
                        for part in message_parts:
                            part_type = str(part.get("type") or "")
                            if part_type in {"kpi", "chart", "table", "evidence"}:
                                artifact = factory.create(
                                    "artifact.ready",
                                    artifact_type=part_type,
                                    artifact=part,
                                )
                                yield format_sse("artifact.ready", artifact)
                        citations_part = next((part for part in message_parts if part.get("type") == "citations"), None)
                        if citations_part:
                            citations = factory.create("citations.ready", citations=citations_part.get("items") or [])
                            yield format_sse("citations.ready", citations)
                        terminal = factory.create(
                            "run.completed",
                            status=assistant_status,
                            result_semantic=payload.get("result_semantic") or "VALUE",
                            message_parts=message_parts,
                            response=payload,
                        )
                        yield format_sse("run.completed", terminal)
                    else:
                        response_payload = assistant.get("response_payload") or {}
                        error_part = next((part for part in response_payload.get("message_parts") or [] if part.get("type") == "error"), {})
                        terminal = factory.create(
                            "run.failed",
                            code=error_part.get("code") or assistant.get("error_code") or "CHAT_RUN_FAILED",
                            message=error_part.get("message") or "请求执行失败，请稍后重试。",
                            retryable=bool(error_part.get("retryable", True)),
                        )
                        yield format_sse("run.failed", terminal)
                    terminal_sent = True
                    break
                if event == "cancelled":
                    yield from render_many(transition(None))
                    terminal = factory.create("run.cancelled", **payload)
                    yield format_sse("run.cancelled", terminal)
                    terminal_sent = True
                    break
                if event == "error":
                    yield from render_many(transition(None))
                    terminal = factory.create("run.failed", **payload)
                    yield format_sse("run.failed", terminal)
                    terminal_sent = True
                    break
            if not terminal_sent:
                yield from render_many(transition(None))
                terminal = factory.create(
                    "run.cancelled" if lifecycle.cancel_event.is_set() else "run.failed",
                    code="RUN_CANCELLED" if lifecycle.cancel_event.is_set() else "STREAM_ENDED_WITHOUT_RESULT",
                    message="请求已取消。" if lifecycle.cancel_event.is_set() else "流式请求未返回结果。",
                    retryable=True,
                )
                yield format_sse(terminal["event_type"], terminal)
        finally:
            stream_registry.connection_closed(run_id)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "X-Trace-ID": run_id},
    )


@router.post("/chat/stream/cancel", status_code=status.HTTP_202_ACCEPTED)
def cancel_chat_stream(
    data: ChatCancelRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("query.ask")),
) -> dict[str, bool]:
    get_conversation(db, data.conversation_id, principal)
    lifecycle = stream_registry.cancel_matching(
        conversation_id=data.conversation_id,
        client_message_id=data.client_message_id,
    )
    if lifecycle is not None:
        # The explicit acknowledgement is the transaction boundary observed by
        # the browser.  A worker may already be committing when cancellation
        # arrives, so wait for its bounded completion and clean once more after
        # the commit window closes.  Cleanup remains scoped to this exact run.
        # Never let a non-cooperative provider make the acknowledgement hang.
        # The worker performs the same scoped cleanup when it eventually exits.
        if lifecycle.task_done.wait(timeout=max(1.0, get_settings().agent_timeout_ms / 1000 + 1.0)):
            _cleanup_cancelled_messages(data.conversation_id, data.client_message_id)
    return {"cancelled": lifecycle is not None}


@router.get("/chat/stream/diagnostics")
def chat_stream_diagnostics(_: Principal = Depends(require_permission("query.ask"))) -> dict:
    """Return aggregate lifecycle counters without exposing request content."""
    return stream_registry.snapshot()
