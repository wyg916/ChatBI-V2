from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import AppUser, AuditEvent, ChatMessage, Conversation, ConversationShare, Project, Workspace


def _create_conversation(client, title: str) -> dict:
    response = client.post("/api/v1/conversations", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


def test_conversation_project_pin_archive_search_batch_and_audit(client, db_session):
    first = _create_conversation(client, "Revenue 100% 华东")
    second = _create_conversation(client, "利润趋势")
    third = _create_conversation(client, "待删除会话")

    search = client.get("/api/v1/conversations", params={"q": "100%"})
    assert search.status_code == 200
    assert [item["id"] for item in search.json()] == [first["id"]]

    pinned = client.post(f"/api/v1/conversations/{second['id']}/pin")
    assert pinned.status_code == 200 and pinned.json()["pinned_at"]
    ordered = client.get("/api/v1/conversations").json()
    assert ordered[0]["id"] == second["id"]
    assert client.post(f"/api/v1/conversations/{second['id']}/unpin").json()["pinned_at"] is None

    archived = client.post(f"/api/v1/conversations/{first['id']}/archive")
    assert archived.status_code == 200 and archived.json()["archived_at"]
    assert first["id"] not in {item["id"] for item in client.get("/api/v1/conversations").json()}
    assert first["id"] in {item["id"] for item in client.get("/api/v1/conversations", params={"state": "archived"}).json()}
    assert client.post(f"/api/v1/conversations/{first['id']}/pin").status_code == 409
    archived_chat = client.post("/api/v1/chat", json={
        "conversation_id": first["id"],
        "content": "归档后不应继续写入",
        "client_message_id": "phase4-archived-write",
    })
    assert archived_chat.status_code == 409
    assert client.post(f"/api/v1/conversations/{first['id']}/restore").json()["archived_at"] is None

    project_response = client.post("/api/v1/projects", json={"name": "经营分析", "description": "月度经营会话"})
    assert project_response.status_code == 201, project_response.text
    project = project_response.json()
    assert client.post("/api/v1/projects", json={"name": "经营分析"}).status_code == 409
    moved = client.put(f"/api/v1/conversations/{first['id']}/project", json={"project_id": project["id"]})
    assert moved.status_code == 200 and moved.json()["project_id"] == project["id"]
    project_search = client.get(f"/api/v1/projects/{project['id']}/conversations", params={"q": "Revenue"})
    assert [item["id"] for item in project_search.json()] == [first["id"]]
    removed = client.delete(f"/api/v1/conversations/{first['id']}/project")
    assert removed.status_code == 200 and removed.json()["project_id"] is None
    archived_project = client.post(f"/api/v1/projects/{project['id']}/archive")
    assert archived_project.json()["archived_at"]
    assert client.put(f"/api/v1/conversations/{first['id']}/project", json={"project_id": project["id"]}).status_code == 409
    assert client.post(f"/api/v1/projects/{project['id']}/restore").json()["archived_at"] is None

    batch_archive = client.post("/api/v1/conversations/batch/archive", json={
        "conversation_ids": [first["id"], second["id"]],
    })
    assert batch_archive.status_code == 200
    assert batch_archive.json()["affected_count"] == 2
    db_session.expire_all()
    assert db_session.get(Conversation, first["id"]).archived_at is not None
    assert db_session.get(Conversation, second["id"]).archived_at is not None

    batch_delete = client.post("/api/v1/conversations/batch/delete", json={"conversation_ids": [third["id"]]})
    assert batch_delete.status_code == 200 and batch_delete.json()["affected_count"] == 1
    db_session.expire_all()
    assert db_session.get(Conversation, third["id"]) is None

    actions = set(db_session.scalars(select(AuditEvent.action)))
    assert {
        "CONVERSATION_CREATE", "CONVERSATION_SEARCH", "CONVERSATION_PIN", "CONVERSATION_UNPIN",
        "CONVERSATION_ARCHIVE", "CONVERSATION_RESTORE", "PROJECT_CREATE", "CONVERSATION_PROJECT_BIND",
        "CONVERSATION_PROJECT_REMOVE", "PROJECT_ARCHIVE", "PROJECT_RESTORE",
        "CONVERSATION_BATCH_ARCHIVE", "CONVERSATION_BATCH_DELETE",
    } <= actions


def test_project_conversation_and_batch_actions_are_user_and_workspace_isolated(client, db_session):
    own = _create_conversation(client, "Own")
    workspace = db_session.scalar(select(Workspace))
    owner = db_session.scalar(select(AppUser).where(AppUser.workspace_id == workspace.id))
    same_workspace_user = AppUser(
        workspace_id=workspace.id, email="same-workspace@chatbi.local", display_name="Same Workspace",
        role="ANALYST", status="ACTIVE",
    )
    foreign_workspace = Workspace(name="Foreign governance workspace")
    db_session.add_all([same_workspace_user, foreign_workspace]); db_session.flush()
    foreign_user = AppUser(
        workspace_id=foreign_workspace.id, email="foreign-governance@chatbi.local", display_name="Foreign",
        role="ADMIN", status="ACTIVE",
    )
    db_session.add(foreign_user); db_session.flush()
    same_user_conversation = Conversation(workspace_id=workspace.id, user_id=same_workspace_user.id, title="Same workspace secret")
    foreign_conversation = Conversation(workspace_id=foreign_workspace.id, user_id=foreign_user.id, title="Foreign secret")
    same_user_project = Project(workspace_id=workspace.id, user_id=same_workspace_user.id, name="Other user's project")
    db_session.add_all([same_user_conversation, foreign_conversation, same_user_project]); db_session.commit()

    for conversation in (same_user_conversation, foreign_conversation):
        assert client.post(f"/api/v1/conversations/{conversation.id}/archive").status_code == 403
        assert client.put(
            f"/api/v1/conversations/{own['id']}/project", json={"project_id": same_user_project.id},
        ).status_code == 403
        denied = client.post("/api/v1/conversations/batch/archive", json={
            "conversation_ids": [own["id"], conversation.id],
        })
        assert denied.status_code == 403
        db_session.expire_all()
        assert db_session.get(Conversation, own["id"]).archived_at is None

    assert owner.id != same_workspace_user.id


def test_controlled_share_is_hashed_expiring_revocable_read_only_and_redacted(client, db_session):
    conversation = _create_conversation(client, "共享经营结论")
    stored = db_session.get(Conversation, conversation["id"])
    owner = db_session.scalar(select(AppUser).where(AppUser.id == stored.user_id))
    user_message = ChatMessage(
        conversation_id=stored.id, workspace_id=stored.workspace_id, user_id=owner.id,
        role="user", content="请读取 https://internal.local/attachments/private/artifact?token=raw",
        status="COMPLETED", attachment_ids=["private-attachment"], context_payload={"password": "db-password"},
        response_payload={}, trace_payload={"hidden_prompt": "never expose"},
    )
    db_session.add(user_message); db_session.flush()
    assistant = ChatMessage(
        conversation_id=stored.id, workspace_id=stored.workspace_id, user_id=owner.id,
        parent_message_id=user_message.id, role="assistant", content="password=hunter2 结论可共享",
        status="SUCCEEDED", attachment_ids=["private-attachment"], context_payload={"api_key": "secret"},
        trace_payload={"reasoning_content": "private chain of thought"},
        response_payload={"message_parts": [
            {"type": "text", "text": "Authorization: Bearer-secret 正常结论", "role": "conclusion"},
            {"type": "table", "columns": ["region", "password"], "rows": [{"region": "华东", "password": "hidden"}], "row_count": 1, "result_signature": "sig"},
            {"type": "citations", "items": [{"title": "规则", "version": "v1", "locator": "javascript:alert(1)", "resource_id": "private-id"}]},
            {"type": "evidence", "sql": "SELECT secret FROM credentials", "guard": {}, "oracle": {}, "semantic": {}, "phases": []},
        ]},
    )
    db_session.add(assistant); db_session.commit()

    created = client.post(f"/api/v1/conversations/{stored.id}/shares", json={"expires_in_hours": 1})
    assert created.status_code == 201, created.text
    share = created.json()
    raw_token = share["token"]
    stored_share = db_session.get(ConversationShare, share["id"])
    assert raw_token not in stored_share.token_hash
    assert len(stored_share.token_hash) == 64
    listed_text = client.get(f"/api/v1/conversations/{stored.id}/shares").text
    assert raw_token not in listed_text

    public = client.get(share["share_path"].replace("/share/", "/api/v1/shared-conversations/"))
    assert public.status_code == 200, public.text
    payload = public.json()
    assert payload["read_only"] is True
    serialized = public.text.lower()
    for forbidden in (
        "hunter2", "db-password", "bearer-secret", "private chain of thought", "hidden_prompt",
        "trace_payload", "private-attachment", "select secret", "javascript:", "resource_id", "api_key",
    ):
        assert forbidden not in serialized
    assert "华东" in public.text and "正常结论" in public.text
    assert client.post(share["share_path"].replace("/share/", "/api/v1/shared-conversations/")).status_code == 405

    revoked = client.post(f"/api/v1/conversation-shares/{share['id']}/revoke")
    assert revoked.status_code == 200 and revoked.json()["revoked_at"]
    assert client.get(share["share_path"].replace("/share/", "/api/v1/shared-conversations/")).status_code == 410

    second = client.post(f"/api/v1/conversations/{stored.id}/shares", json={"expires_in_hours": 1}).json()
    expiring = db_session.get(ConversationShare, second["id"])
    expiring.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert client.get(second["share_path"].replace("/share/", "/api/v1/shared-conversations/")).status_code == 410

    actions = set(db_session.scalars(select(AuditEvent.action)))
    assert {"CONVERSATION_SHARE_CREATE", "CONVERSATION_SHARE_LIST", "CONVERSATION_SHARE_ACCESS", "CONVERSATION_SHARE_REVOKE"} <= actions
