from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.access import Principal, get_principal
from app.main import app
from app.models import (
    AppUser,
    DataSource,
    DataSourceColumn,
    DataSourceSchema,
    DataSourceTable,
    QueryRun,
    ResourceGrant,
    SemanticModel,
    VerifiedAnswer,
    Workspace,
)
from app.services.feedback_loop import FLOW_ID, PHASE4_FLOW_ID, feedback_dashboard


def _scope(db: Session) -> tuple[Principal, Principal, DataSource, SemanticModel]:
    workspace = db.query(Workspace).filter_by(name="Test Workspace").one()
    admin = db.query(AppUser).filter_by(email="admin@chatbi.local").one()
    analyst = AppUser(
        workspace_id=workspace.id,
        email="feedback-analyst@chatbi.local",
        display_name="Feedback Analyst",
        role="ANALYST",
        status="ACTIVE",
    )
    datasource = DataSource(
        workspace_id=workspace.id,
        name="Feedback RBAC source",
        type="postgresql",
        host="127.0.0.1",
        port=5432,
        database="chatbi_test",
        username="readonly",
        password_encrypted="encrypted-test-placeholder",
        status="SYNCED",
    )
    db.add_all([analyst, datasource])
    db.flush()
    model = SemanticModel(
        workspace_id=workspace.id,
        datasource_id=datasource.id,
        name="Feedback RBAC model",
        status="PUBLISHED",
        version=1,
    )
    schema = DataSourceSchema(
        datasource_id=datasource.id,
        name="public",
        qualified_name=f"{datasource.id}.public",
    )
    db.add_all([model, schema])
    db.flush()
    table = DataSourceTable(
        schema_id=schema.id,
        name="customers",
        qualified_name=f"{schema.qualified_name}.customers",
    )
    db.add(table)
    db.flush()
    db.add(DataSourceColumn(
        table_id=table.id,
        name="email",
        qualified_name=f"{table.qualified_name}.email",
        data_type="TEXT",
        nullable=False,
        comment="[SENSITIVE_SOURCE] customer email",
    ))
    db.commit()
    return (
        Principal(admin.id, workspace.id, admin.email, admin.display_name, admin.role),
        Principal(analyst.id, workspace.id, analyst.email, analyst.display_name, analyst.role),
        datasource,
        model,
    )


def _grant(
    db: Session,
    principal: Principal,
    resource_type: str,
    resource_id: str,
    *,
    can_read: bool = True,
    can_query: bool = True,
) -> ResourceGrant:
    grant = ResourceGrant(
        user_id=principal.user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        can_read=can_read,
        can_query=can_query,
    )
    db.add(grant)
    db.commit()
    return grant


def _source_run(
    db: Session,
    principal: Principal,
    datasource: DataSource,
    model: SemanticModel,
    *,
    owner_id: str | None = None,
) -> QueryRun:
    run = QueryRun(
        workspace_id=principal.workspace_id,
        datasource_id=datasource.id,
        semantic_model_id=model.id,
        semantic_model_version=model.version,
        question="经营分析客户邮箱",
        status="SUCCEEDED",
        provider="deepseek",
        context_payload={
            "request_context": {"user_id": owner_id or principal.user_id},
        },
        guard_payload={"allowed": True},
        execution_payload={"status": "SUCCEEDED", "columns": ["count"], "rows": [{"count": 1}]},
        oracle_payload={"status": "PASSED", "confidence": 1},
        generated_sql="SELECT COUNT(*) AS count FROM customers",
        normalized_sql="SELECT COUNT(*) AS count FROM customers",
        result_signature="a" * 64,
    )
    db.add(run)
    db.commit()
    return run


def _answer(
    db: Session,
    principal: Principal,
    datasource: DataSource,
    model: SemanticModel,
    *,
    flow: str,
    workflow_state: str,
    status: str = "DRAFT",
) -> VerifiedAnswer:
    sql = "SELECT email FROM customers WHERE email='private@example.com'"
    answer = VerifiedAnswer(
        workspace_id=principal.workspace_id,
        question="经营分析客户邮箱",
        module="评测反馈",
        model_name="Feedback RBAC model",
        owner_name="Feedback Analyst",
        status=status,
        accuracy_percent=100,
        sql_text=sql if status == "VERIFIED" else None,
        semantic_model_id=model.id,
        datasource_id=datasource.id,
        semantic_model_version=model.version,
        oracle_status="PASSED",
        result_signature="b" * 64,
        feedback={
            "flow": flow,
            "workflow_state": workflow_state,
            "corrected_sql": sql,
            "candidate_sql": sql,
            "error_text": "driver leaked private@example.com",
            "review_history": [],
            "replays": [{"passed": True}],
        },
    )
    db.add(answer)
    db.commit()
    return answer


