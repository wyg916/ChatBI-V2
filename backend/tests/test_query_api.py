from sqlalchemy import select

from app.models import DataSource, DataSourceColumn, DataSourceSchema, DataSourceTable, SemanticModel
from app.query.contracts import ExecutionResult
from app.query.executor import QueryExecutor
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
    answer = client.post(f"/api/v1/queries/{query_id}/save", json={"owner_name": "Tester", "status": "DRAFT"})
    assert answer.status_code == 201
    assert answer.json()["question"] == "按地区统计订单收入"


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
