from __future__ import annotations

from app.models import (
    DataSource,
    DataSourceColumn,
    DataSourceRelation,
    DataSourceSchema,
    DataSourceTable,
    VerifiedAnswer,
    Workspace,
)
from app.core.data_safety import (
    redact_public_explain_plan_payload,
    redact_public_sql,
    redact_public_sql_payload,
    sensitive_output_columns,
)
from app.query.contracts import ExecutionResult
from app.query.executor import QueryExecutor


def test_sensitive_lineage_follows_ctes_subqueries_and_stars():
    cases = (
        "SELECT q.contact FROM (SELECT email AS contact FROM customers) q",
        "WITH q AS (SELECT email AS contact FROM customers) SELECT contact FROM q",
        "SELECT * FROM (SELECT email AS contact FROM customers) q",
    )
    for sql in cases:
        assert sensitive_output_columns(
            sql, ["contact"], ["email"], dialect="postgresql",
        ) == ["contact"]
    renamed_cases = (
        "WITH q(status) AS (SELECT email FROM customers) SELECT status FROM q",
        "SELECT status FROM (SELECT email FROM customers) q(status)",
        "SELECT status FROM LATERAL (SELECT email FROM customers) q(status)",
        "SELECT q.status FROM LATERAL (SELECT email FROM customers) q(status)",
    )
    for sql in renamed_cases:
        assert sensitive_output_columns(
            sql, ["status"], ["email"], dialect="postgresql",
        ) == ["status"]
    whole_row_cases = (
        "WITH q AS (SELECT email AS contact FROM customers) SELECT q AS payload FROM q",
        "WITH q AS (SELECT email AS contact FROM customers) SELECT ROW(q) AS payload FROM q",
        "SELECT ROW(u.*) AS payload FROM customers u",
        "SELECT json_build_array(u.*) AS payload FROM customers u",
    )
    for sql in whole_row_cases:
        assert sensitive_output_columns(
            sql, ["payload"], ["email"], dialect="postgresql",
        ) == ["payload"]


