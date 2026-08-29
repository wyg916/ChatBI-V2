from sqlalchemy import select

from app.core.auth import hash_password
from app.models import (
    AnswerVersion, AppUser, AuditEvent, DataSourceColumn, DataSourceSchema, DataSourceTable,
    QueryRun, ResourceGrant, SemanticModel, SqlWorkspaceRun, VerifiedAnswer, Workspace,
)
from app.query.contracts import ExecutionResult
from app.query.executor import QueryExecutor


TEST_PASSWORD = "Valid-Test-Password-42!"


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


def _seed_users(db_session):
    workspace = Workspace(name="Security Test Workspace")
    db_session.add(workspace)
    db_session.flush()
    admin = AppUser(
        workspace_id=workspace.id, email="security-admin@chatbi.local", display_name="Admin",
        role="ADMIN", status="ACTIVE", password_hash=hash_password(TEST_PASSWORD),
    )
    analyst = AppUser(
        workspace_id=workspace.id, email="security-analyst@chatbi.local", display_name="Analyst",
        role="ANALYST", status="ACTIVE", password_hash=hash_password(TEST_PASSWORD),
    )
    db_session.add_all([admin, analyst])
    db_session.commit()
    return admin, analyst


def _login(client, email: str):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert response.status_code == 200


def test_admin_analyst_resource_access_and_denial_audit(raw_client, db_session):
    admin, analyst = _seed_users(db_session)
    _login(raw_client, admin.email)
    postgres = _create_datasource(raw_client, "Allowed PostgreSQL", "postgresql")
    mysql = _create_datasource(raw_client, "Restricted MySQL", "mysql")
    allowed_model = raw_client.post("/api/v1/semantic-models", json={
        "name": "Allowed Model", "datasource_id": postgres["id"],
    }).json()
    restricted_model = raw_client.post("/api/v1/semantic-models", json={
        "name": "Restricted Model", "datasource_id": mysql["id"],
    }).json()
    restricted_answer = raw_client.post("/api/v1/answers", json={
        "question": "管理员限定答案", "model_name": "收入", "owner_name": "管理员",
        "status": "DRAFT", "accuracy_percent": 0,
    }).json()
    restricted_dashboard = raw_client.post("/api/v1/dashboards", json={
        "name": "管理员限定看板", "description": "不得向未授权分析师泄漏", "is_shared": False,
    }).json()
    read_only_answer = raw_client.post("/api/v1/answers", json={
        "question": "仅读答案", "model_name": "收入", "owner_name": "管理员",
        "status": "DRAFT", "accuracy_percent": 0,
    }).json()
    read_only_dashboard = raw_client.post("/api/v1/dashboards", json={
        "name": "仅读看板", "description": "列表元数据可见但不可执行或修改", "is_shared": False,
    }).json()
    db_session.add_all([
        ResourceGrant(user_id=analyst.id, resource_type="DATASOURCE", resource_id=postgres["id"], can_read=True, can_query=True),
        ResourceGrant(user_id=analyst.id, resource_type="SEMANTIC_MODEL", resource_id=allowed_model["id"], can_read=True, can_query=True),
        ResourceGrant(user_id=analyst.id, resource_type="ANSWER", resource_id=read_only_answer["id"], can_read=True, can_query=False),
        ResourceGrant(user_id=analyst.id, resource_type="DASHBOARD", resource_id=read_only_dashboard["id"], can_read=True, can_query=False),
    ])
    db_session.commit()
    assert raw_client.post("/api/v1/auth/logout").status_code == 204
    _login(raw_client, analyst.email)

    visible_sources = raw_client.get("/api/v1/datasources")
    assert visible_sources.status_code == 200
    assert [item["id"] for item in visible_sources.json()] == [postgres["id"]]
    visible_models = raw_client.get("/api/v1/semantic-models")
    assert visible_models.status_code == 200
    assert [item["id"] for item in visible_models.json()] == [allowed_model["id"]]

    assert raw_client.get(f"/api/v1/datasources/{mysql['id']}").status_code == 403
    assert raw_client.get(f"/api/v1/semantic-models/{restricted_model['id']}").status_code == 403
    assert raw_client.get("/api/v1/model-providers").status_code == 403
    assert raw_client.post("/api/v1/ask", json={
        "question": "统计收入", "datasource_id": mysql["id"], "semantic_model_id": restricted_model["id"],
    }).status_code == 403

    visible_answers = raw_client.get("/api/v1/answers")
    assert visible_answers.status_code == 200 and visible_answers.json()["total"] == 1
    assert visible_answers.json()["items"][0]["id"] == read_only_answer["id"]
    assert raw_client.get(f"/api/v1/answers/{restricted_answer['id']}").status_code == 403
    assert raw_client.get(f"/api/v1/answers/{read_only_answer['id']}").status_code == 200
    assert raw_client.patch(
        f"/api/v1/answers/{read_only_answer['id']}/status", json={"status": "DEPRECATED"},
    ).status_code == 403
    assert raw_client.post(f"/api/v1/answers/{read_only_answer['id']}/reuse").status_code == 403
    own_answer = raw_client.post("/api/v1/answers", json={
        "question": "分析师草稿问题", "model_name": "收入", "owner_name": "数据分析组",
        "status": "DRAFT", "accuracy_percent": 0,
    })
    assert own_answer.status_code == 201
    assert {item["id"] for item in raw_client.get("/api/v1/answers").json()["items"]} == {
        read_only_answer["id"], own_answer.json()["id"],
    }
    assert raw_client.get(f"/api/v1/answers/{own_answer.json()['id']}").status_code == 200

    visible_dashboards = raw_client.get("/api/v1/dashboards")
    assert visible_dashboards.status_code == 200 and visible_dashboards.json()["total"] == 1
    assert visible_dashboards.json()["items"][0]["id"] == read_only_dashboard["id"]
    assert raw_client.get(f"/api/v1/dashboards/{restricted_dashboard['id']}").status_code == 403
    assert raw_client.get(f"/api/v1/dashboards/{read_only_dashboard['id']}").status_code == 403
    own_dashboard = raw_client.post("/api/v1/dashboards", json={
        "name": "分析师看板", "description": "RBAC 回归", "is_shared": False,
    })
    assert own_dashboard.status_code == 201
    assert {item["id"] for item in raw_client.get("/api/v1/dashboards").json()["items"]} == {
        read_only_dashboard["id"], own_dashboard.json()["id"],
    }

    denied = list(db_session.scalars(select(AuditEvent).where(AuditEvent.status == "DENIED")))
    assert len(denied) >= 4
    assert {item.resource_type for item in denied} >= {
        "DATASOURCE", "SEMANTIC_MODEL", "ANSWER", "DASHBOARD", "PERMISSION",
    }

    assert raw_client.post("/api/v1/auth/logout").status_code == 204
    _login(raw_client, admin.email)
    overview = raw_client.get("/api/v1/security/overview")
    assert overview.status_code == 200
    payload = overview.json()
    assert payload["user_count"] == 2
    assert {item["name"] for item in payload["roles"]} == {"ADMIN", "ANALYST"}
    assert payload["audit_event_count"] >= 4
    filtered = raw_client.get("/api/v1/security/overview", params={"user_query": "analyst", "user_status": "ACTIVE"})
    assert filtered.status_code == 200
    assert filtered.json()["user_count"] == 2
    assert [item["email"] for item in filtered.json()["users"]] == [analyst.email]


