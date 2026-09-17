from sqlalchemy import select

from app.api.routes import system as system_routes
from app.core.access import Principal, get_principal, has_resource_access
from app.core.config import Settings
from app.main import app
from app.model_gateway.configuration import ResolvedProvider
from app.core.auth import verify_password
from app.models import (
    AppUser, AuditEvent, DataSource, ProviderRuntimeSetting, ResourceGrant, Workspace,
    WorkspaceInvitation, WorkspaceSetting,
)
from app.services import admin_settings


def test_settings_are_transactional_persisted_runtime_safe_and_audited(client, db_session):
    baseline = client.get("/api/v1/settings")
    assert baseline.status_code == 200
    original = baseline.json()
    response = client.patch("/api/v1/settings", json={
        "expected_version": original["version"],
        "query_security": {
            **original["query_security"],
            "query_timeout_ms": 12000,
            "max_rows": 123,
            "allowed_schemas": ["demo_business"],
            "blocked_schemas": ["private"],
        },
        "appearance": {
            **original["appearance"],
            "product_name": "Verified ChatBI",
            "primary_color": "#123ABC",
        },
    })
    assert response.status_code == 200
    assert response.json()["version"] == original["version"] + 1
    assert response.json()["query_security"]["max_rows"] == 123
    assert client.get("/api/v1/settings").json()["appearance"]["product_name"] == "Verified ChatBI"
    row = db_session.scalar(select(WorkspaceSetting))
    assert row.query_security["query_timeout_ms"] == 12000
    assert db_session.scalar(select(AuditEvent).where(AuditEvent.action == "UPDATE_SETTINGS")) is not None

    rejected = client.patch("/api/v1/settings", json={
        "query_security": {**response.json()["query_security"], "dangerous_sql_block": False},
    })
    assert rejected.status_code == 422
    assert client.get("/api/v1/settings").json()["version"] == original["version"] + 1


