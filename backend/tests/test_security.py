from sqlalchemy import select

from app.models import AppUser, AuditEvent, ResourceGrant, Workspace


ANALYST_HEADERS = {"X-ChatBI-Actor": "analyst@chatbi.local"}


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


def _seed_users_and_grants(db_session, datasource_id: str, model_id: str):
    workspace = db_session.scalar(select(Workspace).order_by(Workspace.created_at))
    admin = AppUser(
        workspace_id=workspace.id, email="admin@chatbi.local", display_name="Admin",
        role="ADMIN", status="ACTIVE",
    )
    analyst = AppUser(
        workspace_id=workspace.id, email="analyst@chatbi.local", display_name="Analyst",
        role="ANALYST", status="ACTIVE",
    )
    db_session.add_all([admin, analyst])
    db_session.flush()
    db_session.add_all([
        ResourceGrant(user_id=analyst.id, resource_type="DATASOURCE", resource_id=datasource_id, can_read=True, can_query=True),
        ResourceGrant(user_id=analyst.id, resource_type="SEMANTIC_MODEL", resource_id=model_id, can_read=True, can_query=True),
    ])
    db_session.commit()


def test_admin_analyst_resource_access_and_denial_audit(client, db_session):
    postgres = _create_datasource(client, "Allowed PostgreSQL", "postgresql")
    mysql = _create_datasource(client, "Restricted MySQL", "mysql")
    allowed_model = client.post("/api/v1/semantic-models", json={
        "name": "Allowed Model", "datasource_id": postgres["id"],
    }).json()
    restricted_model = client.post("/api/v1/semantic-models", json={
        "name": "Restricted Model", "datasource_id": mysql["id"],
    }).json()
    _seed_users_and_grants(db_session, postgres["id"], allowed_model["id"])

    visible_sources = client.get("/api/v1/datasources", headers=ANALYST_HEADERS)
    assert visible_sources.status_code == 200
    assert [item["id"] for item in visible_sources.json()] == [postgres["id"]]
    visible_models = client.get("/api/v1/semantic-models", headers=ANALYST_HEADERS)
    assert visible_models.status_code == 200
    assert [item["id"] for item in visible_models.json()] == [allowed_model["id"]]

    datasource_denial = client.get(f"/api/v1/datasources/{mysql['id']}", headers=ANALYST_HEADERS)
    semantic_denial = client.get(f"/api/v1/semantic-models/{restricted_model['id']}", headers=ANALYST_HEADERS)
    settings_denial = client.get("/api/v1/model-providers", headers=ANALYST_HEADERS)
    query_denial = client.post("/api/v1/ask", headers=ANALYST_HEADERS, json={
        "question": "统计收入", "datasource_id": mysql["id"], "semantic_model_id": restricted_model["id"],
    })
    assert datasource_denial.status_code == 403
    assert semantic_denial.status_code == 403
    assert settings_denial.status_code == 403
    assert query_denial.status_code == 403

    assert client.get("/api/v1/answers", headers=ANALYST_HEADERS).status_code == 200
    created_answer = client.post("/api/v1/answers", headers=ANALYST_HEADERS, json={
        "question": "分析师草稿问题", "model_name": "收入", "owner_name": "数据分析组",
        "status": "DRAFT", "accuracy_percent": 0,
    })
    assert created_answer.status_code == 201
    assert client.get("/api/v1/dashboards", headers=ANALYST_HEADERS).status_code == 200
    created_dashboard = client.post("/api/v1/dashboards", headers=ANALYST_HEADERS, json={
        "name": "分析师看板", "description": "RBAC 回归", "card_count": 0, "is_shared": False,
    })
    assert created_dashboard.status_code == 201

    denied = list(db_session.scalars(select(AuditEvent).where(AuditEvent.status == "DENIED")))
    assert len(denied) >= 4
    assert {item.resource_type for item in denied} >= {"DATASOURCE", "SEMANTIC_MODEL", "PERMISSION"}

    overview = client.get("/api/v1/security/overview")
    assert overview.status_code == 200
    payload = overview.json()
    assert payload["user_count"] == 2
    assert {item["name"] for item in payload["roles"]} == {"ADMIN", "ANALYST"}
    assert payload["audit_event_count"] >= 4
    successful_actions = list(db_session.scalars(select(AuditEvent).where(AuditEvent.status == "SUCCESS")))
    assert {(item.action, item.resource_type) for item in successful_actions} >= {
        ("CREATE", "ANSWER"), ("CREATE", "DASHBOARD"),
    }


def test_disabled_and_unknown_actor_are_rejected_and_audited(client, db_session):
    postgres = _create_datasource(client, "PostgreSQL", "postgresql")
    model = client.post("/api/v1/semantic-models", json={"name": "Model", "datasource_id": postgres["id"]}).json()
    _seed_users_and_grants(db_session, postgres["id"], model["id"])
    analyst = db_session.scalar(select(AppUser).where(AppUser.email == "analyst@chatbi.local"))
    analyst.status = "DISABLED"
    db_session.commit()

    assert client.get("/api/v1/datasources", headers=ANALYST_HEADERS).status_code == 403
    assert client.get("/api/v1/datasources", headers={"X-ChatBI-Actor": "missing@chatbi.local"}).status_code == 401
    events = list(db_session.scalars(select(AuditEvent).where(AuditEvent.action == "AUTHENTICATE")))
    assert {item.details["reason"] for item in events} == {"USER_DISABLED", "UNKNOWN_ACTOR"}