def test_disabled_and_missing_session_are_rejected_and_audited(raw_client, db_session):
    _, analyst = _seed_users(db_session)
    _login(raw_client, analyst.email)
    analyst.status = "DISABLED"
    db_session.commit()

    assert raw_client.get("/api/v1/datasources").status_code == 403
    raw_client.cookies.clear()
    assert raw_client.get("/api/v1/datasources", headers={"X-ChatBI-Actor": "missing@chatbi.local"}).status_code == 401
    events = list(db_session.scalars(select(AuditEvent).where(AuditEvent.action == "AUTHENTICATE")))
    assert {item.details["reason"] for item in events} == {"USER_DISABLED"}


def test_read_without_query_permission_never_receives_column_sample_values(raw_client, db_session):
    admin, analyst = _seed_users(db_session)
    _login(raw_client, admin.email)
    datasource = _create_datasource(raw_client, "Metadata only", "postgresql")
    schema = DataSourceSchema(
        datasource_id=datasource["id"], name="public", qualified_name=f"{datasource['id']}.public",
    )
    db_session.add(schema)
    db_session.flush()
    table = DataSourceTable(
        schema_id=schema.id, name="customers", qualified_name=f"{datasource['id']}.public.customers",
    )
    db_session.add(table)
    db_session.flush()
    db_session.add(DataSourceColumn(
        table_id=table.id,
        name="email",
        qualified_name=f"{datasource['id']}.public.customers.email",
        data_type="TEXT",
        sample_values=["private@example.com"],
    ))
    db_session.add(ResourceGrant(
        user_id=analyst.id,
        resource_type="DATASOURCE",
        resource_id=datasource["id"],
        can_read=True,
        can_query=False,
    ))
    db_session.commit()
    assert raw_client.post("/api/v1/auth/logout").status_code == 204
    _login(raw_client, analyst.email)

    columns = raw_client.get(
        f"/api/v1/datasources/{datasource['id']}/tables/customers/columns",
        params={"schema": "public"},
    )
    assert columns.status_code == 200
    assert columns.json()[0]["sample_values"] == []
    sample = raw_client.get(
        f"/api/v1/data-workspace/datasources/{datasource['id']}/schemas/public/tables/customers/sample",
    )
    assert sample.status_code == 403


