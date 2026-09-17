from __future__ import annotations

from app.core.access import Principal, get_principal
from app.models import AppUser, QueryRun, ResourceGrant, Workspace
from app.main import app


def _datasource_and_model(client) -> tuple[str, str]:
    datasource = client.post("/api/v1/datasources", json={
        "name": "QueryRun access source",
        "type": "postgresql",
        "host": "localhost",
        "port": 5432,
        "database": "demo",
        "username": "readonly",
        "password": "test-only-password",
        "ssl": False,
        "schema": "public",
    })
    assert datasource.status_code == 201, datasource.text
    model = client.post("/api/v1/semantic-models", json={
        "name": "QueryRun access model",
        "datasource_id": datasource.json()["id"],
    })
    assert model.status_code == 201, model.text
    return datasource.json()["id"], model.json()["id"]


def _principal(user: AppUser) -> Principal:
    return Principal(user.id, user.workspace_id, user.email, user.display_name, user.role)


def _assert_query_run_endpoints_denied(client, run_id: str) -> None:
    requests = (
        ("get", f"/api/v1/queries/{run_id}", None),
        ("post", f"/api/v1/queries/{run_id}/verify", {
            "expected": {"columns": [], "rows": []},
        }),
        ("post", f"/api/v1/queries/{run_id}/feedback", {
            "feedback_type": "HELPFUL",
        }),
        ("post", f"/api/v1/queries/{run_id}/save", {
            "owner_name": "Denied analyst",
            "status": "DRAFT",
        }),
    )
    for method, path, payload in requests:
        response = getattr(client, method)(path, json=payload) if payload is not None else getattr(client, method)(path)
        assert response.status_code == 403, (method, path, response.text)


def test_query_run_follow_up_requires_query_grants_and_owner(client, db_session):
    workspace = db_session.query(Workspace).first()
    datasource_id, semantic_model_id = _datasource_and_model(client)
    owner = AppUser(
        workspace_id=workspace.id,
        email="query-owner@chatbi.local",
        display_name="Query Owner",
        role="ANALYST",
        status="ACTIVE",
    )
    analyst = AppUser(
        workspace_id=workspace.id,
        email="query-reader@chatbi.local",
        display_name="Query Reader",
        role="ANALYST",
        status="ACTIVE",
    )
    db_session.add_all([owner, analyst])
    db_session.flush()
    grants = [
        ResourceGrant(
            user_id=analyst.id,
            resource_type=kind,
            resource_id=resource_id,
            can_read=True,
            can_query=True,
        )
        for kind, resource_id in (
            ("DATASOURCE", datasource_id),
            ("SEMANTIC_MODEL", semantic_model_id),
        )
    ]
    db_session.add_all(grants)
    run = QueryRun(
        workspace_id=workspace.id,
        datasource_id=datasource_id,
        semantic_model_id=semantic_model_id,
        semantic_model_version=1,
        question="private query",
        status="SUCCEEDED",
        provider="deterministic",
        context_payload={"request_context": {"user_id": owner.id}},
        oracle_payload={"status": "PASSED"},
    )
    db_session.add(run)
    db_session.commit()

    app.dependency_overrides[get_principal] = lambda: _principal(analyst)
    _assert_query_run_endpoints_denied(client, run.id)

    run.context_payload = {"request_context": {"user_id": analyst.id}}
    for grant in grants:
        grant.can_query = False
    db_session.commit()
    _assert_query_run_endpoints_denied(client, run.id)

    for grant in grants:
        grant.can_query = True
    db_session.commit()
    allowed = client.get(f"/api/v1/queries/{run.id}")
    assert allowed.status_code == 200, allowed.text
