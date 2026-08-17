from __future__ import annotations

import json
from queue import Queue
from threading import Thread

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access import Principal, require_permission
from app.db.session import SessionLocal, get_db
from app.models import Attachment, Conversation
from app.schemas.chat import ChatRequest, ChatResponse, ConversationCreate, ConversationDetail, ConversationRead
from app.services.chat import ChatService
from app.services.attachments import attachment_path
from app.services.conversations import get_conversation, list_messages


router = APIRouter(tags=["authenticated chat"])


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
def chat_stream(data: ChatRequest, principal: Principal = Depends(require_permission("query.ask"))):
    events: Queue[tuple[str, dict] | None] = Queue()

    def progress(stage: str, detail: dict):
        public = {key: detail[key] for key in ("route", "status", "elapsed_ms", "role", "tool") if key in detail}
        events.put(("progress", {"stage": stage, **public}))

    def worker():
        try:
            with SessionLocal() as db:
                result = ChatService().execute(db, data, principal, progress=progress)
                events.put(("result", result.model_dump(mode="json")))
        except Exception as exc:
            events.put(("error", {"code": f"CHAT_STREAM_{type(exc).__name__.upper()}"}))
        finally:
            events.put(None)

    Thread(target=worker, name="chatbi-chat-stream", daemon=True).start()

    def stream():
        while True:
            item = events.get()
            if item is None:
                break
            event, payload = item
            yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
