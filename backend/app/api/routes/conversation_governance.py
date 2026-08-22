from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.access import Principal, record_audit, require_permission
from app.core.auth import new_session_token, token_digest
from app.db.session import get_db
from app.models import Attachment, ChatMessage, Conversation, ConversationShare, Project
from app.schemas.chat import (
    ConversationBatchRequest,
    ConversationBatchResult,
    ConversationProjectUpdate,
    ConversationRead,
    ConversationShareCreate,
    ConversationShareCreated,
    ConversationShareRead,
    ProjectCreate,
    ProjectRead,
    SharedConversationRead,
    SharedMessageRead,
)
from app.services.attachments import attachment_path
from app.services.conversations import (
    get_conversation,
    get_conversation_share,
    get_project,
    list_conversations,
    list_messages,
    list_projects,
    public_message_parts,
    redact_public_text,
    require_owned_conversations,
)


router = APIRouter(tags=["conversation governance"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _public_principal(workspace_id: str) -> Principal:
    return Principal(None, workspace_id, "shared-link", "Shared link", "PUBLIC")


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    data: ProjectCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("project.manage")),
):
    duplicate = db.scalar(select(Project).where(
        Project.workspace_id == principal.workspace_id,
        Project.user_id == principal.user_id,
        func.lower(Project.name) == data.name.lower(),
    ))
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Project name already exists")
    item = Project(
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        name=data.name,
        description=data.description.strip(),
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Project name already exists") from exc
    record_audit(db, principal, action="PROJECT_CREATE", resource_type="PROJECT", resource_id=item.id)
    db.commit()
    db.refresh(item)
    return item


@router.get("/projects", response_model=list[ProjectRead])
def projects(
    q: str = Query(default="", max_length=255),
    state: str = Query(default="active", pattern="^(active|archived|all)$"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("project.manage")),
):
    items = list_projects(db, principal, query=q, state=state)
    record_audit(
        db, principal, action="PROJECT_SEARCH" if q else "PROJECT_LIST", resource_type="PROJECT",
        details={"state": state, "query_length": len(q), "count": len(items)},
    )
    db.commit()
    return items


@router.get("/projects/{project_id}/conversations", response_model=list[ConversationRead])
def project_conversations(
    project_id: str,
    q: str = Query(default="", max_length=255),
    state: str = Query(default="active", pattern="^(active|archived|all)$"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("project.manage")),
):
    items = list_conversations(db, principal, query=q, state=state, project_id=project_id)
    record_audit(
        db, principal, action="PROJECT_CONVERSATION_SEARCH", resource_type="PROJECT", resource_id=project_id,
        details={"state": state, "query_length": len(q), "count": len(items)},
    )
    db.commit()
    return items


@router.post("/projects/{project_id}/archive", response_model=ProjectRead)
def archive_project(
    project_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("project.manage")),
):
    item = get_project(db, project_id, principal)
    item.archived_at = item.archived_at or _now()
    record_audit(db, principal, action="PROJECT_ARCHIVE", resource_type="PROJECT", resource_id=item.id)
    db.commit()
    db.refresh(item)
    return item


@router.post("/projects/{project_id}/restore", response_model=ProjectRead)
def restore_project(
    project_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("project.manage")),
):
    item = get_project(db, project_id, principal)
    item.archived_at = None
    record_audit(db, principal, action="PROJECT_RESTORE", resource_type="PROJECT", resource_id=item.id)
    db.commit()
    db.refresh(item)
    return item


@router.post("/conversations/batch/archive", response_model=ConversationBatchResult)
def batch_archive_conversations(
    data: ConversationBatchRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("conversation.manage")),
):
    items = require_owned_conversations(db, data.conversation_ids, principal)
    now = _now()
    for item in items:
        item.archived_at = item.archived_at or now
        item.pinned_at = None
    record_audit(
        db, principal, action="CONVERSATION_BATCH_ARCHIVE", resource_type="CONVERSATION",
        details={"conversation_ids": data.conversation_ids, "affected_count": len(items)},
    )
    db.commit()
    return ConversationBatchResult(affected_count=len(items), conversation_ids=data.conversation_ids)


