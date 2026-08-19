from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access import Principal, get_conversation_principal, require_permission
from app.db.session import SessionLocal, get_db
from app.models import Attachment, Conversation
from app.schemas.chat import ChatRequest, ChatResponse, ConversationCreate, ConversationDetail, ConversationRead
from app.services.chat import ChatService
from app.services.attachments import attachment_path
from app.services.conversations import get_conversation, list_messages
from app.streaming import StreamCancelled, StreamEventFactory, event_for_stage, format_sse, stream_registry


router = APIRouter(tags=["authenticated chat"])
# Twenty clients may remain connected, but this two-core release topology runs
# at most six CPU/DB-heavy chat jobs at once. Queued streams have already
# received `accepted` and continue to receive heartbeats from reusable response
# stream workers, preventing business work from starving TTFE scheduling.
_CHAT_STREAM_EXECUTOR = ThreadPoolExecutor(max_workers=6, thread_name_prefix="chatbi-stream")


def _stream_principal(
    data: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> Principal:
    return get_conversation_principal(
        request, db, conversation_id=data.conversation_id, permission="query.ask",
    )


@router.post("/conversations", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
def create_conversation(data: ConversationCreate, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("query.ask"))):
    item = Conversation(workspace_id=principal.workspace_id, user_id=principal.user_id, title=data.title)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/conversations", response_model=list[ConversationRead])
def conversations(db: Session = Depends(get_db), principal: Principal = Depends(require_permission("query.ask"))):
    return list(db.scalars(select(Conversation).where(
        Conversation.workspace_id == principal.workspace_id,
        Conversation.user_id == principal.user_id,
    ).order_by(Conversation.updated_at.desc())))


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def conversation_detail(conversation_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("query.ask"))):
    item = get_conversation(db, conversation_id, principal)
    return ConversationDetail.model_validate(item).model_copy(update={"messages": list_messages(db, item.id)})


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("query.ask"))):
    item = get_conversation(db, conversation_id, principal)
    attachments = list(db.scalars(select(Attachment).where(Attachment.conversation_id == item.id)))
    for attachment in attachments:
        attachment_path(attachment).unlink(missing_ok=True)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/chat", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
def chat(data: ChatRequest, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("query.ask"))):
    return ChatService().execute(db, data, principal)


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
    trace_id = f"STREAM-{uuid4()}"
    factory = StreamEventFactory(trace_id=trace_id)
    lifecycle = stream_registry.register(trace_id)
    events: Queue[tuple[str, dict] | None] = Queue()

    def progress(stage: str, detail: dict):
        lifecycle.checkpoint()
        public = {key: detail[key] for key in ("route", "status", "elapsed_ms", "role", "tool") if key in detail}
        events.put(("progress", {"stage": stage, **public}))

    def worker():
        stream_registry.task_started(trace_id)
        try:
            with SessionLocal() as worker_db:
                result = ChatService().execute(
                    worker_db, data, principal, progress=progress,
                    cancellation_event=lifecycle.cancel_event,
                )
                lifecycle.checkpoint()
                events.put(("result", result.model_dump(mode="json")))
        except StreamCancelled:
            events.put(("cancelled", {"code": "STREAM_CANCELLED"}))
        except Exception as exc:
            events.put(("error", {"code": f"CHAT_STREAM_{type(exc).__name__.upper()}"}))
        finally:
            stream_registry.task_finished(trace_id)
            events.put(None)

    def stream():
        try:
            accepted = factory.create("accepted", data={"conversation_id": data.conversation_id})
            yield format_sse("accepted", accepted)
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
                    yield format_sse("heartbeat", factory.create("heartbeat"))
                    continue
                if item is None:
                    break
                event, payload = item
                if event == "progress":
                    stage = str(payload.get("stage", ""))
                    if stage.upper() == "COMPLETED":
                        envelope = factory.create("completed", capability="chatbi", data=payload)
                        yield format_sse("progress", {**envelope, "stage": stage})
                        continue
                    protocol_event = event_for_stage(stage)
                    if protocol_event:
                        capability = str(payload.get("tool") or payload.get("role") or payload.get("route") or "chatbi")
                        envelope = factory.create(protocol_event, capability=capability, data=payload)
                        yield format_sse(protocol_event, envelope)
                        yield format_sse("progress", {**envelope, "stage": stage})
                    continue
                if event == "result":
                    assistant = payload.get("assistant_message") or {}
                    content = str(assistant.get("content") or "")
                    if content:
                        yield format_sse("answer_delta", factory.create("answer_delta", data={"text": content}))
                    response_payload = assistant.get("response_payload") or {}
                    if "chart" in str(response_payload).lower():
                        yield format_sse("chart_ready", factory.create("chart_ready"))
                    yield format_sse("completed", factory.create(
                        "completed",
                        data={"stage": "COMPLETED", "status": assistant.get("status")},
                    ))
                    yield format_sse("result", payload)
                    continue
                if event == "cancelled":
                    yield format_sse("cancelled", factory.create("cancelled", data=payload))
                    continue
                if event == "error":
                    yield format_sse("error", factory.create("error", data=payload))
        finally:
            stream_registry.connection_closed(trace_id)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "X-Trace-ID": trace_id},
    )


@router.get("/chat/stream/diagnostics")
def chat_stream_diagnostics(_: Principal = Depends(require_permission("query.ask"))) -> dict:
    """Return aggregate lifecycle counters without exposing request content."""
    return stream_registry.snapshot()
