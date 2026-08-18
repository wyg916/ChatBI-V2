from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import httpx
import xlwt
from docx import Document
from PIL import Image
from pypdf import PdfWriter
from sqlalchemy import select

from app.core.auth import hash_password
from app.core.config import Settings
from app.integration.model_gateway import ModelGateway, ModelReply
from app.models import AppUser, Attachment, AuthSession, Conversation, Workspace
from app.services.attachments import attachment_path
from app.services.chat import ChatService
from app.services.conversations import extract_slots


PASSWORD = "phase2-test-password"


def _seed_login(db_session, *, email="phase2@chatbi.local", workspace=None):
    workspace = workspace or Workspace(name=f"Workspace {email}")
    if workspace.id is None:
        db_session.add(workspace); db_session.flush()
    user = AppUser(
        workspace_id=workspace.id, email=email, display_name=email.split("@")[0], role="ADMIN",
        status="ACTIVE", password_hash=hash_password(PASSWORD), password_changed_at=datetime.now(timezone.utc),
    )
    db_session.add(user); db_session.commit()
    return user, workspace


def test_unauthenticated_login_logout_and_invalid_session(raw_client, db_session):
    user, _ = _seed_login(db_session)
    for path in (
        "/api/v1/datasources", "/api/v1/semantic-models", "/api/v1/answers", "/api/v1/dashboards",
        "/api/v1/evaluation/overview", "/api/v1/security/overview", "/api/v1/model-providers",
        "/api/v1/query-capabilities", "/api/v1/conversations", "/api/v1/attachments?conversation_id=missing",
    ):
        assert raw_client.get(path).status_code == 401, path
    assert raw_client.post("/api/v1/ask", json={"question": "统计收入"}).status_code == 401
    assert raw_client.post("/api/v1/analysis", json={"question": "统计收入", "route": "DATA_QUERY"}).status_code == 401
    assert raw_client.post("/api/v1/chat", json={
        "conversation_id": "missing", "client_message_id": "anonymous", "content": "你好",
    }).status_code == 401
    assert raw_client.post("/api/v1/chat/stream", json={
        "conversation_id": "missing", "client_message_id": "anonymous-stream", "content": "你好",
    }).status_code == 401
    invalid = raw_client.get("/api/v1/datasources", headers={"Authorization": "Bearer invalid"})
    assert invalid.status_code == 401
    login = raw_client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD, "remember": False})
    assert login.status_code == 200
    assert login.json()["user"]["id"] == user.id
    cookie = login.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert raw_client.get("/api/v1/datasources").status_code == 200
    assert raw_client.post("/api/v1/auth/logout").status_code == 204
    assert raw_client.get("/api/v1/datasources").status_code == 401
    assert db_session.scalar(select(AuthSession).where(AuthSession.user_id == user.id)).revoked_at is not None


