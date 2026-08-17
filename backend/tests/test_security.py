from sqlalchemy import select

from app.core.auth import hash_password
from app.models import AppUser, AuditEvent, ResourceGrant, Workspace


TEST_PASSWORD = "Valid-Test-Password-42!"


def _create_datasource(client, name: str, dialect: str):
    response = client.post("/api/v1/datasources", json={
        "name": name,
        "type": dialect,
        "host": "localhost",
        "port": 5432 if dialect == "postgresql" else 3306,
        "database": "demo",
        "username": "readonly",
        "password": "safe-test-password",
        "ssl": False,
        "schema": "public" if dialect == "postgresql" else "demo",
    })
    assert response.status_code == 201
    return response.json()


def _seed_users(db_session):
    workspace = Workspace(name="Security Test Workspace")
    db_session.add(workspace)
    db_session.flush()
    admin = AppUser(
        workspace_id=workspace.id, email="security-admin@chatbi.local", display_name="Admin",
        role="ADMIN", status="ACTIVE", password_hash=hash_password(TEST_PASSWORD),
    )
    analyst = AppUser(
        workspace_id=workspace.id, email="security-analyst@chatbi.local", display_name="Analyst",
        role="ANALYST", status="ACTIVE", password_hash=hash_password(TEST_PASSWORD),
    )
    db_session.add_all([admin, analyst])
    db_session.commit()
    return admin, analyst


def _login(client, email: str):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert response.status_code == 200


def test_admin_analyst_resource_access_and_denial_audit(raw_client, db_session):
    admin, analyst = _seed_users(db_session)
    _login(raw_client, admin.email)
    postgres = _create_datasource(raw_client, "Allowed PostgreSQL", "postgresql")
    mysql = _create_datasource(raw_client, "Restricted MySQL", "mysql")
    allowed_model = raw_client.post("/api/v1/semantic-models", json={
        "name": "Allowed Model", "datasource_id": postgres["id"],
    }).json()
    restricted_model = raw_client.post("/api/v1/semantic-models", json={
        "name": "Restricted Model", "datasource_id": mysql["id"],
    }).json()
    db_session.add_all([
        ResourceGrant(user_id=analyst.id, resource_type="DATASOURCE", resource_id=postgres["id"], can_read=True, can_query=True),
        ResourceGrant(user_id=analyst.id, resource_type="SEMANTIC_MODEL", resource_id=allowed_model["id"], can_read=True, can_query=True),
    ])
    db_session.commit()
    assert raw_client.post("/api/v1/auth/logout").status_code == 204
    _login(raw_client, analyst.email)

    visible_sources = raw_client.get("/api/v1/datasources")
    assert visible_sources.status_code == 200
    assert [item["id"] for item in visible_sources.json()] == [postgres["id"]]
    visible_models = raw_client.get("/api/v1/semantic-models")
    assert visible_models.status_code == 200
    assert [item["id"] for item in visible_models.json()] == [allowed_model["id"]]

    assert raw_client.get(f"/api/v1/datasources/{mysql['id']}").status_code == 403
    assert raw_client.get(f"/api/v1/semantic-models/{restricted_model['id']}").status_code == 403
    assert raw_client.get("/api/v1/model-providers").status_code == 403
    assert raw_client.post("/api/v1/ask", json={
        "question": "统计收入", "datasource_id": mysql["id"], "semantic_model_id": restricted_model["id"],
    }).status_code == 403

    assert raw_client.get("/api/v1/answers").status_code == 200
    assert raw_client.post("/api/v1/answers", json={
        "question": "分析师草稿问题", "model_name": "收入", "owner_name": "数据分析组",
        "status": "DRAFT", "accuracy_percent": 0,
    }).status_code == 201
    assert raw_client.post("/api/v1/dashboards", json={
        "name": "分析师看板", "description": "RBAC 回归", "card_count": 0, "is_shared": False,
    }).status_code == 201

    denied = list(db_session.scalars(select(AuditEvent).where(AuditEvent.status == "DENIED")))
    assert len(denied) >= 4
    assert {item.resource_type for item in denied} >= {"DATASOURCE", "SEMANTIC_MODEL", "PERMISSION"}

    assert raw_client.post("/api/v1/auth/logout").status_code == 204
    _login(raw_client, admin.email)
    overview = raw_client.get("/api/v1/security/overview")
    assert overview.status_code == 200
    payload = overview.json()
    assert payload["user_count"] == 2
    assert {item["name"] for item in payload["roles"]} == {"ADMIN", "ANALYST"}
    assert payload["audit_event_count"] >= 4


def test_disabled_and_missing_session_are_rejected_and_audited(raw_client, db_session):
    _, analyst = _seed_users(db_session)
    _login(raw_client, analyst.email)
    analyst.status = "DISABLED"
    db_session.commit()

    assert raw_client.get("/api/v1/datasources").status_code == 403
    raw_client.cookies.clear()
    assert raw_client.get("/api/v1/datasources", headers={"X-ChatBI-Actor": "missing@chatbi.local"}).status_code == 401
    events = list(db_session.scalars(select(AuditEvent).where(AuditEvent.action == "AUTHENTICATE")))
    assert {item.details["reason"] for item in events} == {"USER_DISABLED"}