def test_revoked_datasource_runs_disappear_from_history_and_cannot_be_replayed(
    raw_client, db_session,
):
    admin, analyst = _seed_users(db_session)
    _login(raw_client, admin.email)
    datasource = _create_datasource(raw_client, "Revocable history", "postgresql")
    grant = ResourceGrant(
        user_id=analyst.id,
        resource_type="DATASOURCE",
        resource_id=datasource["id"],
        can_read=True,
        can_query=True,
    )
    db_session.add(grant)
    db_session.flush()
    run = SqlWorkspaceRun(
        workspace_id=analyst.workspace_id,
        user_id=analyst.id,
        datasource_id=datasource["id"],
        operation="EXECUTE",
        sql_text="SELECT 1",
        normalized_sql="SELECT 1 LIMIT 1",
        status="SUCCEEDED",
        guard_payload={"allowed": True, "dialect": "postgresql", "normalized_sql": "SELECT 1 LIMIT 1"},
        execution_payload={
            "status": "SUCCEEDED", "columns": ["value"], "rows": [{"value": 1}],
            "normalized_sql": "SELECT 1 LIMIT 1", "result_signature": "a" * 64,
        },
        oracle_payload={"status": "PASSED"},
    )
    db_session.add(run)
    db_session.commit()
    assert raw_client.post("/api/v1/auth/logout").status_code == 204
    _login(raw_client, analyst.email)

    visible = raw_client.get("/api/v1/data-workspace/sql/history")
    assert visible.status_code == 200
    assert [item["id"] for item in visible.json()["items"]] == [run.id]

    db_session.delete(grant)
    db_session.commit()
    revoked = raw_client.get("/api/v1/data-workspace/sql/history")
    assert revoked.status_code == 200
    assert revoked.json()["total"] == 0
    assert revoked.json()["items"] == []
    assert raw_client.get(
        "/api/v1/data-workspace/sql/history", params={"datasource_id": datasource["id"]},
    ).status_code == 403
    assert raw_client.post(f"/api/v1/data-workspace/sql/history/{run.id}/replay").status_code == 403
    assert raw_client.post(
        f"/api/v1/data-workspace/sql/history/{run.id}/verify",
        json={"owner_name": "Revoked Analyst", "status": "VERIFIED"},
    ).status_code == 403