def test_public_sql_renderer_redacts_sensitive_predicate_literals_only():
    sql = (
        "SELECT email AS contact FROM customers "
        "WHERE email = 'victim@example.com' "
        "OR email IN ('first@example.com', 'second@example.com') "
        "OR email ILIKE '%example.com' "
        "OR email BETWEEN 'a@example.com' AND 'z@example.com' "
        "OR customer_id = 42"
    )
    public_sql = redact_public_sql(sql, ["email"], dialect="postgresql")
    assert public_sql is not None
    assert "victim@example.com" not in public_sql
    assert "first@example.com" not in public_sql
    assert "%example.com" not in public_sql
    assert "z@example.com" not in public_sql
    assert public_sql.count("***MASKED***") == 6
    assert "customer_id = 42" in public_sql

    alias_cases = (
        "WITH c(contact) AS (SELECT email FROM customers) "
        "SELECT contact FROM c WHERE contact='victim@example.com'",
        "SELECT q.contact FROM (SELECT email FROM customers) q(contact) "
        "WHERE q.contact='victim@example.com'",
        "SELECT q.contact FROM LATERAL (SELECT email FROM customers) q(contact) "
        "WHERE q.contact='victim@example.com'",
        "SELECT 'victim@example.com' AS email",
    )
    for alias_sql in alias_cases:
        rendered = redact_public_sql(alias_sql, ["email"], dialect="postgresql")
        assert rendered is not None
        assert "victim@example.com" not in rendered
        assert "***MASKED***" in rendered

    predicate_cases = (
        "SELECT 1 FROM customers WHERE starts_with(email, 'victim@example.com')",
        "SELECT 1 FROM customers WHERE email ~* 'victim@example.com'",
        "SELECT 1 FROM customers WHERE email OPERATOR(pg_catalog.~~) 'victim@example.com'",
        "SELECT 1 FROM customers WHERE strpos(email, 'victim@example.com') > 0",
    )
    for predicate_sql in predicate_cases:
        rendered = redact_public_sql(predicate_sql, ["email"], dialect="postgresql")
        assert rendered is not None
        assert "victim@example.com" not in rendered
        assert "***MASKED***" in rendered

    expression_cases = (
        "SELECT starts_with(email, 'victim@example.com') FROM users",
        "SELECT email || ':victim@example.com' FROM users",
        "SELECT DISTINCT ON (starts_with(email, 'victim@example.com')) id FROM users",
        "SELECT id FROM users GROUP BY starts_with(email, 'victim@example.com')",
        "SELECT id FROM users ORDER BY starts_with(email, 'victim@example.com')",
        "SELECT row_number() OVER (PARTITION BY starts_with(email, 'victim@example.com') "
        "ORDER BY strpos(email, 'victim@example.com')) FROM users",
    )
    for expression_sql in expression_cases:
        rendered = redact_public_sql(expression_sql, ["email"], dialect="postgresql")
        assert rendered is not None
        assert "victim@example.com" not in rendered
        assert "***MASKED***" in rendered

    table_function_cases = (
        "SELECT x.email FROM jsonb_to_recordset('[{\"email\":\"victim@example.com\"}]') "
        "AS x(email text) WHERE x.email='victim@example.com'",
        "SELECT x.email FROM customers c CROSS JOIN "
        "jsonb_to_recordset('[{\"email\":\"victim@example.com\"}]') AS x(email text) "
        "WHERE x.email='victim@example.com'",
        "SELECT x.email FROM customers c, "
        "jsonb_to_recordset('[{\"email\":\"victim@example.com\"}]') AS x(email text) "
        "WHERE x.email='victim@example.com'",
    )
    for table_function_sql in table_function_cases:
        rendered = redact_public_sql(
            table_function_sql, ["email"], dialect="postgresql",
        )
        assert rendered is not None
        assert "victim@example.com" not in rendered
        assert rendered.count("***MASKED***") >= 2

    recursive = redact_public_sql_payload({
        "feedback": {
            "corrected_sql": "SELECT email FROM customers WHERE email='victim@example.com'",
            "workflow": {
                "candidate_sql": "SELECT email FROM customers WHERE email='victim@example.com'",
            },
        },
        "evaluation": {
            "expected": {"sql": "SELECT email FROM customers WHERE email='victim@example.com'"},
            "actual": {
                "semantic_sql": "SELECT email FROM customers WHERE email='victim@example.com'",
                "generated_sql": "SELECT email FROM customers WHERE email='victim@example.com'",
                "error_code": "QUERY_EXECUTION_ERROR",
                "error_message": "driver echoed victim@example.com",
            },
        },
    }, ["email"], dialect="postgresql")
    assert "victim@example.com" not in str(recursive)

    explain_plan = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Total Cost": 12.5,
            "Filter": "(email = 'victim@example.com'::text)",
            "Output": ["email", "'victim@example.com'::text AS contact"],
            "Plans": [{
                "Node Type": "Index Scan",
                "Index Cond": "(email = 'victim@example.com'::text)",
            }],
        },
        "query_block": {
            "table": {
                "table_name": "customers",
                "attached_condition": "customers.email = 'victim@example.com'",
            },
        },
    }
    public_plan = redact_public_explain_plan_payload(explain_plan, ["email"])
    assert "victim@example.com" not in str(public_plan)
    assert public_plan["Plan"]["Node Type"] == "Seq Scan"
    assert public_plan["Plan"]["Total Cost"] == 12.5
    assert public_plan["Plan"]["Filter"] == "***MASKED***"
    assert public_plan["Plan"]["Output"] == ["***MASKED***", "***MASKED***"]
    assert public_plan["Plan"]["Plans"][0]["Index Cond"] == "***MASKED***"
    assert public_plan["query_block"]["table"]["attached_condition"] == "***MASKED***"

    public_snapshot = redact_public_sql_payload(
        {"result_snapshot": {"rows": [{"plan": explain_plan}]}},
        ["email"],
        dialect="postgresql",
    )
    assert "victim@example.com" not in str(public_snapshot)
    assert public_snapshot["result_snapshot"]["rows"][0]["plan"]["Plan"][
        "Node Type"
    ] == "Seq Scan"
    opaque_table_function_cases = (
        "SELECT j.value AS payload FROM users u "
        "CROSS JOIN LATERAL jsonb_each_text(to_jsonb(u)) AS j WHERE j.key = 'email'",
        "SELECT j.value AS payload FROM users u "
        "CROSS JOIN LATERAL jsonb_each_text(to_jsonb(u)) AS j(key, value) WHERE j.key = 'email'",
        "SELECT j.value AS payload FROM users u "
        "CROSS JOIN LATERAL unnest(ARRAY[u.email]) AS j(value)",
        "SELECT j.value AS payload FROM users u "
        "CROSS JOIN jsonb_each_text(to_jsonb(u)) AS j(key, value) WHERE j.key = 'email'",
        "SELECT j.value AS payload FROM users u, "
        "jsonb_each_text(to_jsonb(u)) AS j(key, value) WHERE j.key = 'email'",
    )
    for sql in opaque_table_function_cases:
        assert sensitive_output_columns(
            sql, ["payload"], ["email"], dialect="postgresql",
        ) == ["payload"]


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
    if " AS contact" in normalized_sql:
        rows = [{"contact": "buyer@example.com"}]
    else:
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
    assert run["execution"]["rows"][0]["email"] == "***MASKED***"

    alias = client.post("/api/v1/data-workspace/sql/execute", json={
        "datasource_id": datasource_id,
        "sql": "SELECT email AS contact FROM finance.orders",
        "row_limit": 20,
    })
    assert alias.status_code == 201
    assert alias.json()["execution"]["rows"][0]["contact"] == "***MASKED***"
    assert alias.json()["execution"]["masked_columns"] == ["contact"]

    explained = client.post("/api/v1/data-workspace/sql/explain", json={
        "datasource_id": datasource_id, "sql": sql, "row_limit": 20,
    })
    assert explained.status_code == 201
    assert explained.json()["execution"]["rows"][0]["plan"]["Node Type"] == "Limit"

    history = client.get(f"/api/v1/data-workspace/sql/history?datasource_id={datasource_id}")
    assert history.status_code == 200
    assert history.json()["total"] == 4

    replay = client.post(f"/api/v1/data-workspace/sql/history/{run['id']}/replay")
    assert replay.status_code == 201
    assert replay.json()["operation"] == "REPLAY"

    verified = client.post(f"/api/v1/data-workspace/sql/history/{run['id']}/verify", json={"owner_name": "SQL Analyst"})
    assert verified.status_code == 201
    assert verified.json()["status"] == "VERIFIED"
    assert verified.json()["result_signature"] == "a" * 64
    saved_answer = db_session.get(VerifiedAnswer, verified.json()["answer_id"])
    assert saved_answer is not None
    assert "_sensitive_columns_snapshot" not in str(saved_answer.sql_plan)


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