@router.post("/conversations/batch/delete", response_model=ConversationBatchResult)
def batch_delete_conversations(
    data: ConversationBatchRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("conversation.manage")),
):
    items = require_owned_conversations(db, data.conversation_ids, principal)
    attachments = list(db.scalars(select(Attachment).where(Attachment.conversation_id.in_(data.conversation_ids))))
    paths = [attachment_path(item) for item in attachments]
    for conversation in items:
        db.delete(conversation)
    record_audit(
        db, principal, action="CONVERSATION_BATCH_DELETE", resource_type="CONVERSATION",
        details={"conversation_ids": data.conversation_ids, "affected_count": len(items)},
    )
    db.commit()
    for path in paths:
        path.unlink(missing_ok=True)
    return ConversationBatchResult(affected_count=len(items), conversation_ids=data.conversation_ids)


@router.put("/conversations/{conversation_id}/project", response_model=ConversationRead)
def move_conversation_to_project(
    conversation_id: str,
    data: ConversationProjectUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("project.manage")),
):
    conversation = get_conversation(db, conversation_id, principal)
    project = get_project(db, data.project_id, principal)
    if project.archived_at is not None:
        raise HTTPException(status_code=409, detail="Cannot move a conversation to an archived project")
    conversation.project_id = project.id
    conversation.updated_at = _now()
    record_audit(
        db, principal, action="CONVERSATION_PROJECT_BIND", resource_type="CONVERSATION", resource_id=conversation.id,
        details={"project_id": project.id},
    )
    db.commit()
    db.refresh(conversation)
    return conversation


@router.delete("/conversations/{conversation_id}/project", response_model=ConversationRead)
def remove_conversation_from_project(
    conversation_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("project.manage")),
):
    conversation = get_conversation(db, conversation_id, principal)
    previous_project_id = conversation.project_id
    conversation.project_id = None
    conversation.updated_at = _now()
    record_audit(
        db, principal, action="CONVERSATION_PROJECT_REMOVE", resource_type="CONVERSATION", resource_id=conversation.id,
        details={"project_id": previous_project_id},
    )
    db.commit()
    db.refresh(conversation)
    return conversation


@router.post("/conversations/{conversation_id}/pin", response_model=ConversationRead)
def pin_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("conversation.manage")),
):
    item = get_conversation(db, conversation_id, principal)
    if item.archived_at is not None:
        raise HTTPException(status_code=409, detail="Archived conversations cannot be pinned")
    item.pinned_at = item.pinned_at or _now()
    record_audit(db, principal, action="CONVERSATION_PIN", resource_type="CONVERSATION", resource_id=item.id)
    db.commit()
    db.refresh(item)
    return item


@router.post("/conversations/{conversation_id}/unpin", response_model=ConversationRead)
def unpin_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("conversation.manage")),
):
    item = get_conversation(db, conversation_id, principal)
    item.pinned_at = None
    record_audit(db, principal, action="CONVERSATION_UNPIN", resource_type="CONVERSATION", resource_id=item.id)
    db.commit()
    db.refresh(item)
    return item


@router.post("/conversations/{conversation_id}/archive", response_model=ConversationRead)
def archive_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("conversation.manage")),
):
    item = get_conversation(db, conversation_id, principal)
    item.archived_at = item.archived_at or _now()
    item.pinned_at = None
    record_audit(db, principal, action="CONVERSATION_ARCHIVE", resource_type="CONVERSATION", resource_id=item.id)
    db.commit()
    db.refresh(item)
    return item


@router.post("/conversations/{conversation_id}/restore", response_model=ConversationRead)
def restore_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("conversation.manage")),
):
    item = get_conversation(db, conversation_id, principal)
    item.archived_at = None
    record_audit(db, principal, action="CONVERSATION_RESTORE", resource_type="CONVERSATION", resource_id=item.id)
    db.commit()
    db.refresh(item)
    return item