def test_cross_workspace_conversation_and_attachment_access_returns_403(raw_client, db_session):
    first, first_workspace = _seed_login(db_session, email="first@chatbi.local")
    second_workspace = Workspace(name="Second Workspace"); db_session.add(second_workspace); db_session.flush()
    second = AppUser(workspace_id=second_workspace.id, email="second@chatbi.local", display_name="Second", role="ADMIN", status="ACTIVE", password_hash=hash_password(PASSWORD))
    db_session.add(second); db_session.flush()
    foreign = Conversation(workspace_id=second_workspace.id, user_id=second.id, title="Foreign")
    db_session.add(foreign); db_session.flush()
    attachment = Attachment(
        workspace_id=second_workspace.id, user_id=second.id, conversation_id=foreign.id, filename="secret.txt",
        extension=".txt", mime_type="text/plain", kind="DOCUMENT", size_bytes=6, sha256="0" * 64,
        storage_key="foreign.txt", status="READY", extracted_payload={"text": "secret"},
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(attachment); db_session.commit()
    assert raw_client.post("/api/v1/auth/login", json={"email": first.email, "password": PASSWORD, "remember": False}).status_code == 200
    assert raw_client.get(f"/api/v1/conversations/{foreign.id}").status_code == 403
    assert raw_client.get(f"/api/v1/attachments/{attachment.id}").status_code == 403
    assert raw_client.get(f"/api/v1/attachments/{attachment.id}/artifact?format=json").status_code == 403
    stream = raw_client.post("/api/v1/chat/stream", json={
        "conversation_id": foreign.id,
        "client_message_id": "cross-workspace-stream",
        "content": "读取另一个工作区的数据",
    })
    assert stream.status_code == 403
    assert "secret" not in stream.text


def _file_bytes(extension: str) -> tuple[bytes, str]:
    frame = pd.DataFrame({"region": ["华东", "华南"], "revenue": [10, 20]})
    output = io.BytesIO()
    if extension == ".csv": return frame.to_csv(index=False).encode(), "text/csv"
    if extension == ".xls":
        workbook = xlwt.Workbook(); sheet = workbook.add_sheet("data")
        for column_index, name in enumerate(frame.columns): sheet.write(0, column_index, name)
        for row_index, row in enumerate(frame.itertuples(index=False), start=1):
            for column_index, value in enumerate(row): sheet.write(row_index, column_index, value)
        workbook.save(output); return output.getvalue(), "application/vnd.ms-excel"
    if extension == ".xlsx": frame.to_excel(output, index=False); return output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if extension == ".parquet": frame.to_parquet(output, index=False); return output.getvalue(), "application/vnd.apache.parquet"
    if extension == ".pdf": PdfWriter().write(output); return output.getvalue(), "application/pdf"
    if extension == ".docx":
        document = Document(); document.add_paragraph("收入必须经过结果验证。"); document.save(output)
        return output.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if extension == ".txt": return "收入规则".encode(), "text/plain"
    if extension == ".md": return "# 收入规则".encode(), "text/markdown"
    image = Image.new("RGB", (12, 8), color="red"); image.save(output, format={".png": "PNG", ".jpg": "JPEG", ".webp": "WEBP"}[extension])
    return output.getvalue(), {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}[extension]


def test_supported_attachment_formats_and_host_path_is_not_exposed(client, db_session):
    conversation = client.post("/api/v1/conversations", json={"title": "Files"}).json()
    uploaded: list[tuple[str, Path]] = []
    for extension in (".csv", ".xls", ".xlsx", ".parquet", ".pdf", ".docx", ".txt", ".md", ".png", ".jpg", ".webp"):
        data, mime = _file_bytes(extension)
        response = client.post("/api/v1/attachments", data={"conversation_id": conversation["id"]}, files={"file": (f"sample{extension}", data, mime)})
        assert response.status_code == 201, (extension, response.text)
        payload = response.json()
        assert payload["status"] == "READY"
        assert "storage" not in payload and "path" not in payload
        item = db_session.get(Attachment, payload["id"])
        uploaded.append((payload["id"], attachment_path(item)))
    blocked = client.post("/api/v1/attachments", data={"conversation_id": conversation["id"]}, files={"file": ("bad.exe", b"MZ", "application/octet-stream")})
    assert blocked.status_code == 415
    stored_conversation = db_session.get(Conversation, conversation["id"])
    stored_conversation.active_attachment_ids = [uploaded[0][0]]
    db_session.commit()
    assert client.delete(f"/api/v1/attachments/{uploaded[0][0]}").status_code == 204
    db_session.refresh(stored_conversation)
    assert stored_conversation.active_attachment_ids == []
    assert not uploaded[0][1].exists()
    assert client.delete(f"/api/v1/conversations/{conversation['id']}").status_code == 204
    assert all(not path.exists() for _, path in uploaded)


def test_multiturn_slot_inheritance_matches_required_sequence():
    slots, first = extract_slots("今年华东区销售额是多少？")
    assert {"今年", "华东", "销售额"} <= {token for token in ("今年", "华东", "销售额") if token in first}
    slots, second = extract_slots("那华南呢？", slots)
    assert all(value in second for value in ("今年", "销售额", "华南"))
    slots, third = extract_slots("两者相差多少？", slots)
    assert all(value in third for value in ("华东", "华南", "按地区"))
    slots, fourth = extract_slots("按月份画趋势图。", slots)
    assert slots["granularity"] == "按月"
    slots, fifth = extract_slots("哪个月差距最大？", slots)
    assert all(value in fifth for value in ("华东", "华南", "按月"))
    slots, sixth = extract_slots("结合知识库规则解释可能原因。", slots)
    assert slots["include_knowledge"] is True and "销售额" in sixth


class _FakeGateway:
    def classify(self, question, *, history_summary=""):
        return "GENERAL_CHAT"

    def complete(self, **kwargs):
        return ModelReply(content="真实模型测试回答", provider="test-provider", model="test-model")


def test_general_chat_persists_conversation_trace(client, db_session):
    conversation = client.post("/api/v1/conversations", json={"title": "Chat"}).json()
    principal = type("PrincipalStub", (), {
        "workspace_id": db_session.query(Workspace).first().id,
        "user_id": db_session.query(AppUser).filter_by(email="admin@chatbi.local").first().id,
        "email": "admin@chatbi.local", "display_name": "Admin", "role": "ADMIN", "allows": lambda self, _: True,
    })()
    result = ChatService(gateway=_FakeGateway()).execute(
        db_session,
        __import__("app.schemas.chat", fromlist=["ChatRequest"]).ChatRequest(
            conversation_id=conversation["id"], content="你好", client_message_id="client-message-001",
        ),
        principal,
    )
    assert result.assistant_message.content == "真实模型测试回答"
    trace = result.assistant_message.trace_payload
    assert trace["conversation_id"] == conversation["id"]
    assert trace["route"] == "GENERAL_CHAT"
    assert trace["model_provider"] == "test-provider"


def test_model_gateway_auto_fails_over_without_fabricating_an_answer():
    calls = []

    def handler(request: httpx.Request):
        calls.append(str(request.url))
        if "moonshot" in str(request.url):
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "真实备用模型回答"}}]})

    gateway = ModelGateway(Settings(
        kimi_api_key="kimi-test", mimo_api_key="mimo-test", deepseek_api_key="",
        general_model_provider="auto",
    ), transport=httpx.MockTransport(handler))
    reply = gateway.complete(system="system", user="hello")
    assert reply.content == "真实备用模型回答"
    assert reply.provider == "mimo"
    assert len(calls) == 2
