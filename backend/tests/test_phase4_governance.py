from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import (
    AppUser,
    ChatMessage,
    Conversation,
    DataSource,
    EvaluationRun,
    ModelInvocation,
    QueryAuditEvent,
    QueryRun,
    SemanticModel,
    Workspace,
)
from app.schemas.governance import (
    CostDashboardResponse,
    EvaluationGovernanceDashboardResponse,
    ModelDashboardResponse,
    TraceDashboardResponse,
    TraceDetailResponse,
)
from app.services.governance import (
    cost_dashboard,
    evaluation_governance_dashboard,
    model_dashboard,
    model_invocation_contract_fields,
    trace_dashboard,
    trace_detail,
)


def _business_scope(db: Session, *, suffix: str = "primary") -> dict[str, object]:
    workspace = Workspace(name=f"Governance {suffix}")
    db.add(workspace)
    db.flush()
    user = AppUser(
        workspace_id=workspace.id,
        email=f"governance-{suffix}@chatbi.local",
        display_name=f"Governance {suffix}",
        role="ADMIN",
        status="ACTIVE",
    )
    datasource = DataSource(
        workspace_id=workspace.id,
        name=f"Readonly {suffix}",
        type="postgresql",
        host="127.0.0.1",
        port=5432,
        database="chatbi_test",
        username="readonly",
        password_encrypted="encrypted-fixture",
    )
    db.add_all([user, datasource])
    db.flush()
    semantic_model = SemanticModel(
        workspace_id=workspace.id,
        datasource_id=datasource.id,
        name=f"Semantic {suffix}",
        status="PUBLISHED",
        version=1,
    )
    conversation = Conversation(
        workspace_id=workspace.id,
        user_id=user.id,
        title=f"Conversation {suffix}",
    )
    db.add_all([semantic_model, conversation])
    db.flush()
    return {
        "workspace": workspace,
        "user": user,
        "datasource": datasource,
        "semantic_model": semantic_model,
        "conversation": conversation,
    }


def test_cost_and_model_governance_use_real_workspace_scoped_ledger(db_session: Session):
    scope = _business_scope(db_session)
    foreign = _business_scope(db_session, suffix="foreign")
    now = datetime.now(timezone.utc)
    db_session.add_all([
        ModelInvocation(
            workspace_id=scope["workspace"].id,
            user_id=scope["user"].id,
            trace_id="TRACE-GOVERNANCE-001",
            request_id="REQUEST-GOVERNANCE-001",
            conversation_id=scope["conversation"].id,
            route="DATA_QUERY",
            capability="nl2sql",
            provider="deepseek",
            model="deepseek-chat",
            status="SUCCEEDED",
            input_tokens=120,
            cached_input_tokens=20,
            output_tokens=30,
            cost_cny=0.0125,
            latency_ms=410,
            cache_hit=True,
            fallback_count=1,
            retry_count=1,
            premium_escalation=False,
            circuit_state="CLOSED",
            pricing_version="v1@2026-08-22",
            created_at=now,
        ),
        ModelInvocation(
            workspace_id=foreign["workspace"].id,
            user_id=foreign["user"].id,
            trace_id="TRACE-FOREIGN",
            request_id="REQUEST-FOREIGN",
            route="DATA_QUERY",
            capability="nl2sql",
            provider="kimi",
            model="kimi-k2",
            status="FAILED",
            error_code="FOREIGN_SECRET_ERROR",
            created_at=now,
        ),
    ])
    db_session.commit()

    assert set(model_invocation_contract_fields()) == {
        "id", "workspace_id", "user_id", "trace_id", "request_id", "conversation_id", "route",
        "capability", "provider", "model", "status", "input_tokens", "cached_input_tokens",
        "output_tokens", "cost_cny", "latency_ms", "cache_hit", "fallback_count", "retry_count",
        "premium_escalation", "error_code", "circuit_state", "pricing_version", "created_at",
    }
    cost = CostDashboardResponse.model_validate(cost_dashboard(
        db_session, workspace_id=scope["workspace"].id,
    ))
    assert cost.coverage.source == "MODEL_INVOCATION_LEDGER"
    assert cost.coverage.complete is True
    assert cost.requests == 1
    assert cost.cost_cny == 0.0125
    assert cost.cache_hits == 1
    assert cost.fallbacks == 1
    assert [item.key for item in cost.by_provider] == ["deepseek"]
    assert [item.key for item in cost.by_workspace] == [scope["workspace"].id]
    assert [item.key for item in cost.by_user] == [scope["user"].id]
    assert [item.key for item in cost.by_conversation] == [scope["conversation"].id]
    assert cost.entries[0].circuit_state == "CLOSED"
    assert "FOREIGN_SECRET_ERROR" not in cost.model_dump_json()

    models = ModelDashboardResponse.model_validate(model_dashboard(
        db_session, workspace_id=scope["workspace"].id,
    ))
    deepseek = next(item for item in models.providers if item.provider == "deepseek")
    assert deepseek.requests == 1
    assert deepseek.circuit_state == "CLOSED"
    assert deepseek.cost_cny == 0.0125


