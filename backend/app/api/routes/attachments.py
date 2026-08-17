from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access import Principal, require_permission
from app.db.session import get_db
from app.models import Attachment
from app.schemas.chat import AttachmentRead
from app.services.attachments import cleanup_expired, create_attachment, delete_attachment, get_attachment
from app.services.conversations import get_conversation


router = APIRouter(prefix="/attachments", tags=["conversation attachments"])


@router.post("", response_model=AttachmentRead, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    conversation_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("query.ask")),
):
    cleanup_expired(db)
    return await create_attachment(db, principal, conversation_id, file)


@router.get("", response_model=list[AttachmentRead])
def list_attachments(conversation_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("query.ask"))):
    get_conversation(db, conversation_id, principal)
    cleanup_expired(db)
    return list(db.scalars(select(Attachment).where(
        Attachment.conversation_id == conversation_id,
        Attachment.workspace_id == principal.workspace_id,
        Attachment.user_id == principal.user_id,
    ).order_by(Attachment.created_at)))


@router.get("/{attachment_id}", response_model=AttachmentRead)
def attachment_detail(attachment_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("query.ask"))):
    return get_attachment(db, attachment_id, principal)


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_attachment(attachment_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("query.ask"))):
    delete_attachment(db, get_attachment(db, attachment_id, principal))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
