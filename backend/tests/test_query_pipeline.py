import json
from datetime import datetime, timezone

import httpx
import pytest

from app.core.config import Settings
from app.evaluation import DANGEROUS_SQL_CASES
from app.query.context_builder import ContextBuilder
from app.query.contracts import (
    ExecutionResult,
    ExpectedResult,
    GuardResult,
    QueryContext,
    SecurityPolicy,
)
from app.query.nl2sql import DeterministicTestProvider, Nl2SqlRouter, OpenAICompatibleProvider, model_provider_catalog
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


DANGEROUS_SQL = DANGEROUS_SQL_CASES


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
            {"id": "m3", "name": "cost", "label": "成本", "description": "订单成本", "expression": "orders.cost", "aggregation": "SUM", "filters": []},
            {"id": "m4", "name": "profit", "label": "利润", "description": "订单利润", "expression": "orders.revenue - orders.cost", "aggregation": "SUM", "filters": []},
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


@pytest.mark.parametrize("dialect", ["postgresql", "mysql"])
def test_day4_planner_supports_growth_ratio_null_and_date_boundaries(dialect):
    provider = DeterministicTestProvider()
    context = semantic_context(dialect)

    quarter = provider.plan(question="2026年第一季度按地区统计收入和成本", context=context)
    assert quarter.metrics == ["revenue", "cost"]
    assert quarter.time_range.start == "2026-01-01"
    assert quarter.time_range.end_exclusive == "2026-04-01"

    natural_month = provider.plan(question="2026年2月按产品统计利润率", context=context)
    assert natural_month.metrics == ["profit_margin"]
    assert natural_month.time_range.kind == "NATURAL_MONTH"
    assert natural_month.time_range.end_exclusive == "2026-03-01"
    assert "NULLIF" in natural_month.generated_sql

    share = provider.plan(question="按地区统计收入贡献度", context=context)
    assert share.metrics == ["revenue_share"]
    assert "OVER" in share.generated_sql

    null_status = provider.plan(question="统计状态为空的订单量", context=context)
    assert null_status.filters[0].operator == "IS"
    assert null_status.filters[0].value is None
    assert "IS NULL" in null_status.generated_sql

    growth = provider.plan(question="按月统计收入环比", context=context)
    assert growth.metrics == ["revenue", "revenue_mom"]
    assert growth.dimensions == ["month"]
    assert "LAG" in growth.generated_sql
    guarded = SqlGuard().validate(growth.generated_sql, dialect=dialect, policy=policy())
    assert guarded.allowed is True, guarded.issues

    yoy = provider.plan(question="华南今年收入同比去年", context=context)
    assert yoy.metrics == ["revenue", "revenue_yoy"]
    assert "JOIN" in yoy.generated_sql and "region_name" in yoy.generated_sql
    assert "LAG(revenue, 12)" in yoy.generated_sql
    assert "WHERE month" in yoy.generated_sql
    guarded = SqlGuard().validate(yoy.generated_sql, dialect=dialect, policy=policy())
    assert guarded.allowed is True, guarded.issues


