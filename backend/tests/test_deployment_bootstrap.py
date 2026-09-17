from sqlalchemy import func, select

from app.core.auth import verify_password
from app.core.config import get_settings
from app.db.deployment_bootstrap import bootstrap_database
from app.models import AppUser, OrchestrationProfile, Workspace


def test_deployment_bootstrap_is_idempotent_without_demo_seed(db_session, monkeypatch):
    monkeypatch.setenv("CHATBI_BOOTSTRAP_ADMIN_PASSWORD", "Admin-deploy-password-123")
    monkeypatch.setenv("CHATBI_BOOTSTRAP_ANALYST_PASSWORD", "Analyst-deploy-password-123")
    get_settings.cache_clear()
    try:
        first = bootstrap_database(db_session)
        second = bootstrap_database(db_session)
    finally:
        get_settings.cache_clear()

    assert first["created_users"] == 2
    assert second["created_users"] == 0
    assert db_session.scalar(select(func.count()).select_from(Workspace)) == 1
    assert db_session.scalar(select(func.count()).select_from(AppUser)) == 2
    assert db_session.scalar(select(func.count()).select_from(OrchestrationProfile)) == 1
    admin = db_session.scalar(select(AppUser).where(AppUser.email == "admin@chatbi.local"))
    assert verify_password("Admin-deploy-password-123", admin.password_hash)
    assert first["demo_seed"] == second["demo_seed"] == "DISABLED"
