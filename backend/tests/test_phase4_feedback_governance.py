from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.access import Principal
from app.models import (
    AnswerVersion,
    AppUser,
    DataSource,
    QueryRun,
    SemanticModel,
    VerifiedAnswer,
    Workspace,
)
from app.schemas.evaluation import (
    FeedbackDecisionRequest,
    FeedbackReviewStartRequest,
    UserFeedbackCreate,
)
from app.services.feedback_loop import (
    PHASE4_FLOW_ID,
    decide_feedback_review,
    feedback_dashboard,
    record_user_feedback,
    start_feedback_review,
)


def _source_run(db: Session) -> tuple[QueryRun, Principal]:
    workspace = Workspace(name="Phase 4 Feedback")
    db.add(workspace)
    db.flush()
    user = AppUser(
        workspace_id=workspace.id,
        email="phase4-reviewer@chatbi.local",
        display_name="Phase 4 Reviewer",
        role="ADMIN",
        status="ACTIVE",
    )
    datasource = DataSource(
        workspace_id=workspace.id,
        name="Feedback readonly PostgreSQL",
        type="postgresql",
        host="127.0.0.1",
        port=5432,
        database="chatbi_test",
        username="readonly",
        password_encrypted="encrypted-fixture",
    )
    db.add_all([user, datasource])
    db.flush()
    model = SemanticModel(
        workspace_id=workspace.id,
        datasource_id=datasource.id,
        name="Feedback semantic",
        status="PUBLISHED",
        version=4,
    )
    db.add(model)
    db.flush()
    run = QueryRun(
        workspace_id=workspace.id,
        datasource_id=datasource.id,
        semantic_model_id=model.id,
        semantic_model_version=model.version,
        question="按地区统计收入",
        status="SUCCEEDED",
        provider="deepseek",
        plan_payload={"intent": "aggregate", "metrics": ["revenue"], "dimensions": ["region"]},
        guard_payload={"allowed": True},
        execution_payload={
            "status": "SUCCEEDED",
            "columns": ["region", "revenue"],
            "rows": [{"region": "华东", "revenue": 100}],
        },
        oracle_payload={"status": "PASSED", "confidence": 1},
        generated_sql="SELECT region, SUM(revenue) AS revenue FROM sales GROUP BY region",
        normalized_sql="SELECT region, SUM(revenue) AS revenue FROM sales GROUP BY region",
        result_signature="b" * 64,
    )
    db.add(run)
    db.commit()
    return run, Principal(user.id, workspace.id, user.email, user.display_name, user.role)


def test_feedback_review_exact_states_preserve_versions_and_dashboard(db_session: Session):
    source, principal = _source_run(db_session)
    opened = record_user_feedback(
        db_session,
        data=UserFeedbackCreate(
            query_run_id=source.id,
            sentiment="THUMB_DOWN",
            reason="INCORRECT_RESULT",
            comment="收入口径不正确",
        ),
        principal=principal,
    )
    assert opened["workflow_state"] == "OPEN"
    assert opened["status"] == "DRAFT"
    assert opened["feedback"]["flow"] == PHASE4_FLOW_ID
    assert db_session.get(VerifiedAnswer, opened["answer_id"]).sql_text is None

    reviewing = start_feedback_review(
        db_session,
        answer_id=opened["answer_id"],
        data=FeedbackReviewStartRequest(comment="由评测负责人复核"),
        principal=principal,
    )
    assert reviewing["workflow_state"] == "IN_REVIEW"
    assert reviewing["reviewer"] == principal.email
    assert reviewing["version"] == 2

    rejected = decide_feedback_review(
        db_session,
        answer_id=opened["answer_id"],
        data=FeedbackDecisionRequest(
            decision="REJECT",
            comment="缺少可重现的正确结果",
        ),
        principal=principal,
    )
    assert rejected["workflow_state"] == "REJECTED"
    assert rejected["status"] == "REJECTED"
    assert rejected["version"] == 3
    assert db_session.scalar(select(func.count()).select_from(AnswerVersion).where(
        AnswerVersion.answer_id == opened["answer_id"],
    )) == 3
    dashboard = feedback_dashboard(db_session, workspace_id=principal.workspace_id)
    assert dashboard["workflows"][0]["workflow_state"] == "REJECTED"


def test_thumb_down_requires_reason_and_review_assignment_is_enforced(db_session: Session):
    source, principal = _source_run(db_session)
    try:
        record_user_feedback(
            db_session,
            data=UserFeedbackCreate(query_run_id=source.id, sentiment="THUMB_DOWN"),
            principal=principal,
        )
    except ValueError as exc:
        assert "requires a reason" in str(exc)
    else:
        raise AssertionError("Thumb down without a reason must fail")

    opened = record_user_feedback(
        db_session,
        data=UserFeedbackCreate(
            query_run_id=source.id,
            sentiment="THUMB_DOWN",
            reason="INCORRECT_SQL",
        ),
        principal=principal,
    )
    start_feedback_review(
        db_session,
        answer_id=opened["answer_id"],
        data=FeedbackReviewStartRequest(),
        principal=principal,
    )
    other = Principal("other-user", principal.workspace_id, "other@chatbi.local", "Other", "ADMIN")
    try:
        decide_feedback_review(
            db_session,
            answer_id=opened["answer_id"],
            data=FeedbackDecisionRequest(decision="REJECT", comment="拒绝"),
            principal=other,
        )
    except ValueError as exc:
        assert "another reviewer" in str(exc)
    else:
        raise AssertionError("A different reviewer must not decide an assigned item")