@router.post(
    "/conversations/{conversation_id}/shares",
    response_model=ConversationShareCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation_share(
    conversation_id: str,
    data: ConversationShareCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("conversation.share")),
):
    conversation = get_conversation(db, conversation_id, principal)
    raw_token = new_session_token()
    item = ConversationShare(
        conversation_id=conversation.id,
        workspace_id=principal.workspace_id,
        created_by_user_id=principal.user_id,
        token_hash=token_digest(raw_token),
        expires_at=_now() + timedelta(hours=data.expires_in_hours),
    )
    db.add(item)
    db.flush()
    record_audit(
        db, principal, action="CONVERSATION_SHARE_CREATE", resource_type="CONVERSATION_SHARE", resource_id=item.id,
        details={"conversation_id": conversation.id, "expires_in_hours": data.expires_in_hours},
    )
    db.commit()
    db.refresh(item)
    return ConversationShareCreated(
        **ConversationShareRead.model_validate(item).model_dump(),
        token=raw_token,
        share_path=f"/share/{raw_token}",
    )


@router.get("/conversations/{conversation_id}/shares", response_model=list[ConversationShareRead])
def conversation_shares(
    conversation_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("conversation.share")),
):
    conversation = get_conversation(db, conversation_id, principal)
    items = list(db.scalars(select(ConversationShare).where(
        ConversationShare.conversation_id == conversation.id,
        ConversationShare.workspace_id == principal.workspace_id,
        ConversationShare.created_by_user_id == principal.user_id,
    ).order_by(ConversationShare.created_at.desc())))
    record_audit(
        db, principal, action="CONVERSATION_SHARE_LIST", resource_type="CONVERSATION", resource_id=conversation.id,
        details={"count": len(items)},
    )
    db.commit()
    return items


@router.post("/conversation-shares/{share_id}/revoke", response_model=ConversationShareRead)
def revoke_conversation_share(
    share_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("conversation.share")),
):
    item = get_conversation_share(db, share_id, principal)
    already_revoked = item.revoked_at is not None
    item.revoked_at = item.revoked_at or _now()
    record_audit(
        db, principal, action="CONVERSATION_SHARE_REVOKE", resource_type="CONVERSATION_SHARE", resource_id=item.id,
        details={"conversation_id": item.conversation_id, "already_revoked": already_revoked},
    )
    db.commit()
    db.refresh(item)
    return item


@router.get("/shared-conversations/{token}", response_model=SharedConversationRead)
def shared_conversation(token: str, db: Session = Depends(get_db)):
    if len(token) < 32 or len(token) > 128:
        raise HTTPException(status_code=404, detail="Shared conversation not found")
    item = db.scalar(select(ConversationShare).where(ConversationShare.token_hash == token_digest(token)))
    if item is None:
        raise HTTPException(status_code=404, detail="Shared conversation not found")
    public_principal = _public_principal(item.workspace_id)
    now = _now()
    if item.revoked_at is not None or _aware(item.expires_at) <= now:
        reason = "REVOKED" if item.revoked_at is not None else "EXPIRED"
        record_audit(
            db, public_principal, action="CONVERSATION_SHARE_ACCESS", resource_type="CONVERSATION_SHARE",
            resource_id=item.id, status="DENIED", details={"reason": reason},
        )
        db.commit()
        raise HTTPException(status_code=410, detail="Shared conversation is no longer available")
    conversation = db.get(Conversation, item.conversation_id)
    if conversation is None or conversation.workspace_id != item.workspace_id:
        raise HTTPException(status_code=404, detail="Shared conversation not found")
    messages = [
        SharedMessageRead(
            id=message.id,
            role=message.role,
            content=redact_public_text(message.content),
            message_parts=public_message_parts(message),
            created_at=message.created_at,
        )
        for message in list_messages(db, conversation.id)
        if message.role in {"user", "assistant"}
    ]
    item.access_count += 1
    item.last_accessed_at = now
    record_audit(
        db, public_principal, action="CONVERSATION_SHARE_ACCESS", resource_type="CONVERSATION_SHARE",
        resource_id=item.id, details={"conversation_id": conversation.id},
    )
    db.commit()
    return SharedConversationRead(
        share_id=item.id,
        title=redact_public_text(conversation.title, limit=255),
        summary=redact_public_text(conversation.summary),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        expires_at=item.expires_at,
        messages=messages,
    )