def test_sensitive_sql_literal_is_absent_from_run_history_and_shared_answer_reads(
    raw_client, db_session, monkeypatch,
):
    admin, analyst = _seed_users(db_session)
    _login(raw_client, admin.email)
    datasource = _create_datasource(raw_client, "Sensitive SQL", "postgresql")
    schema = DataSourceSchema(
        datasource_id=datasource["id"], name="public",
        qualified_name=f"{datasource['id']}.public",
    )
    db_session.add(schema)
    db_session.flush()
    table = DataSourceTable(
        schema_id=schema.id, name="customers",
        qualified_name=f"{datasource['id']}.public.customers",
    )
    db_session.add(table)
    db_session.flush()
    db_session.add(DataSourceColumn(
        table_id=table.id, name="email",
        qualified_name=f"{datasource['id']}.public.customers.email",
        data_type="TEXT",
    ))
    db_session.commit()

    def fake_execute(self, *, datasource, normalized_sql, row_limit, timeout_ms):
        return ExecutionResult(
            status="SUCCEEDED", columns=["contact"], column_types=["TEXT"],
            rows=[{"contact": "victim@example.com"}], row_count=1, duration_ms=2,
            datasource_id=datasource.id, dialect=datasource.type,
            normalized_sql=normalized_sql, result_signature="a" * 64,
        )

    def fake_explain(self, *, datasource, normalized_sql, timeout_ms):
        return ExecutionResult(
            status="SUCCEEDED", columns=["plan"], column_types=["JSON"],
            rows=[{"plan": [{"Plan": {"Node Type": "Limit", "Total Cost": 1.0}}]}],
            row_count=1, duration_ms=1, datasource_id=datasource.id,
            dialect=datasource.type, normalized_sql=normalized_sql,
            result_signature="b" * 64,
        )

    monkeypatch.setattr(QueryExecutor, "execute", fake_execute)
    monkeypatch.setattr(QueryExecutor, "explain", fake_explain)
    secret = "victim@example.com"
    sql = "SELECT email AS contact FROM customers WHERE email='victim@example.com'"
    executed = raw_client.post("/api/v1/data-workspace/sql/execute", json={
        "datasource_id": datasource["id"], "sql": sql, "row_limit": 20,
    })
    assert executed.status_code == 201
    assert secret not in executed.text
    assert executed.json()["execution"]["rows"] == [{"contact": "***MASKED***"}]
    run_id = executed.json()["id"]
    stored_run = db_session.get(SqlWorkspaceRun, run_id)
    assert stored_run is not None
    assert secret in stored_run.sql_text
    assert secret in (stored_run.normalized_sql or "")

    history = raw_client.get(
        "/api/v1/data-workspace/sql/history", params={"datasource_id": datasource["id"]},
    )
    assert history.status_code == 200
    assert secret not in history.text

    verified = raw_client.post(
        f"/api/v1/data-workspace/sql/history/{run_id}/verify",
        json={"owner_name": "Security Admin", "status": "VERIFIED"},
    )
    assert verified.status_code == 201
    answer = db_session.get(VerifiedAnswer, verified.json()["answer_id"])
    assert answer is not None
    assert secret in (answer.sql_text or "")
    answer.question = sql
    db_session.add(AnswerVersion(
        answer_id=answer.id,
        version=1,
        snapshot={
            "question": f"SQL 工作台验证：{sql}",
            "sql": stored_run.normalized_sql,
            "sql_plan": {"guard": stored_run.guard_payload},
            "result_snapshot": stored_run.execution_payload,
        },
    ))
    db_session.add(ResourceGrant(
        user_id=analyst.id, resource_type="ANSWER", resource_id=answer.id,
        can_read=True, can_query=False,
    ))
    db_session.commit()

    model = SemanticModel(
        workspace_id=admin.workspace_id, datasource_id=datasource["id"],
        name="Sensitive response model", status="PUBLISHED", version=1,
    )
    db_session.add(model)
    db_session.flush()
    query_run = QueryRun(
        workspace_id=admin.workspace_id,
        datasource_id=datasource["id"],
        semantic_model_id=model.id,
        semantic_model_version=1,
        question=sql,
        status="FAILED",
        provider="test",
        context_payload={
            "dialect": "postgresql",
            "security_policy": {"sensitive_columns": ["email"]},
            "verified_sql_examples": [{"sql": sql}],
            "request_context": {"permission_hash": secret},
            "permission_hash": secret,
        },
        plan_payload={
            "generated_sql": sql,
            "filters": [{"field": "customers.email", "operator": "=", "value": secret}],
        },
        guard_payload={
            "allowed": True,
            "dialect": "postgresql",
            "normalized_sql": stored_run.normalized_sql,
        },
        execution_payload={
            "status": "FAILED", "normalized_sql": stored_run.normalized_sql,
            "rows": [], "error_code": "QUERY_EXECUTION_ERROR",
            "error_message": f"driver failed while executing {sql}",
        },
        oracle_payload={"status": "NOT_RUN"},
        error_code="QUERY_EXECUTION_ERROR",
        error_message=f"driver failed while executing {sql}",
    )
    db_session.add(query_run)
    stored_run.status = "FAILED"
    stored_run.error_code = "QUERY_EXECUTION_ERROR"
    stored_run.error_message = f"driver failed while executing {sql}"
    db_session.commit()

    query_read = raw_client.get(f"/api/v1/queries/{query_run.id}")
    assert query_read.status_code == 200
    assert secret not in query_read.text
    assert "verified_sql_examples" not in query_read.json()["context"]
    assert "request_context" not in query_read.json()["context"]
    assert "permission_hash" not in query_read.json()["context"]
    assert query_read.json()["plan"]["filters"][0]["value"] == "***MASKED***"
    failed_history = raw_client.get(
        "/api/v1/data-workspace/sql/history", params={"datasource_id": datasource["id"]},
    )
    assert failed_history.status_code == 200
    assert secret not in failed_history.text
    assert "use the error code" in failed_history.json()["items"][0]["error_message"]

    assert raw_client.post("/api/v1/auth/logout").status_code == 204
    _login(raw_client, analyst.email)
    answer_list = raw_client.get("/api/v1/answers")
    assert answer_list.status_code == 200
    assert secret not in answer_list.text
    detail = raw_client.get(f"/api/v1/answers/{answer.id}")
    assert detail.status_code == 200
    assert secret not in detail.text
    assert detail.json()["question"] == (
        "SELECT email AS contact FROM customers WHERE email = '***MASKED***'"
    )
    assert detail.json()["sql_text"].count("***MASKED***") == 1
    assert detail.json()["versions"][0]["snapshot"]["question"].count("***MASKED***") == 1
    assert detail.json()["versions"][0]["snapshot"]["sql"].count("***MASKED***") == 1
