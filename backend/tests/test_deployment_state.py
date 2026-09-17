from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.db.deployment_state import (
    managed_spreadsheet_state,
    metadata_snapshot,
    provider_configuration_state,
    spreadsheet_helper_state,
)
from app.models import AppUser, ProviderRuntimeSetting, ResourceGrant, Workspace, WorkspaceInvitation, WorkspaceSetting


def test_metadata_snapshot_covers_admin_rbac_invite_and_persistence(db_session):
    workspace = Workspace(id="workspace-snapshot", name="Snapshot Workspace")
    user = AppUser(
        id="user-snapshot",
        workspace_id=workspace.id,
        email="snapshot@example.com",
        display_name="Snapshot Admin",
        role="ADMIN",
        status="ACTIVE",
        password_hash="not-part-of-the-snapshot",
    )
    db_session.add_all(
        [
            workspace,
            user,
            ResourceGrant(
                id="grant-snapshot",
                user_id=user.id,
                resource_type="DATASOURCE",
                resource_id="source-snapshot",
                can_read=True,
                can_query=True,
            ),
            WorkspaceSetting(
                workspace_id=workspace.id,
                query_security={"row_limit": 200},
                workspace_config={"locale": "zh-CN"},
                appearance={"theme": "light"},
                version=2,
            ),
            ProviderRuntimeSetting(
                id="provider-snapshot",
                workspace_id=workspace.id,
                provider_id="mimo",
                enabled=True,
                healthy=None,
                priority=1,
                cost_policy="STANDARD",
            ),
            WorkspaceInvitation(
                id="invite-snapshot",
                workspace_id=workspace.id,
                email="invitee@example.com",
                role="ANALYST",
                token_hash="not-part-of-the-snapshot",
                status="PENDING",
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            ),
        ]
    )
    db_session.commit()

    snapshot = metadata_snapshot(db_session, migration_head="20260828_0013")

    assert snapshot["migration_head"] == "20260828_0013"
    assert snapshot["counts"]["workspace"] == 1
    assert snapshot["counts"]["rbac_grant"] == 1
    assert snapshot["counts"]["workspace_setting"] == 1
    assert snapshot["counts"]["provider_runtime_setting"] == 1
    assert snapshot["counts"]["invitation"] == 1
    assert "datasource" in snapshot["counts"]
    assert snapshot["counts"]["datasource_import"] == 0
    assert snapshot["counts"]["excel_datasource"] == 0
    assert len(snapshot["metadata_sha256"]) == 64
    assert snapshot["secrets_included"] is False
    assert managed_spreadsheet_state(db_session) == {
        "datasource_import": 0,
        "excel_datasource": 0,
    }


def test_provider_configuration_state_uses_runtime_toggle_without_live_call(db_session, monkeypatch):
    workspace = Workspace(id="workspace-provider", name="Provider Workspace")
    db_session.add(workspace)
    db_session.add(
        ProviderRuntimeSetting(
            id="provider-runtime",
            workspace_id=workspace.id,
            provider_id="mimo",
            enabled=False,
            healthy=True,
            health_message="OK",
            priority=1,
            cost_policy="STANDARD",
        )
    )
    db_session.commit()
    monkeypatch.setenv("CHATBI_MIMO_API_KEY", "configured-for-test-only")
    get_settings.cache_clear()
    try:
        states = {item["provider"]: item for item in provider_configuration_state(db_session)}
    finally:
        get_settings.cache_clear()

    assert states["mimo"] == {
        "provider": "mimo",
        "configured": True,
        "enabled": False,
        "health": "HEALTHY",
        "reachability": "LAST_RECORDED_SUCCESS",
    }
    assert states["deepseek"]["configured"] is False
    assert states["deepseek"]["reachability"] == "NOT_TESTED"


def test_spreadsheet_helper_state_is_explicitly_unsupported_off_postgres(db_session):
    assert spreadsheet_helper_state(db_session) == {
        "available": False,
        "database": "unsupported",
        "helpers": [],
    }
