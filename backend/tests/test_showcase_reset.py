from pathlib import Path

from app.core.auth import verify_password
from app.models import AppUser, EvaluationCaseResult, EvaluationRun
from app.services.evaluation import evaluation_dashboard
from app.showcase.rebuild_schema import validate_local_showcase_target
from app.showcase.reset import ADMIN_EMAIL, ANALYST_EMAIL, reset_showcase_metadata


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_showcase_reset_reseeds_stable_metadata_and_credentials(db_session) -> None:
    summary = reset_showcase_metadata(
        db_session,
        admin_password="showcase-admin-test",
        analyst_password="showcase-analyst-test",
        sync_catalogs=False,
    )

    assert summary == {
        "users": 2,
        "datasources": 2,
        "semantic_models": 2,
        "verified_answers": 128,
        "dashboards": 18,
        "evaluation_runs": 1,
        "knowledge_documents": 6,
        "datasource_schemas": 0,
        "datasource_tables": 0,
        "datasource_columns": 0,
        "datasource_relationships": 0,
        "business_data_reset": "NOT_NEEDED_READ_ONLY_FROZEN_SEED",
    }
    users = {item.email: item for item in db_session.query(AppUser).all()}
    assert verify_password("showcase-admin-test", users[ADMIN_EMAIL].password_hash)
    assert verify_password("showcase-analyst-test", users[ANALYST_EMAIL].password_hash)
    run = db_session.query(EvaluationRun).one()
    assert run.release_name == "V1.3.0 Golden 50 Showcase Snapshot"
    assert db_session.query(EvaluationCaseResult).count() == 50
    dashboard = evaluation_dashboard(db_session, run.workspace_id)
    assert dashboard["release_gate"]["status"] == "PASS"
    assert all(card["value"] == 1.0 and card["passed"] for card in dashboard["accuracy_cards"])


def test_business_seed_uses_a_frozen_showcase_date() -> None:
    postgres = (PROJECT_ROOT / "database/postgresql/demo_business.sql").read_text(encoding="utf-8")
    mysql = (PROJECT_ROOT / "database/mysql/demo_business.sql").read_text(encoding="utf-8")

    assert "current_date" not in postgres.lower()
    assert "current_date" not in mysql.lower()
    assert "2026-08-17" in postgres
    assert "2026-08-17" in mysql


def test_schema_rebuild_guard_accepts_only_local_development_metadata() -> None:
    validate_local_showcase_target(
        "postgresql+psycopg://chatbi_app@host.docker.internal:5432/chatbi_v2",
        environment="development",
    )

    for database_url, environment in (
        ("postgresql+psycopg://chatbi_app@db.example.com:5432/chatbi_v2", "development"),
        ("postgresql+psycopg://chatbi_app@127.0.0.1:5432/production", "development"),
        ("mysql+pymysql://chatbi_app@127.0.0.1:3306/chatbi_v2", "development"),
        ("postgresql+psycopg://chatbi_app@127.0.0.1:5432/chatbi_v2", "production"),
    ):
        try:
            validate_local_showcase_target(database_url, environment=environment)
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"unsafe showcase schema target was accepted: {database_url}")
