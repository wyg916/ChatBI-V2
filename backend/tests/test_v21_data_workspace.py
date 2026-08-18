from __future__ import annotations

from app.models import (
    DataSource,
    DataSourceColumn,
    DataSourceRelation,
    DataSourceSchema,
    DataSourceTable,
    Workspace,
)
from app.query.contracts import ExecutionResult
from app.query.executor import QueryExecutor


def seed_catalog(db_session, datasource_id: str) -> None:
    schema = DataSourceSchema(datasource_id=datasource_id, name="finance", qualified_name="finance")
    db_session.add(schema)
    db_session.flush()
    orders = DataSourceTable(schema_id=schema.id, name="orders", qualified_name="finance.orders", comment="Order facts")
    customers = DataSourceTable(schema_id=schema.id, name="customers", qualified_name="finance.customers", comment="Customer master")
    db_session.add_all([orders, customers])
    db_session.flush()
    db_session.add_all([
        DataSourceColumn(table_id=orders.id, name="order_id", qualified_name="finance.orders.order_id", data_type="bigint", nullable=False, primary_key=True),
        DataSourceColumn(table_id=orders.id, name="customer_id", qualified_name="finance.orders.customer_id", data_type="bigint", nullable=False, foreign_key=True),
        DataSourceColumn(table_id=orders.id, name="email", qualified_name="finance.orders.email", data_type="text", nullable=True),
        DataSourceColumn(table_id=orders.id, name="revenue", qualified_name="finance.orders.revenue", data_type="numeric", nullable=False),
        DataSourceColumn(table_id=customers.id, name="customer_id", qualified_name="finance.customers.customer_id", data_type="bigint", nullable=False, primary_key=True),
    ])
    db_session.add(DataSourceRelation(
        datasource_id=datasource_id, source_schema="finance", source_table="orders",
        source_columns=["customer_id"], target_schema="finance", target_table="customers",
        target_columns=["customer_id"],
    ))
    db_session.commit()


def fake_execute(self, *, datasource, normalized_sql, row_limit, timeout_ms):
    rows = [{"order_id": 1, "customer_id": 7, "email": "buyer@example.com", "revenue": 99.5}]
    columns = list(rows[0])
    return ExecutionResult(
        status="SUCCEEDED", columns=columns, column_types=["unknown"] * len(columns), rows=rows,
        row_count=1, duration_ms=4, datasource_id=datasource.id, dialect=datasource.type,
        normalized_sql=normalized_sql, result_signature="a" * 64,
    )


def fake_explain(self, *, datasource, normalized_sql, timeout_ms):
    return ExecutionResult(
        status="SUCCEEDED", columns=["plan"], column_types=["json"], rows=[{"plan": {"Node Type": "Limit"}}],
        row_count=1, duration_ms=2, datasource_id=datasource.id, dialect=datasource.type,
        normalized_sql=normalized_sql, result_signature="b" * 64,
    )


def test_catalog_search_relationships_and_cross_workspace_isolation(client, db_session, datasource_id):
    seed_catalog(db_session, datasource_id)
    response = client.get(f"/api/v1/data-workspace/datasources/{datasource_id}/search?q=customer&page=1&page_size=2")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert len(payload["items"]) == 2
    assert {item["kind"] for item in payload["items"]}.issubset({"table", "column"})

    relationships = client.get(f"/api/v1/data-workspace/datasources/{datasource_id}/relationships")
    assert relationships.status_code == 200
    assert relationships.json()[0]["source_columns"] == ["customer_id"]

    foreign_workspace = Workspace(name="Foreign Workspace")
    db_session.add(foreign_workspace)
    db_session.flush()
    foreign = DataSource(
        workspace_id=foreign_workspace.id, name="Foreign", type="postgresql", host="127.0.0.1", port=5432,
        database="foreign", username="readonly", password_encrypted="not-used", ssl=False,
    )
    db_session.add(foreign)
    db_session.commit()
    denied = client.get(f"/api/v1/data-workspace/datasources/{foreign.id}/search")
    assert denied.status_code == 403


def test_sql_workspace_guard_execute_explain_history_replay_and_verified_sql(
    client, db_session, datasource_id, monkeypatch,
):
    seed_catalog(db_session, datasource_id)
    monkeypatch.setattr(QueryExecutor, "execute", fake_execute)
    monkeypatch.setattr(QueryExecutor, "explain", fake_explain)
    sql = "select order_id, customer_id, email, revenue from finance.orders"

    formatted = client.post("/api/v1/data-workspace/sql/format", json={"datasource_id": datasource_id, "sql": sql})
    assert formatted.status_code == 200
    assert "SELECT" in formatted.json()["formatted_sql"]

    blocked = client.post("/api/v1/data-workspace/sql/execute", json={
        "datasource_id": datasource_id, "sql": "DELETE FROM finance.orders", "row_limit": 20,
    })
    assert blocked.status_code == 201
    assert blocked.json()["status"] == "SECURITY_REJECTED"
    assert blocked.json()["execution"] == {}

    executed = client.post("/api/v1/data-workspace/sql/execute", json={
        "datasource_id": datasource_id, "sql": sql, "row_limit": 20,
    })
    assert executed.status_code == 201
    run = executed.json()
    assert run["status"] == "SUCCEEDED"
    assert run["oracle"]["status"] == "PASSED"
    assert run["execution"]["result_signature"] == "a" * 64

    explained = client.post("/api/v1/data-workspace/sql/explain", json={
        "datasource_id": datasource_id, "sql": sql, "row_limit": 20,
    })
    assert explained.status_code == 201
    assert explained.json()["execution"]["rows"][0]["plan"]["Node Type"] == "Limit"

    history = client.get(f"/api/v1/data-workspace/sql/history?datasource_id={datasource_id}")
    assert history.status_code == 200
    assert history.json()["total"] == 3

    replay = client.post(f"/api/v1/data-workspace/sql/history/{run['id']}/replay")
    assert replay.status_code == 201
    assert replay.json()["operation"] == "REPLAY"

    verified = client.post(f"/api/v1/data-workspace/sql/history/{run['id']}/verify", json={"owner_name": "SQL Analyst"})
    assert verified.status_code == 201
    assert verified.json()["status"] == "VERIFIED"
    assert verified.json()["result_signature"] == "a" * 64


def test_sample_values_are_lazy_paginated_and_sensitive_fields_are_masked(
    client, db_session, datasource_id, monkeypatch,
):
    seed_catalog(db_session, datasource_id)
    monkeypatch.setattr(QueryExecutor, "execute", fake_execute)
    response = client.get(
        f"/api/v1/data-workspace/datasources/{datasource_id}/schemas/finance/tables/orders/sample?page=2&page_size=25"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["page"] == 2
    assert payload["page_size"] == 25
    assert payload["masked_columns"] == ["email"]
    assert payload["rows"][0]["email"] == "***MASKED***"
    assert payload["rows"][0]["revenue"] == 99.5