def test_provider_disable_persists_affects_readback_and_never_exposes_secrets(client, db_session):
    catalog = client.get("/api/v1/model-providers")
    assert catalog.status_code == 200
    encoded = catalog.text.lower()
    assert "api_key" not in encoded and "base_url" not in encoded and "credential_env" not in encoded
    response = client.patch("/api/v1/model-providers/mimo", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    persisted = db_session.scalar(select(ProviderRuntimeSetting).where(ProviderRuntimeSetting.provider_id == "mimo"))
    assert persisted is not None and persisted.enabled is False
    assert next(item for item in client.get("/api/v1/model-providers").json()["items"] if item["id"] == "mimo")["enabled"] is False
    assert db_session.scalar(select(AuditEvent).where(AuditEvent.action == "TOGGLE_MODEL")) is not None


def test_provider_catalog_discloses_unrestricted_usage_policy_without_secrets(client, monkeypatch):
    monkeypatch.setattr(
        admin_settings,
        "get_settings",
        lambda: Settings(_env_file=None, provider_usage_unrestricted=True),
    )

    response = client.get("/api/v1/model-providers")

    assert response.status_code == 200
    payload = response.json()
    assert payload["usage_unrestricted"] is True
    assert payload["selection_strategy"] == "capability-health-unrestricted"
    external = {
        item["id"]: item["cost_policy"]
        for item in payload["items"] if item["external_model"]
    }
    assert {external[name] for name in {"mimo", "deepseek", "kimi"}} == {"UNRESTRICTED"}
    assert external["openai-compatible"] == "STANDARD"
    assert "api_key" not in response.text.lower()


def test_provider_enable_persists_without_an_implicit_paid_probe(client, db_session, monkeypatch):
    provider = ResolvedProvider(
        provider_id="mimo",
        display_name="Xiaomi MiMo",
        base_url="https://example.invalid",
        api_key="redacted-test-key",
        model_name="mimo-test",
    )
    monkeypatch.setattr(admin_settings, "configured_providers", lambda _settings: {"mimo": provider})

    def unexpected_probe(*_args, **_kwargs):
        raise AssertionError("enabling a provider must not perform a paid connectivity probe")

    monkeypatch.setattr(admin_settings, "test_provider", unexpected_probe)
    response = client.patch("/api/v1/model-providers/mimo", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["enabled"] is True
    persisted = db_session.scalar(select(ProviderRuntimeSetting).where(ProviderRuntimeSetting.provider_id == "mimo"))
    assert persisted is not None and persisted.enabled is True
    assert db_session.scalar(select(AuditEvent).where(AuditEvent.action == "TEST_MODEL")) is None


def test_first_provider_check_preserves_configured_default_enabled_state(client, db_session, monkeypatch):
    provider = ResolvedProvider(
        provider_id="mimo",
        display_name="Xiaomi MiMo",
        base_url="https://example.invalid",
        api_key="redacted-test-key",
        model_name="mimo-test",
    )
    monkeypatch.setattr(admin_settings, "configured_providers", lambda _settings: {"mimo": provider})
    monkeypatch.setattr(admin_settings.ModelGateway, "probe", lambda *_args, **_kwargs: {
        "provider": "mimo", "model": "mimo-test", "status": "PASS",
    })

    response = client.post("/api/v1/model-providers/mimo/test")

    assert response.status_code == 200
    assert response.json()["enabled"] is True
    persisted = db_session.scalar(select(ProviderRuntimeSetting).where(ProviderRuntimeSetting.provider_id == "mimo"))
    assert persisted is not None and persisted.enabled is True
    assert persisted.healthy is True


def test_provider_check_preserves_an_existing_disabled_state(client, db_session, monkeypatch):
    provider = ResolvedProvider(
        provider_id="mimo",
        display_name="Xiaomi MiMo",
        base_url="https://example.invalid",
        api_key="redacted-test-key",
        model_name="mimo-test",
    )
    workspace = db_session.scalar(select(Workspace))
    db_session.add(ProviderRuntimeSetting(
        workspace_id=workspace.id,
        provider_id="mimo",
        enabled=False,
    ))
    db_session.commit()
    monkeypatch.setattr(admin_settings, "configured_providers", lambda _settings: {"mimo": provider})
    monkeypatch.setattr(admin_settings.ModelGateway, "probe", lambda *_args, **_kwargs: {
        "provider": "mimo", "model": "mimo-test", "status": "PASS",
    })

    response = client.post("/api/v1/model-providers/mimo/test")

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    persisted = db_session.scalar(select(ProviderRuntimeSetting).where(ProviderRuntimeSetting.provider_id == "mimo"))
    assert persisted is not None and persisted.enabled is False
    assert persisted.healthy is True


def test_user_invitation_audit_and_workspace_isolation_controls(client, db_session):
    workspace = db_session.scalar(select(Workspace))
    admin = db_session.scalar(select(AppUser).where(AppUser.role == "ADMIN"))
    analyst = AppUser(workspace_id=workspace.id, email="v131-analyst@chatbi.local", display_name="V131 Analyst", role="ANALYST", status="ACTIVE")
    foreign_workspace = Workspace(name="V131 Foreign")
    db_session.add_all([analyst, foreign_workspace])
    db_session.flush()
    foreign = AppUser(workspace_id=foreign_workspace.id, email="v131-foreign@chatbi.local", display_name="Foreign", role="ANALYST", status="ACTIVE")
    db_session.add(foreign)
    db_session.commit()

    updated = client.patch(f"/api/v1/security/users/{analyst.id}", json={"role": "ADMIN"})
    assert updated.status_code == 200 and updated.json()["role"] == "ADMIN"
    assert client.patch(f"/api/v1/security/users/{admin.id}", json={"role": "ANALYST"}).status_code == 409
    assert client.patch(f"/api/v1/security/users/{foreign.id}", json={"status": "DISABLED"}).status_code == 404

    created = client.post("/api/v1/security/invitations", json={"email": "invitee@example.com", "role": "ANALYST", "expires_in_days": 3})
    assert created.status_code == 201
    invite_url = created.json()["invite_url"]
    assert "/invite/" in invite_url
    invitation = db_session.scalar(select(WorkspaceInvitation).where(WorkspaceInvitation.email == "invitee@example.com"))
    assert invitation is not None and invitation.token_hash not in invite_url
    revoked = client.post(f"/api/v1/security/invitations/{invitation.id}/revoke")
    assert revoked.status_code == 200 and revoked.json()["status"] == "REVOKED"
    page = client.get("/api/v1/security/audit", params={"action": "REVOKE_INVITATION", "page": 1, "page_size": 10})
    assert page.status_code == 200 and page.json()["total"] == 1


def test_admin_can_create_login_ready_member_without_exposing_password(client, db_session):
    payload = {
        "email": "new-member@example.com",
        "display_name": "New Member",
        "role": "ANALYST",
        "password": "member-test-password-2026",
    }
    created = client.post("/api/v1/security/users", json=payload)

    assert created.status_code == 201
    assert created.json()["email"] == payload["email"]
    assert created.json()["role"] == "ANALYST"
    assert "password" not in created.text.lower()
    member = db_session.scalar(select(AppUser).where(AppUser.email == payload["email"]))
    assert member is not None and member.status == "ACTIVE"
    assert verify_password(payload["password"], member.password_hash)
    event = db_session.scalar(select(AuditEvent).where(AuditEvent.action == "CREATE_MEMBER"))
    assert event is not None and "password" not in str(event.details).lower()
    duplicate = client.post("/api/v1/security/users", json=payload)
    assert duplicate.status_code == 409


def test_resource_permission_crud_is_workspace_scoped_and_admin_is_implicit(
    client, db_session, datasource_payload,
):
    workspace = db_session.scalar(select(Workspace))
    admin = db_session.scalar(select(AppUser).where(AppUser.role == "ADMIN"))
    analyst = AppUser(
        workspace_id=workspace.id,
        email="permission-analyst@chatbi.local",
        display_name="Permission Analyst",
        role="ANALYST",
        status="ACTIVE",
    )
    foreign_workspace = Workspace(name="Permission Foreign Workspace")
    db_session.add_all([analyst, foreign_workspace])
    db_session.flush()
    foreign_datasource = DataSource(
        workspace_id=foreign_workspace.id,
        name="Foreign datasource",
        type="postgresql",
        host="localhost",
        port=5432,
        database="foreign",
        username="readonly",
        password_encrypted="test-only",
        status="CONNECTED",
    )
    db_session.add(foreign_datasource)
    db_session.commit()

    datasource_response = client.post("/api/v1/datasources", json={
        **datasource_payload,
        "name": "Permission datasource",
    })
    assert datasource_response.status_code == 201
    datasource = datasource_response.json()
    semantic_response = client.post("/api/v1/semantic-models", json={
        "name": "Permission semantic model",
        "datasource_id": datasource["id"],
    })
    assert semantic_response.status_code == 201
    semantic_model = semantic_response.json()

    overview = client.get("/api/v1/security/overview")
    assert overview.status_code == 200
    resource_keys = {
        (item["resource_type"], item["resource_id"])
        for item in overview.json()["permission_resources"]
    }
    assert resource_keys >= {
        ("DATASOURCE", datasource["id"]),
        ("SEMANTIC_MODEL", semantic_model["id"]),
    }
    assert client.get(
        f"/api/v1/security/users/{analyst.id}/resource-permissions"
    ).json() == []

    datasource_path = (
        f"/api/v1/security/users/{analyst.id}/resource-permissions/"
        f"DATASOURCE/{datasource['id']}"
    )
    created = client.put(datasource_path, json={"can_read": True, "can_query": False})
    assert created.status_code == 200
    assert created.json()["can_read"] is True
    assert created.json()["can_query"] is False
    grant_id = created.json()["id"]

    updated = client.put(datasource_path, json={"can_read": True, "can_query": True})
    assert updated.status_code == 200
    assert updated.json()["id"] == grant_id
    assert updated.json()["can_query"] is True
    assert client.put(
        datasource_path, json={"can_read": False, "can_query": True},
    ).status_code == 422

    model_path = (
        f"/api/v1/security/users/{analyst.id}/resource-permissions/"
        f"SEMANTIC_MODEL/{semantic_model['id']}"
    )
    assert client.put(model_path, json={"can_read": True, "can_query": True}).status_code == 200
    grants = client.get(
        f"/api/v1/security/users/{analyst.id}/resource-permissions"
    )
    assert grants.status_code == 200
    assert {(item["resource_type"], item["can_query"]) for item in grants.json()} == {
        ("DATASOURCE", True),
        ("SEMANTIC_MODEL", True),
    }

    cross_workspace_path = (
        f"/api/v1/security/users/{analyst.id}/resource-permissions/"
        f"DATASOURCE/{foreign_datasource.id}"
    )
    assert client.put(
        cross_workspace_path, json={"can_read": True, "can_query": False},
    ).status_code == 404

    admin_path = (
        f"/api/v1/security/users/{admin.id}/resource-permissions/"
        f"DATASOURCE/{datasource['id']}"
    )
    assert has_resource_access(
        db_session,
        Principal(admin.id, workspace.id, admin.email, admin.display_name, admin.role),
        resource_type="DATASOURCE",
        resource_id=datasource["id"],
        query=True,
    )
    assert client.put(
        admin_path, json={"can_read": True, "can_query": True},
    ).status_code == 409
    assert client.delete(admin_path).status_code == 409
    assert db_session.scalar(select(ResourceGrant).where(ResourceGrant.user_id == admin.id)) is None

    assert client.delete(datasource_path).status_code == 204
    remaining = client.get(
        f"/api/v1/security/users/{analyst.id}/resource-permissions"
    ).json()
    assert [(item["resource_type"], item["resource_id"]) for item in remaining] == [
        ("SEMANTIC_MODEL", semantic_model["id"]),
    ]
    actions = set(db_session.scalars(select(AuditEvent.action)))
    assert {"SET_RESOURCE_PERMISSION", "REVOKE_RESOURCE_PERMISSION"} <= actions


def test_analyst_cannot_call_admin_mutations(client, db_session):
    workspace = db_session.scalar(select(Workspace))
    analyst = AppUser(workspace_id=workspace.id, email="v131-rbac@chatbi.local", display_name="RBAC Analyst", role="ANALYST", status="ACTIVE")
    db_session.add(analyst)
    db_session.commit()
    app.dependency_overrides[get_principal] = lambda: Principal(analyst.id, workspace.id, analyst.email, analyst.display_name, analyst.role)
    try:
        assert client.patch("/api/v1/settings", json={"appearance": {"product_name": "Denied"}}).status_code == 403
        assert client.patch("/api/v1/model-providers/mimo", json={"enabled": False}).status_code == 403
        assert client.post("/api/v1/security/users", json={"email": "denied-user@example.com", "display_name": "Denied", "role": "ANALYST", "password": "denied-password"}).status_code == 403
        assert client.post("/api/v1/security/invitations", json={"email": "denied@example.com", "role": "ANALYST", "expires_in_days": 7}).status_code == 403
        permission_base = f"/api/v1/security/users/{analyst.id}/resource-permissions"
        assert client.get(permission_base).status_code == 403
        assert client.put(
            f"{permission_base}/DATASOURCE/not-authorized",
            json={"can_read": True, "can_query": True},
        ).status_code == 403
        assert client.delete(
            f"{permission_base}/DATASOURCE/not-authorized",
        ).status_code == 403
    finally:
        # client fixture restores all overrides after the test; put its ADMIN override back now.
        admin = db_session.scalar(select(AppUser).where(AppUser.email == "admin@chatbi.local"))
        app.dependency_overrides[get_principal] = lambda: Principal(admin.id, workspace.id, admin.email, admin.display_name, admin.role)
