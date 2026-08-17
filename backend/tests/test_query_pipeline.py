from datetime import datetime, timezone

import pytest

from app.query.context_builder import ContextBuilder
from app.query.contracts import (
    ExecutionResult,
    ExpectedResult,
    GuardResult,
    QueryContext,
    SecurityPolicy,
)
from app.query.nl2sql import DeterministicTestProvider
from app.query.oracle import ResultOracle
from app.query.sql_guard import SqlGuard


def policy() -> SecurityPolicy:
    return SecurityPolicy(
        allowed_schemas=["demo_business", "chatbi_demo_business"],
        allowed_tables=["orders", "regions", "products", "customers"],
        allowed_columns={
            "orders": ["order_id", "customer_id", "product_id", "region_id", "order_date", "revenue", "cost", "status"],
            "regions": ["region_id", "region_name"],
            "products": ["product_id", "product_name", "category"],
            "customers": ["customer_id", "customer_name", "customer_type"],
        },
        row_limit=100,
        timeout_ms=5000,
    )


DANGEROUS_SQL = [
    ("postgresql", "INSERT INTO demo_business.orders(order_id) VALUES (999)"),
    ("postgresql", "UPDATE demo_business.orders SET revenue = 0"),
    ("postgresql", "DELETE FROM demo_business.orders"),
    ("postgresql", "DROP TABLE demo_business.orders"),
    ("postgresql", "ALTER TABLE demo_business.orders ADD COLUMN hacked int"),
    ("postgresql", "CREATE TABLE demo_business.hacked(id int)"),
    ("postgresql", "TRUNCATE TABLE demo_business.orders"),
    ("postgresql", "GRANT ALL ON demo_business.orders TO public"),
    ("postgresql", "REVOKE SELECT ON demo_business.orders FROM public"),
    ("postgresql", "COPY demo_business.orders TO '/tmp/orders.csv'"),
    ("postgresql", "SET ROLE postgres"),
    ("postgresql", "SELECT pg_read_file('/etc/passwd')"),
    ("postgresql", "SELECT pg_read_binary_file('/etc/passwd')"),
    ("postgresql", "SELECT pg_ls_dir('/')"),
    ("postgresql", "SELECT lo_import('/tmp/file')"),
    ("postgresql", "SELECT dblink_exec('x', 'DELETE FROM orders')"),
    ("postgresql", "SELECT * FROM pg_catalog.pg_user"),
    ("postgresql", "SELECT * FROM information_schema.tables"),
    ("postgresql", "SELECT * FROM demo_business.orders"),
    ("postgresql", "SELECT secret FROM demo_business.orders"),
    ("postgresql", "SELECT order_id FROM private.orders"),
    ("postgresql", "SELECT order_id FROM demo_business.unknown_table"),
    ("postgresql", "SELECT order_id FROM demo_business.orders; DELETE FROM demo_business.orders"),
    ("mysql", "INSERT INTO orders(order_id) VALUES (999)"),
    ("mysql", "UPDATE orders SET revenue = 0"),
    ("mysql", "DELETE FROM orders"),
    ("mysql", "DROP TABLE orders"),
    ("mysql", "TRUNCATE TABLE orders"),
    ("mysql", "LOAD DATA INFILE '/tmp/x' INTO TABLE orders"),
    ("mysql", "SELECT LOAD_FILE('/etc/passwd')"),
    ("mysql", "SELECT SLEEP(10)"),
    ("mysql", "SELECT BENCHMARK(1000000, SHA2('x', 256))"),
    ("mysql", "SELECT * FROM mysql.user"),
    ("mysql", "SELECT order_id FROM information_schema.tables"),
    ("mysql", "SELECT order_id INTO OUTFILE '/tmp/x' FROM orders"),
    ("mysql", "SELECT order_id FROM unknown_table"),
    ("mysql", "SELECT password_hash FROM customers"),
    ("mysql", "SELECT order_id FROM orders; DROP TABLE orders"),
]


