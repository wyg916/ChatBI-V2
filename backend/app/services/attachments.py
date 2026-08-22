from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd
from docx import Document
from fastapi import HTTPException, UploadFile
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access import Principal
from app.core.config import get_settings
from app.file_multimodal.contracts import AttachmentKind, ParsedAttachment
from app.file_multimodal.parsers import parse_attachment
from app.models import Attachment, Conversation
from app.services.conversations import get_conversation


STRUCTURED = {".csv", ".xls", ".xlsx", ".parquet"}
DOCUMENT = {".pdf", ".docx", ".txt", ".md"}
IMAGES = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED = STRUCTURED | DOCUMENT | IMAGES
PROMPT_INJECTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"忽略.{0,12}(之前|以上|系统).{0,8}(指令|提示)",
        r"(system|developer)\s*prompt",
        r"(绕过|跳过|disable).{0,16}(权限|guard|acl|安全)",
        r"(exfiltrate|reveal).{0,24}(secret|credential|prompt)",
    )
)
MIME = {
    ".csv": {"text/csv", "application/csv", "text/plain"},
    ".xls": {"application/vnd.ms-excel", "application/octet-stream"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/zip"},
    ".parquet": {"application/vnd.apache.parquet", "application/octet-stream"},
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip"},
    ".txt": {"text/plain"},
    ".md": {"text/markdown", "text/plain"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".webp": {"image/webp"},
}


def storage_root() -> Path:
    root = Path(get_settings().attachment_storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def attachment_path(item: Attachment) -> Path:
    root = storage_root()
    path = (root / item.storage_key).resolve()
    if root not in path.parents:
        raise RuntimeError("Invalid attachment storage key")
    return path


def _validate_signature(extension: str, data: bytes) -> None:
    if extension == ".pdf" and not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="File signature does not match PDF")
    if extension == ".xls" and not data.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        raise HTTPException(status_code=415, detail="File signature does not match XLS")
    if extension == ".parquet" and not (data.startswith(b"PAR1") and data.endswith(b"PAR1")):
        raise HTTPException(status_code=415, detail="File signature does not match Parquet")
    if extension in {".xlsx", ".docx"}:
        if not data.startswith(b"PK"):
            raise HTTPException(status_code=415, detail="File signature does not match Office document")
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
        except (zipfile.BadZipFile, OSError) as exc:
            raise HTTPException(status_code=415, detail="Invalid Office document archive") from exc
        required = "xl/workbook.xml" if extension == ".xlsx" else "word/document.xml"
        if required not in names:
            raise HTTPException(status_code=415, detail="Office document structure does not match extension")
    if extension == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=415, detail="File signature does not match PNG")
    if extension in {".jpg", ".jpeg"} and not data.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=415, detail="File signature does not match JPEG")
    if extension == ".webp" and not (data.startswith(b"RIFF") and data[8:12] == b"WEBP"):
        raise HTTPException(status_code=415, detail="File signature does not match WebP")
    if extension in {".csv", ".txt", ".md"}:
        if b"\x00" in data[:8192]:
            raise HTTPException(status_code=415, detail="Text file contains binary data")
        try:
            data[:8192].decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="Text file must use UTF-8") from exc


def _dataframe_payload(frame: pd.DataFrame) -> dict:
    settings = get_settings()
    if len(frame) > settings.attachment_max_rows:
        raise ValueError("FILE_ROW_LIMIT_EXCEEDED")
    normalized = frame.where(pd.notna(frame), None)
    preview = json.loads(normalized.head(100).to_json(orient="records", date_format="iso", force_ascii=False))
    describe = json.loads(normalized.describe(include="all").fillna("").to_json(force_ascii=False))
    return {
        "row_count": len(frame),
        "columns": [str(value) for value in frame.columns],
        "dtypes": {str(key): str(value) for key, value in frame.dtypes.items()},
        "preview": preview,
        "describe": describe,
    }


def _reject_prompt_injection(text: str) -> None:
    if any(pattern.search(text) for pattern in PROMPT_INJECTION_PATTERNS):
        raise ValueError("PROMPT_INJECTION_DETECTED")