@pytest.mark.parametrize(
    ("provider_id", "secret_field", "expected_url", "auth_header", "max_tokens_field"),
    [
        ("kimi", "kimi_api_key", "https://api.moonshot.cn/v1/chat/completions", "authorization", "max_completion_tokens"),
        ("mimo", "mimo_api_key", "https://api.xiaomimimo.com/v1/chat/completions", "api-key", "max_completion_tokens"),
        ("deepseek", "deepseek_api_key", "https://api.deepseek.com/chat/completions", "authorization", "max_tokens"),
    ],
)
def test_named_provider_uses_safe_provider_specific_contract(
    provider_id, secret_field, expected_url, auth_header, max_tokens_field,
):
    secret = f"{provider_id}-test-secret"
    settings = Settings(_env_file=None, model_provider=provider_id, **{secret_field: secret})
    router = Nl2SqlRouter(settings=settings)
    assert isinstance(router.provider, OpenAICompatibleProvider)

    expected = DeterministicTestProvider().plan(question="按地区统计收入", context=semantic_context())
    expected.provider = "untrusted-model-label"
    expected.semantic_model_id = "untrusted-model-id"
    expected.semantic_model_version = 999
    expected.limit = 5000
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        observed.update(url=str(request.url), payload=payload, headers=dict(request.headers))
        return httpx.Response(200, json={"choices": [{"message": {"content": expected.model_dump_json()}}]})

    router.provider.transport = httpx.MockTransport(handler)
    actual = router.plan(question="按地区统计收入", context=semantic_context())

    assert actual.provider == provider_id
    assert actual.semantic_model_id == semantic_context().semantic_model_id
    assert actual.semantic_model_version == semantic_context().semantic_model_version
    assert actual.limit == semantic_context().row_limit
    assert observed["url"] == expected_url
    assert observed["payload"]["thinking"] == {"type": "disabled"}
    assert observed["payload"][max_tokens_field] == 4096
    assert "temperature" not in observed["payload"]
    assert observed["payload"]["response_format"] == {"type": "json_object"}
    expected_auth = secret if auth_header == "api-key" else f"Bearer {secret}"
    assert observed["headers"][auth_header] == expected_auth


def test_provider_catalog_reports_configuration_without_exposing_secrets():
    settings = Settings(
        _env_file=None,
        model_provider="kimi",
        kimi_api_key="kimi-catalog-secret",
        mimo_api_key="mimo-catalog-secret",
        deepseek_api_key="deepseek-catalog-secret",
    )
    catalog = model_provider_catalog(settings)
    serialized = json.dumps(catalog)

    assert catalog["active_provider"] == "kimi"
    assert catalog["secrets_exposed"] is False
    assert {item["id"] for item in catalog["items"]} >= {"kimi", "mimo", "deepseek", "deterministic"}
    assert all(item["configured"] for item in catalog["items"] if item["id"] in {"kimi", "mimo", "deepseek"})
    assert "catalog-secret" not in serialized


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


def test_result_oracle_requires_all_metrics_and_rejects_duplicate_grain():
    context = semantic_context()
    plan = DeterministicTestProvider().plan(question="按地区统计收入和成本", context=context)
    guard = GuardResult(allowed=True, dialect="postgresql", normalized_sql="SELECT ...", statement_type="SELECT")
    missing_metric = ExecutionResult(
        status="SUCCEEDED", columns=["region", "revenue"], column_types=["text", "numeric"],
        rows=[{"region": "华东", "revenue": 100.0}], row_count=1, datasource_id="d",
        dialect="postgresql", normalized_sql="SELECT ...", result_signature="missing",
    )
    result = ResultOracle().verify(plan=plan, guard=guard, execution=missing_metric)
    assert result.status == "MISMATCH"
    assert next(item for item in result.checks if item.name == "metric_columns").passed is False

    duplicate = ExecutionResult(
        status="SUCCEEDED", columns=["region", "revenue", "cost"], column_types=["text", "numeric", "numeric"],
        rows=[
            {"region": "华东", "revenue": 100.0, "cost": 60.0},
            {"region": "华东", "revenue": 50.0, "cost": 30.0},
        ],
        row_count=2, datasource_id="d", dialect="postgresql", normalized_sql="SELECT ...", result_signature="duplicate",
    )
    result = ResultOracle().verify(plan=plan, guard=guard, execution=duplicate)
    assert result.status == "MISMATCH"
    assert next(item for item in result.checks if item.name == "duplicate_grain").passed is False


def test_context_builder_link_score_is_deterministic():
    first = ContextBuilder()
    assert first.token_budget > 0
    from app.query.context_builder import _score

    score_a = _score("按地区统计销售额", ["收入", "销售额"])
    score_b = _score("按地区统计销售额", ["收入", "销售额"])
    assert score_a == score_b
    assert score_a[0] == 1.0