def test_query_run_feedback_requires_query_grants_and_original_owner(
    client,
    db_session: Session,
) -> None:
    _, analyst, datasource, model = _scope(db_session)
    run = _source_run(db_session, analyst, datasource, model)
    _grant(db_session, analyst, "DATASOURCE", datasource.id)
    model_grant = _grant(
        db_session, analyst, "SEMANTIC_MODEL", model.id, can_query=False,
    )
    app.dependency_overrides[get_principal] = lambda: analyst

    read_only = client.post(
        "/api/v1/evaluation/feedback/correct",
        json={"query_run_id": run.id, "comment": "read-only must fail"},
    )
    assert read_only.status_code == 403

    model_grant.can_query = True
    run.context_payload = {"request_context": {"user_id": "another-user"}}
    db_session.commit()
    owner_mismatch = client.post(
        "/api/v1/evaluation/feedback/correct",
        json={"query_run_id": run.id, "comment": "foreign run must fail"},
    )
    assert owner_mismatch.status_code == 403

    run.context_payload = {"request_context": {"user_id": analyst.user_id}}
    db_session.commit()
    allowed = client.post(
        "/api/v1/evaluation/feedback/correct",
        json={"query_run_id": run.id, "comment": "owned and granted"},
    )
    assert allowed.status_code == 201


def test_answer_feedback_actions_require_answer_and_bound_query_access(
    client,
    db_session: Session,
) -> None:
    _, analyst, datasource, model = _scope(db_session)
    _grant(db_session, analyst, "DATASOURCE", datasource.id)
    model_grant = _grant(db_session, analyst, "SEMANTIC_MODEL", model.id)
    open_answer = _answer(
        db_session,
        analyst,
        datasource,
        model,
        flow=PHASE4_FLOW_ID,
        workflow_state="OPEN",
    )
    app.dependency_overrides[get_principal] = lambda: analyst

    no_answer_grant = client.post(
        f"/api/v1/evaluation/feedback/{open_answer.id}/review/start",
        json={},
    )
    assert no_answer_grant.status_code == 403

    answer_grant = _grant(
        db_session, analyst, "ANSWER", open_answer.id, can_query=False,
    )
    read_only_answer = client.post(
        f"/api/v1/evaluation/feedback/{open_answer.id}/review/start",
        json={},
    )
    assert read_only_answer.status_code == 403

    answer_grant.can_query = True
    model_grant.can_query = False
    db_session.commit()
    missing_bound_query = client.post(
        f"/api/v1/evaluation/feedback/{open_answer.id}/review/start",
        json={},
    )
    assert missing_bound_query.status_code == 403

    legacy_review = _answer(
        db_session,
        analyst,
        datasource,
        model,
        flow=FLOW_ID,
        workflow_state="CORRECTION_SUBMITTED",
    )
    assert client.post(
        f"/api/v1/evaluation/feedback/{legacy_review.id}/review",
        json={"decision": "REJECT", "comment": "no answer grant"},
    ).status_code == 403

    replay_answer = _answer(
        db_session,
        analyst,
        datasource,
        model,
        flow=PHASE4_FLOW_ID,
        workflow_state="ACCEPTED",
        status="VERIFIED",
    )
    _grant(db_session, analyst, "ANSWER", replay_answer.id, can_query=False)
    assert client.post(
        f"/api/v1/evaluation/feedback/{replay_answer.id}/replay",
        json={"question": "经营分析客户邮箱"},
    ).status_code == 403

    model_grant.can_query = True
    db_session.commit()
    started = client.post(
        f"/api/v1/evaluation/feedback/{open_answer.id}/review/start",
        json={},
    )
    assert started.status_code == 200


def test_recall_and_feedback_dashboard_filter_analyst_answers_and_redact_sql(
    client,
    db_session: Session,
) -> None:
    admin, analyst, datasource, model = _scope(db_session)
    _grant(db_session, analyst, "DATASOURCE", datasource.id)
    _grant(db_session, analyst, "SEMANTIC_MODEL", model.id)
    allowed = _answer(
        db_session, analyst, datasource, model,
        flow=PHASE4_FLOW_ID, workflow_state="ACCEPTED", status="VERIFIED",
    )
    read_only = _answer(
        db_session, analyst, datasource, model,
        flow=PHASE4_FLOW_ID, workflow_state="ACCEPTED", status="VERIFIED",
    )
    hidden = _answer(
        db_session, analyst, datasource, model,
        flow=PHASE4_FLOW_ID, workflow_state="ACCEPTED", status="VERIFIED",
    )
    _grant(db_session, analyst, "ANSWER", allowed.id)
    _grant(db_session, analyst, "ANSWER", read_only.id, can_query=False)
    app.dependency_overrides[get_principal] = lambda: analyst

    recall = client.post(
        "/api/v1/evaluation/feedback/recall",
        json={
            "question": "经营分析客户邮箱",
            "datasource_id": datasource.id,
            "semantic_model_id": model.id,
        },
    )
    assert recall.status_code == 200
    assert [item["answer_id"] for item in recall.json()["candidates"]] == [allowed.id]
    assert "private@example.com" not in recall.text
    assert "***MASKED***" in recall.text

    dashboard = client.get("/api/v1/evaluation/feedback/dashboard")
    assert dashboard.status_code == 200
    payload = dashboard.json()
    assert [item["answer_id"] for item in payload["sql_examples"]] == [allowed.id]
    assert [item["answer_id"] for item in payload["workflows"]] == [allowed.id]
    assert payload["total_replays"] == 1
    assert payload["passed_replays"] == 1
    assert "private@example.com" not in dashboard.text
    assert "driver leaked" not in dashboard.text

    admin_dashboard = feedback_dashboard(db_session, principal=admin)
    assert {item["answer_id"] for item in admin_dashboard["workflows"]} == {
        allowed.id, read_only.id, hidden.id,
    }
    assert "private@example.com" not in str(admin_dashboard)