def _parsed_payload(parsed: ParsedAttachment) -> dict:
    """Persist a bounded index while retaining the raw file for full-file queries."""
    settings = get_settings()
    payload: dict = {
        "parser": "chatbi-file-multimodal-v1",
        "file_sha256": parsed.file_sha256,
        "result_signature": parsed.result_signature,
        "requires_vision": parsed.requires_vision,
        "page_count": parsed.page_count,
    }
    if parsed.tables:
        sheets = {
            table.name: {
                "row_count": table.row_count,
                "columns": list(table.columns),
                # This is an index/preview only. Analysis reparses the immutable raw
                # file and therefore never reports a preview as a full-file result.
                "preview": [dict(row) for row in table.rows[:100]],
            }
            for table in parsed.tables
        }
        first = next(iter(sheets.values()))
        payload.update({
            **first,
            "row_count": sum(item["row_count"] for item in sheets.values()),
            "sheet_names": list(sheets),
            "sheets": sheets,
        })
    if parsed.text_evidence:
        evidence = []
        remaining = settings.attachment_text_max_chars
        for item in parsed.text_evidence:
            if remaining <= 0:
                break
            text = item.text[:remaining]
            remaining -= len(text)
            evidence.append({"text": text, "locator": item.locator.__dict__})
        payload["evidence"] = evidence
        payload["text"] = "\n".join(item["text"] for item in evidence)
    return payload


def _extract(
    filename: str,
    declared_mime: str | bytes,
    data: bytes | None = None,
) -> tuple[str, dict]:
    """Parse an upload while retaining the historical ``_extract(ext, data)`` call."""
    if data is None:
        if not isinstance(declared_mime, bytes):
            raise TypeError("legacy _extract requires file bytes as the second argument")
        data = declared_mime
        extension = filename.lower() if filename.lower() in ALLOWED else Path(filename).suffix.lower()
        if extension not in MIME:
            raise ValueError("UNSUPPORTED_FILE_TYPE")
        declared_mime = sorted(MIME[extension])[0]
        if filename.lower() == extension:
            filename = f"upload{extension}"
    parsed = parse_attachment(
        filename,
        declared_mime,
        data,
        max_rows=get_settings().attachment_max_rows,
    )
    payload = _parsed_payload(parsed)
    if parsed.kind == AttachmentKind.IMAGE:
        with Image.open(io.BytesIO(data)) as image:
            payload.update({"width": image.width, "height": image.height, "format": image.format})
    return parsed.kind.value, payload


def cleanup_expired(db: Session) -> int:
    now = datetime.now(timezone.utc)
    items = list(db.scalars(select(Attachment).where(Attachment.expires_at <= now)))
    for item in items:
        attachment_path(item).unlink(missing_ok=True)
        db.delete(item)
    if items:
        db.commit()
    return len(items)


async def create_attachment(db: Session, principal: Principal, conversation_id: str, upload: UploadFile) -> Attachment:
    conversation = get_conversation(db, conversation_id, principal)
    settings = get_settings()
    filename = Path(upload.filename or "").name
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED:
        raise HTTPException(status_code=415, detail="UNSUPPORTED_FILE_TYPE")
    declared = (upload.content_type or "").lower()
    if declared not in MIME[extension]:
        raise HTTPException(status_code=415, detail="MIME_EXTENSION_MISMATCH")
    data = await upload.read(settings.attachment_max_bytes + 1)
    if not data:
        raise HTTPException(status_code=422, detail="EMPTY_FILE")
    if len(data) > settings.attachment_max_bytes:
        raise HTTPException(status_code=413, detail="FILE_TOO_LARGE")
    _validate_signature(extension, data)
    storage_key = f"{uuid4().hex}{extension}"
    item = Attachment(
        workspace_id=principal.workspace_id,
        user_id=principal.user_id,
        conversation_id=conversation.id,
        filename=filename[:255],
        extension=extension,
        mime_type=declared,
        kind="UNKNOWN",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        storage_key=storage_key,
        status="PROCESSING",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.attachment_ttl_hours),
    )
    path = storage_root() / storage_key
    path.write_bytes(data)
    try:
        item.kind, item.extracted_payload = _extract(filename, declared, data)
        item.status = "READY"
    except Exception as exc:
        path.unlink(missing_ok=True)
        item.status = "FAILED"
        item.error_code = str(exc)[:64] or "FILE_PARSE_FAILED"
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def get_attachment(db: Session, attachment_id: str, principal: Principal) -> Attachment:
    item = db.get(Attachment, attachment_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if item.workspace_id != principal.workspace_id or item.user_id != principal.user_id:
        raise HTTPException(status_code=403, detail="Attachment access denied")
    return item


def delete_attachment(db: Session, item: Attachment) -> None:
    conversation = db.get(Conversation, item.conversation_id)
    if conversation is not None and item.id in conversation.active_attachment_ids:
        conversation.active_attachment_ids = [value for value in conversation.active_attachment_ids if value != item.id]
    attachment_path(item).unlink(missing_ok=True)
    db.delete(item)
    db.commit()
