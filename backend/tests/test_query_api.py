from datetime import timedelta

from sqlalchemy import select

from app.models import AuditEvent, DataSource, DataSourceColumn, DataSourceSchema, DataSourceTable, SemanticModel
from app.query.contracts import AskRequest, ExecutionResult
from app.query.executor import QueryExecutor
from app.query.service import _select_runtime
from app.services.seed import DEMO_MODEL_NAME, seed_demo_semantic_model


def prepare_catalog(db_session):
    model = seed_demo_semantic_model(db_session)
    datasource = db_session.get(DataSource, model.datasource_id)
    schema = DataSourceSchema(
        datasource_id=datasource.id, name="demo_business",
        qualified_name=f"{datasource.id}.demo_business",
    )
    db_session.add(schema)
    db_session.flush()
    definitions = {
        "orders": ["order_id", "customer_id", "product_id", "region_id", "order_date", "revenue", "cost", "status"],
        "regions": ["region_id", "region_name"],
        "products": ["product_id", "product_name", "category"],
        "customers": ["customer_id", "customer_name", "customer_type"],
    }
    for table_name, columns in definitions.items():
        table = DataSourceTable(
            schema_id=schema.id, name=table_name,
            qualified_name=f"{schema.qualified_name}.{table_name}",
        )
        db_session.add(table)
        db_session.flush()
        for column_name in columns:
            db_session.add(DataSourceColumn(
                table_id=table.id, name=column_name,
                qualified_name=f"{table.qualified_name}.{column_name}",
                data_type="TEXT", nullable=True,
            ))
    datasource.status = "SYNCED"
    db_session.commit()
    return datasource, db_session.scalar(select(SemanticModel).where(SemanticModel.name == DEMO_MODEL_NAME))


def test_default_runtime_is_stable_when_new_published_model_appears(db_session):
    datasource, primary = prepare_catalog(db_session)
    transient = SemanticModel(
        workspace_id=primary.workspace_id,
        datasource_id=datasource.id,
        name="Parallel transient model",
        status="PUBLISHED",
        created_at=primary.created_at + timedelta(seconds=1),
    )
    db_session.add(transient)
    db_session.commit()

    selected_datasource, selected_model = _select_runtime(db_session, AskRequest(question="统计收入"))
    assert selected_datasource.id == datasource.id
    assert selected_model.id == primary.id


def test_query_api_full_chain_feedback_and_save(client, db_session, monkeypatch):
    datasource, model = prepare_catalog(db_session)

    def fake_execute(self, *, datasource, normalized_sql, row_limit, timeout_ms):
        return ExecutionResult(
            status="SUCCEEDED", columns=["region", "revenue"], column_types=["TEXT", "NUMERIC"],
            rows=[{"region": "华东", "revenue": 100.0}], row_count=1, duration_ms=4,
            datasource_id=datasource.id, dialect=datasource.type, normalized_sql=normalized_sql,
            result_signature="a" * 64,
        )

    monkeypatch.setattr(QueryExecutor, "execute", fake_execute)
    response = client.post("/api/v1/ask", json={
        "question": "按地区统计订单收入",
        "datasource_id": datasource.id,
        "semantic_model_id": model.id,
    })
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "SUCCEEDED"
    assert body["guard"]["allowed"] is True
    assert body["execution"]["rows"] == [{"region": "华东", "revenue": 100.0}]
    assert body["oracle"]["status"] == "PASSED"
    query_id = body["id"]

    feedback = client.post(f"/api/v1/queries/{query_id}/feedback", json={"feedback_type": "HELPFUL"})
    assert feedback.status_code == 201
    assert feedback.json()["recorded"] is True
    answer = client.post(f"/api/v1/queries/{query_id}/save", json={"owner_name": "Tester", "status": "VERIFIED"})
    assert answer.status_code == 201
    assert answer.json()["question"] == "按地区统计订单收入"
    assert answer.json()["chart_spec"]["data_source_query_id"] == query_id
    assert answer.json()["narrative"]["source_query_id"] == query_id
    answer_id = answer.json()["id"]

    detail = client.get(f"/api/v1/answers/{answer_id}")
    assert detail.status_code == 200
    assert len(detail.json()["versions"]) == 1

    dashboard = client.post("/api/v1/dashboards", json={
        "name": "真实答案看板", "description": "由已验证答案创建", "is_shared": False,
    })
    assert dashboard.status_code == 201
    card = client.post(f"/api/v1/dashboards/{dashboard.json()['id']}/cards", json={"answer_id": answer_id})
    assert card.status_code == 201
    assert card.json()["source_question"] == "按地区统计订单收入"
    assert card.json()["result_signature"] == "a" * 64

    deleted = client.delete(f"/api/v1/dashboards/{dashboard.json()['id']}/cards/{card.json()['id']}")
    assert deleted.status_code == 204
    assert db_session.scalar(select(AuditEvent).where(AuditEvent.action == "QUERY_RUN", AuditEvent.resource_id == query_id)) is not None


def test_query_api_rejects_dangerous_sql_before_executor(client, db_session, monkeypatch):
    datasource, model = prepare_catalog(db_session)
    calls = 0

    def should_not_execute(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("Executor must not be called")

    monkeypatch.setattr(QueryExecutor, "execute", should_not_execute)
    response = client.post("/api/v1/ask", json={
        "question": "DELETE FROM demo_business.orders",
        "datasource_id": datasource.id,
        "semantic_model_id": model.id,
    })
    assert response.status_code == 201
    assert response.json()["status"] == "SECURITY_REJECTED"
    assert response.json()["execution"] == {}
    assert calls == 0
