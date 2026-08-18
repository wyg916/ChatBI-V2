import csv
import io
import json

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
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


@router.get("/{attachment_id}/artifact")
def attachment_artifact(
    attachment_id: str,
    format: str = Query(default="csv", pattern="^(csv|json)$"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("query.ask")),
):
    item = get_attachment(db, attachment_id, principal)
    if item.status != "READY" or item.kind != "STRUCTURED":
        return Response(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    payload = item.extracted_payload or {}
    sheets = payload.get("sheets") or {"data": payload}
    if format == "json":
        content = json.dumps({"attachment_id": item.id, "filename": item.filename, "sheets": sheets}, ensure_ascii=False, indent=2)
        return Response(content, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{item.id}.json"'})
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    for sheet_name, sheet in sheets.items():
        writer.writerow([f"sheet:{sheet_name}"])
        columns = list(sheet.get("columns") or [])
        writer.writerow(columns)
        for row in (sheet.get("preview") or [])[:100]:
            writer.writerow([row.get(column) for column in columns])
    return Response(output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{item.id}.csv"'})


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_attachment(attachment_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("query.ask"))):
    delete_attachment(db, get_attachment(db, attachment_id, principal))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