def test_trace_detail_is_one_trace_and_redacts_sensitive_payloads(db_session: Session):
    scope = _business_scope(db_session, suffix="trace")
    run = QueryRun(
        workspace_id=scope["workspace"].id,
        datasource_id=scope["datasource"].id,
        semantic_model_id=scope["semantic_model"].id,
        semantic_model_version=1,
        question="本月收入是多少",
        status="SUCCEEDED",
        provider="deepseek",
        context_payload={
            "dialect": "postgresql",
            "security_policy": {"sensitive_columns": ["email"]},
            "request_context": {
                "trace_id": "TRACE-GOVERNANCE-TRACE",
                "request_id": "REQUEST-GOVERNANCE-TRACE",
                "user_id": scope["user"].id,
            },
            "api_key": "must-not-leak",
        },
        plan_payload={
            "model_trace": {
                "resolved_provider": "deepseek",
                "resolved_model": "deepseek-chat",
                "reasoning_content": "must-not-leak",
            },
        },
        guard_payload={"allowed": True},
        execution_payload={"status": "SUCCEEDED", "columns": ["revenue"], "rows": [{"revenue": 12}]},
        oracle_payload={"status": "PASSED"},
        generated_sql="select sum(revenue) from sales where email='victim@example.com'",
        normalized_sql="SELECT SUM(revenue) FROM sales WHERE email = 'victim@example.com'",
        result_signature="signature",
        duration_ms=55,
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(QueryAuditEvent(
        query_run_id=run.id,
        event_type="SQL_GUARD",
        status="PASS",
        details={
            "duration_ms": 7,
            "statement_type": "SELECT",
            "prompt": "must-not-leak",
            "reasoning_content": "must-not-leak",
            "api_key": "must-not-leak",
            "raw_tool_payload": {"password": "must-not-leak"},
        },
    ))
    db_session.add(ChatMessage(
        conversation_id=scope["conversation"].id,
        workspace_id=scope["workspace"].id,
        user_id=scope["user"].id,
        role="assistant",
        content="收入为 12",
        route="DATA_QUERY",
        status="COMPLETED",
        query_run_id=run.id,
        response_payload={"secret": "must-not-leak"},
        trace_payload={
            "trace_id": "TRACE-GOVERNANCE-TRACE",
            "operation_spans": [{
                "name": "chat.route",
                "status": "COMPLETED",
                "started_at": "2026-08-22T08:00:00Z",
                "duration_ms": 9,
                "timing_source": "CHAT_STAGE",
            }],
            "model_call": {
                "resolved_provider": "deepseek",
                "resolved_model": "deepseek-chat",
                "latency_ms": 40,
                "cost_cny": 0.01,
                "reasoning_content": "must-not-leak",
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        },
    ))
    db_session.commit()

    detail = TraceDetailResponse.model_validate(trace_detail(
        db_session,
        workspace_id=scope["workspace"].id,
        trace_id="TRACE-GOVERNANCE-TRACE",
    ))
    serialized = detail.model_dump_json()
    assert detail.trace.has_sql is True
    assert detail.trace.provider == "deepseek"
    assert {stage.stage for stage in detail.stages} == {"SQL_GUARD", "chat.route", "model.invoke"}
    chat_stage = next(stage for stage in detail.stages if stage.stage == "chat.route")
    assert chat_stage.duration_ms == 9
    assert chat_stage.timing_source == "CHAT_STAGE"
    public_sql = next(stage for stage in detail.stages if stage.stage == "SQL_GUARD").sql
    assert public_sql == "SELECT SUM(revenue) FROM sales WHERE email = '***MASKED***'"
    assert "victim@example.com" in (run.normalized_sql or "")
    for forbidden in (
        "must-not-leak", "reasoning_content", "api_key", "raw_tool_payload",
        "victim@example.com",
    ):
        assert forbidden not in serialized
    dashboard = TraceDashboardResponse.model_validate(trace_dashboard(
        db_session,
        workspace_id=scope["workspace"].id,
    ))
    assert dashboard.trace_granularity == "STAGE_LEVEL"


def test_evaluation_governance_preserves_database_failures_and_labels_evidence(db_session: Session):
    scope = _business_scope(db_session, suffix="evaluation")
    db_session.add(EvaluationRun(
        workspace_id=scope["workspace"].id,
        release_name="Feedback Regression",
        model_name="deepseek-chat",
        status="FAILED",
        golden_set_count=2,
        sql_execution_pass_count=1,
        result_value_pass_count=1,
        result_accuracy=50,
        error_distribution=[{"label": "RESULT_MISMATCH", "percent": 50}],
        trend_points=[{
            "kind": "evaluation_profile",
            "profile": {
                "version": "v1.3",
                "source_sha": "deadbeef",
                "runtime_calls": 2,
                "artifacts": ["db:evaluation_case_result"],
            },
        }],
        manifest_sha256="0" * 64,
        completed_at=datetime.now(timezone.utc),
    ))
    db_session.commit()

    dashboard = EvaluationGovernanceDashboardResponse.model_validate(
        evaluation_governance_dashboard(db_session, workspace_id=scope["workspace"].id)
    )
    database_run = next(item for item in dashboard.runs if item.source == "DATABASE")
    assert database_run.status == "FAILED"
    assert database_run.pass_rate == 0.5
    assert database_run.runtime_calls == 2
    assert "RESULT_MISMATCH" in database_run.errors
    assert all(item.evidence_sha256 for item in dashboard.runs if item.source == "EVIDENCE")
    json.loads(dashboard.model_dump_json())


def test_governance_router_exposes_real_ledger(client, db_session: Session):
    workspace = db_session.query(Workspace).filter_by(name="Test Workspace").one()
    user = db_session.query(AppUser).filter_by(email="admin@chatbi.local").one()
    db_session.add(ModelInvocation(
        workspace_id=workspace.id,
        user_id=user.id,
        trace_id="TRACE-API-GOVERNANCE",
        request_id="REQUEST-API-GOVERNANCE",
        route="DATA_QUERY",
        capability="nl2sql",
        provider="mimo",
        model="mimo-v2.5",
        status="SUCCEEDED",
        input_tokens=10,
        output_tokens=4,
        cost_cny=0.002,
        latency_ms=25,
        circuit_state="CLOSED",
        pricing_version="v1@2026-08-22",
    ))
    db_session.commit()

    response = client.get("/api/v1/governance/cost?provider=mimo")
    assert response.status_code == 200
    payload = response.json()
    assert payload["coverage"]["source"] == "MODEL_INVOCATION_LEDGER"
    assert payload["requests"] == 1
    assert payload["entries"][0]["trace_id"] == "TRACE-API-GOVERNANCE"
    assert client.get("/api/v1/governance/traces").status_code == 200
    assert client.get("/api/v1/governance/models").status_code == 200
    assert client.get("/api/v1/governance/evaluation").status_code == 200