@pytest.mark.parametrize(("dialect", "sql"), DANGEROUS_SQL)
def test_sql_guard_blocks_dangerous_sql(dialect, sql):
    result = SqlGuard().validate(sql, dialect=dialect, policy=policy())
    assert result.allowed is False, sql
    assert result.issues


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [
        ("postgresql", "SELECT o.region_id, SUM(o.revenue) AS revenue FROM demo_business.orders o GROUP BY o.region_id"),
        ("postgresql", "WITH paid AS (SELECT order_id, revenue FROM demo_business.orders WHERE status = 'PAID') SELECT COUNT(order_id) AS order_count FROM paid"),
        ("mysql", "SELECT o.status, COUNT(o.order_id) AS order_count FROM orders o GROUP BY o.status ORDER BY order_count DESC"),
    ],
)
def test_sql_guard_allows_authorized_select_and_caps_limit(dialect, sql):
    result = SqlGuard().validate(sql, dialect=dialect, policy=policy())
    assert result.allowed is True, result.issues
    assert result.applied_limit == 100
    assert "LIMIT 100" in result.normalized_sql.upper()


def semantic_context(dialect: str = "postgresql") -> QueryContext:
    return QueryContext(
        workspace_id="w", workspace_name="Workspace", datasource_id="d", datasource_name="Demo",
        dialect=dialect, schema_name="demo_business" if dialect == "postgresql" else "chatbi_demo_business",
        semantic_model_id="m", semantic_model_name="经营分析", semantic_model_version=2,
        entities=[{"id": "e1", "name": "orders", "source_table": "orders", "primary_key": "order_id"}],
        candidate_tables=[], candidate_columns=[],
        metrics=[
            {"id": "m1", "name": "revenue", "label": "收入", "description": "订单收入", "expression": "orders.revenue", "aggregation": "SUM", "filters": []},
            {"id": "m2", "name": "order_count", "label": "订单量", "description": "订单数量", "expression": "orders.order_id", "aggregation": "COUNT", "filters": []},
        ],
        dimensions=[{"id": "d1", "name": "region", "label": "地区", "source_column": "regions.region_name", "type": "STRING"}],
        relationships=[],
        business_terms=[{"id": "t1", "term": "收入", "synonyms": ["营收", "销售额"], "definition": "收入", "mapped_object": "metric.revenue"}],
        now=datetime(2026, 8, 17, tzinfo=timezone.utc), row_limit=100, token_budget=6000,
        estimated_tokens=200, security_policy=policy(),
    )


@pytest.mark.parametrize("dialect", ["postgresql", "mysql"])
def test_deterministic_provider_builds_structured_join_plan(dialect):
    plan = DeterministicTestProvider().plan(
        question="近30天按地区统计已支付订单收入前3名",
        context=semantic_context(dialect),
    )
    assert plan.metrics == ["revenue"]
    assert plan.dimensions == ["region"]
    assert plan.limit == 3
    assert plan.time_range.kind == "LAST_30_DAYS"
    assert plan.joins[0]["right"] == "regions.region_id"
    assert "JOIN" in plan.generated_sql
    assert "PAID" in plan.generated_sql
    assert plan.dialect == dialect


def test_result_oracle_compares_values_not_sql_text():
    plan = DeterministicTestProvider().plan(question="按地区统计收入", context=semantic_context())
    guard = GuardResult(allowed=True, dialect="postgresql", normalized_sql="SELECT ...", statement_type="SELECT")
    execution = ExecutionResult(
        status="SUCCEEDED", columns=["region", "revenue"], column_types=["text", "numeric"],
        rows=[{"region": "华东", "revenue": 100.001}, {"region": "华北", "revenue": 80.0}],
        row_count=2, duration_ms=3, datasource_id="d", dialect="postgresql", normalized_sql="different SQL",
        result_signature="actual",
    )
    expected = ExpectedResult(
        columns=["region", "revenue"],
        rows=[{"region": "华北", "revenue": 80}, {"region": "华东", "revenue": 100}],
        tolerance=0.001,
    )
    result = ResultOracle().verify(plan=plan, guard=guard, execution=execution, expected=expected)
    assert result.status == "PASSED"
    assert result.mismatch_count == 0


def test_context_builder_link_score_is_deterministic():
    first = ContextBuilder()
    assert first.token_budget > 0
    from app.query.context_builder import _score

    score_a = _score("按地区统计销售额", ["收入", "销售额"])
    score_b = _score("按地区统计销售额", ["收入", "销售额"])
    assert score_a == score_b
    assert score_a[0] == 1.0
