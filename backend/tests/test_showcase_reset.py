from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.auth import verify_password
from app.models import AppUser, EvaluationCaseResult, EvaluationRun
from app.services.evaluation import _next_trend_points, demo_evaluation_trend, evaluation_dashboard
from app.services.seed import seed_demo_semantic_model
from app.showcase.rebuild_schema import validate_local_showcase_target
from app.showcase.reset import ADMIN_EMAIL, ANALYST_EMAIL, reset_showcase_metadata


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_first_real_evaluation_does_not_invent_historical_trend() -> None:
    completed_at = datetime(2026, 8, 29, 8, 30, tzinfo=timezone.utc)
    assert _next_trend_points(None, completed_at=completed_at, latest_value=98.5) == [
        {"date": "08/29 08:30", "value": 98.5},
    ]


def test_first_real_evaluation_does_not_inherit_showcase_demo_history() -> None:
    completed_at = datetime(2026, 8, 29, 12, 30, tzinfo=timezone.utc)
    previous = EvaluationRun(
        workspace_id="workspace-a",
        release_name="V1.3.0 Golden 50 Showcase Snapshot",
        model_name="deterministic",
        trend_points=demo_evaluation_trend(completed_at - timedelta(days=1)),
    )
    assert _next_trend_points(previous, completed_at=completed_at, latest_value=98.5) == [
        {"date": "08/29 12:30", "value": 98.5},
    ]


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
    public_trend = [point for point in run.trend_points if point.get("kind") != "evaluation_profile"]
    assert len(public_trend) == 30
    assert public_trend[0] == {"date": "07/29", "value": 87.8, "source": "SHOWCASE_DEMO"}
    assert public_trend[-1] == {"date": "08/27", "value": 100.0, "source": "SHOWCASE_DEMO"}
    assert db_session.query(EvaluationCaseResult).count() == 50
    dashboard = evaluation_dashboard(db_session, run.workspace_id)
    assert dashboard["release_gate"]["status"] == "PASS"
    assert all(card["value"] == 1.0 and card["passed"] for card in dashboard["accuracy_cards"])

    run.trend_points = [{"date": "08/17", "value": 100}]
    db_session.commit()
    seed_demo_semantic_model(db_session)
    db_session.refresh(run)
    upgraded_trend = [point for point in run.trend_points if point.get("kind") != "evaluation_profile"]
    assert len(upgraded_trend) == 30


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
    validate_local_showcase_target(
        "postgresql+psycopg://chatbi_app@host.docker.internal:5432/chatbi_v2?options=-csearch_path%3Dchatbi_v131_integration",
        environment="development",
        expected_schema="chatbi_v131_integration",
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

    for unsafe_name in ("postgres", "chatbi_v2-unsafe", "chatbi_v2/unsafe"):
        try:
            validate_local_showcase_target(
                "postgresql+psycopg://chatbi_app@127.0.0.1:5432/chatbi_v2",
                environment="development",
                expected_database=unsafe_name,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"unsafe showcase database name was accepted: {unsafe_name}")

    for unsafe_schema in ("private", "chatbi-v131", "public;drop schema public"):
        try:
            validate_local_showcase_target(
                "postgresql+psycopg://chatbi_app@127.0.0.1:5432/chatbi_v2",
                environment="development",
                expected_schema=unsafe_schema,
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"unsafe showcase schema name was accepted: {unsafe_schema}")
