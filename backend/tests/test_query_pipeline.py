import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.evaluation import DANGEROUS_SQL_CASES
from app.query.context_builder import ContextBuilder
from app.query.contracts import (
    ExecutionResult,
    ExpectedResult,
    GuardResult,
    LinkedObject,
    QueryContext,
    SecurityPolicy,
)
from app.query.nl2sql import (
    DeterministicTestProvider,
    GatewayNl2SqlProvider,
    Nl2SqlRouter,
    OpenAICompatibleProvider,
    _provider_output_contract_guidance,
    model_provider_catalog,
)
from app.model_gateway.service import ModelUnavailable
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


@pytest.mark.parametrize("dialect", ["postgresql", "mysql"])
def test_sql_guard_drops_only_ungrouped_provider_order_term(dialect):
    result = SqlGuard().validate(
        "SELECT r.region_name AS region, COUNT(o.order_id) AS order_count, "
        "SUM(o.revenue) AS revenue FROM demo_business.orders o "
        "JOIN demo_business.regions r ON r.region_id = o.region_id "
        "GROUP BY r.region_name ORDER BY revenue DESC, r.region_id ASC",
        dialect=dialect,
        policy=policy(),
    )

    assert result.allowed is True, result.issues
    assert "ORDER BY revenue DESC" in result.normalized_sql
    assert "r.region_id ASC" not in result.normalized_sql
    assert result.normalization_actions == ["DROP_UNGROUPED_ORDER_TERM:r.region_id"]


def test_sql_guard_keeps_order_term_that_is_grouped():
    result = SqlGuard().validate(
        "SELECT r.region_name AS region, COUNT(o.order_id) AS order_count, "
        "SUM(o.revenue) AS revenue FROM demo_business.orders o "
        "JOIN demo_business.regions r ON r.region_id = o.region_id "
        "GROUP BY r.region_name, r.region_id ORDER BY revenue DESC, r.region_id ASC",
        dialect="postgresql",
        policy=policy(),
    )

    assert result.allowed is True, result.issues
    assert "r.region_id ASC" in result.normalized_sql
    assert result.normalization_actions == []


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


def test_nl2sql_router_preserves_explicit_sql_before_external_provider() -> None:
    class NeverCalledProvider:
        @staticmethod
        def capabilities():
            return {"runtime_available": True}

        @staticmethod
        def generate(*, question, context):
            raise AssertionError("explicit SQL must not reach an external model")

    sql = "SELECT COUNT(*) AS revenue FROM demo_business.orders WHERE 1 = 0"
    plan = Nl2SqlRouter(provider=NeverCalledProvider()).plan(question=sql, context=semantic_context())

    assert plan.intent == "DIRECT_SQL"
    assert plan.generated_sql == sql
    assert plan.provider == "deterministic-semantic-v1"


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


def test_phase5_level0_planner_supports_multi_metric_dates_extremes_and_filters() -> None:
    context = semantic_context().model_copy(update={
        "candidate_columns": [
            LinkedObject(
                object_type="column", object_id="product-name", name="product_name", label="产品名称",
                qualified_name="products.product_name", score=1.0, evidence=["exact:储能柜"],
            ),
            LinkedObject(
                object_type="column", object_id="customer-type", name="customer_type", label="客户类型",
                qualified_name="customers.customer_type", score=1.0, evidence=["exact:企业"],
            ),
        ],
    })
    provider = DeterministicTestProvider()

    day = provider.plan(question="只统计2026年1月1日当天的订单量、收入和成本", context=context)
    assert day.metrics == ["order_count", "revenue", "cost"]
    assert day.time_range.start == "2026-01-01"
    assert day.time_range.end_exclusive == "2026-01-02"

    cross_month = provider.plan(
        question="统计2026年1月31日至2月2日跨月三天的订单量、收入和成本", context=context,
    )
    assert cross_month.time_range.start == "2026-01-31"
    assert cross_month.time_range.end_exclusive == "2026-02-03"

    extreme = provider.plan(
        question="找出单笔收入最大的一张订单，若并列取订单编号最小者", context=context,
    )
    assert extreme.dimensions == ["order_id"]
    assert "ORDER BY o.revenue DESC, o.order_id ASC" in extreme.generated_sql
    assert "LIMIT 1" in extreme.generated_sql

    filtered = provider.plan(
        question="2026年2月储能柜订单的订单量、收入和成本", context=context,
    )
    assert any(item.field == "products.product_name" and item.value == "储能柜" for item in filtered.filters)
    assert "p.product_name = '储能柜'" in filtered.generated_sql

    regional = provider.plan(
        question="2026年第一季度华东已支付订单的订单量、收入和成本", context=context,
    )
    assert not any(item.field == "products.product_name" for item in regional.filters)

    customer = provider.plan(question="统计企业客户的已支付订单量、收入和成本", context=context)
    assert customer.dimensions == []
    assert any(item.field == "customers.customer_type" and item.value == "企业" for item in customer.filters)
    assert "JOIN demo_business.customers" in customer.generated_sql

    ranged = provider.plan(
        question="退款且单笔收入大于等于1000小于2000的订单量、收入和成本", context=context,
    )
    assert ranged.metrics == ["order_count", "revenue", "cost"]

    fragment_category = provider.plan(
        question="2026 Q2 充电设备 品类 订单量 收入 成本", context=context,
    )
    assert fragment_category.dimensions == ["category"]
    assert any(item.field == "products.category" and item.value == "充电设备" for item in fragment_category.filters)

    filtered_category = provider.plan(
        question="汇总西部的软件与终端品类订单量、收入和成本", context=context,
    )
    assert filtered_category.dimensions == []
    assert any(item.field == "products.category" and item.value == "软件与终端" for item in filtered_category.filters)
    assert "o.revenue >= 1000" in ranged.generated_sql
    assert "o.revenue < 2000" in ranged.generated_sql


def test_provider_output_guidance_requires_annual_aggregate_rows_for_correlation() -> None:
    context = semantic_context().model_copy(update={
        "dimensions": [{
            "id": "d-order-date",
            "name": "order_date",
            "label": "订单日期",
            "source_column": "orders.order_date",
            "type": "DATE",
        }],
    })

    guidance = _provider_output_contract_guidance(
        "对2025与2026年度收入和成本汇总做Python相关性分析",
        context,
    )

    assert guidance["required_time_grain"] == {
        "grain": "YEAR",
        "canonical_dimension": "order_date",
        "row_shape": "one aggregated row per year",
        "allowed_ast": [
            "EXTRACT(YEAR FROM date_column)",
            "DATE_TRUNC('year', date_column)",
        ],
    }
    assert "do not return raw fact rows" in guidance["downstream_operation"]


@pytest.mark.parametrize(
    "question",
    ["收入怎么样？", "哪个最好？", "把它按那个维度分一下", "统计全部订单的量子利润", "按地区展示碳梦指数"],
)
def test_phase5_level0_unresolved_intents_fail_closed(question: str) -> None:
    with pytest.raises(ValueError, match="SEMANTIC_"):
        DeterministicTestProvider().plan(question=question, context=semantic_context())


def test_phase5_level0_explicit_follow_up_suggestion_remains_resolvable() -> None:
    plan = DeterministicTestProvider().plan(
        question="销售额 按月查看趋势怎么样？",
        context=semantic_context(),
    )

    assert plan.metrics == ["revenue"]
    assert plan.dimensions == ["month"]


@pytest.mark.parametrize("question", ["综合分析利润并结合成本口径给出经营洞察", "综合分析季度利润并解释利润与成本定义"])
def test_phase5_level0_profit_analysis_remains_resolvable(question: str) -> None:
    plan = DeterministicTestProvider().plan(question=question, context=semantic_context())
    assert "profit" in plan.metrics


@pytest.mark.parametrize(
    ("question", "expected_group", "expected_order"),
    [
        pytest.param(
            "按产品统计已退款订单量前5名",
            "GROUP BY p.product_name, p.product_id",
            "ORDER BY order_count DESC, p.product_id ASC",
            id="refunded-product-top5",
        ),
        pytest.param(
            "按客户统计订单量前5名",
            "GROUP BY c.customer_name, c.customer_id",
            "ORDER BY order_count DESC, c.customer_id ASC",
            id="customer-count-top5-boundary-tie",
        ),
        pytest.param(
            "按客户统计订单收入前5名",
            "GROUP BY c.customer_name, c.customer_id",
            "ORDER BY revenue DESC, c.customer_id ASC",
            id="customer-revenue-top5",
        ),
        pytest.param(
            "按产品按状态统计订单量",
            "GROUP BY p.product_name, p.product_id, o.status",
            "ORDER BY order_count DESC, p.product_id ASC, o.status ASC",
            id="product-status-count",
        ),
    ],
)
def test_grouped_business_queries_use_total_order_contract(
    question: str,
    expected_group: str,
    expected_order: str,
) -> None:
    plan = DeterministicTestProvider().plan(question=question, context=semantic_context())

    assert expected_group in plan.generated_sql
    assert expected_order in plan.generated_sql
    guarded = SqlGuard().validate(plan.generated_sql, dialect="postgresql", policy=policy())
    assert guarded.allowed is True, guarded.issues


def test_entity_primary_keys_precede_value_dimensions_in_stable_order() -> None:
    plan = DeterministicTestProvider().plan(
        question="按产品按状态统计订单量",
        context=semantic_context(),
    )

    assert plan.group_by == ["p.product_name", "p.product_id", "o.status"]
    assert plan.order_by == ["order_count DESC", "p.product_id ASC", "o.status ASC"]
    assert {"products.product_id", "orders.status"}.issubset(plan.selected_columns)

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
    settings = Settings(
        _env_file=None,
        model_provider=provider_id,
        provider_usage_unrestricted=True,
        **{secret_field: secret},
    )
    router = Nl2SqlRouter(settings=settings)
    assert isinstance(router.provider, OpenAICompatibleProvider)
    assert router.provider.settings.provider_usage_unrestricted is True

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


def test_gateway_uses_local_semantic_runtime_when_all_external_providers_are_disabled(monkeypatch):
    provider = GatewayNl2SqlProvider(Settings(
        _env_file=None,
        model_provider="auto",
        mimo_api_key="configured-but-runtime-disabled",
    ))

    def no_enabled_provider(*_args, **_kwargs):
        raise ModelUnavailable("No configured model provider is available")

    monkeypatch.setattr(provider.gateway, "execute", no_enabled_provider)
    plan = provider.generate(question="按地区统计收入", context=semantic_context())

    assert plan.provider == "deterministic-semantic-v1"
    assert plan.model_trace["fallback_from"] == "model-gateway"
    assert plan.model_trace["fallback_reason"] == "NO_ENABLED_PROVIDER"
    assert any("Local Semantic Runtime" in warning for warning in plan.warnings)


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


def test_result_oracle_accepts_semantic_relationship_join_shape() -> None:
    plan = DeterministicTestProvider().plan(question="按地区统计收入", context=semantic_context()).model_copy(update={
        "joins": [{
            "left_entity": "orders",
            "right_entity": "regions",
            "join_type": "INNER",
            "join_keys": [{"left": "region_id", "right": "region_id"}],
        }],
    })
    guard = GuardResult(allowed=True, dialect="postgresql", normalized_sql="SELECT ...", statement_type="SELECT")
    execution = ExecutionResult(
        status="SUCCEEDED", columns=["region", "revenue"], column_types=["text", "numeric"],
        rows=[{"region": "华东", "revenue": 100.0}], row_count=1, datasource_id="d",
        dialect="postgresql", normalized_sql="SELECT ...", result_signature="semantic-join",
    )

    result = ResultOracle().verify(plan=plan, guard=guard, execution=execution)

    assert result.status == "PASSED"
    assert next(item for item in result.checks if item.name == "join_semantics").passed is True


def test_result_oracle_reconciles_unique_qualified_selected_tables_with_provider_entities() -> None:
    plan = DeterministicTestProvider().plan(question="按地区统计收入", context=semantic_context()).model_copy(update={
        "selected_tables": ["demo_business.orders", "demo_business.regions"],
        "joins": [{
            "left_entity": "orders",
            "right_entity": "regions",
            "join_type": "INNER",
            "join_keys": [{"left": "region_id", "right": "region_id"}],
        }],
    })
    guard = GuardResult(allowed=True, dialect="postgresql", normalized_sql="SELECT ...", statement_type="SELECT")
    execution = ExecutionResult(
        status="SUCCEEDED", columns=["region", "revenue"], column_types=["text", "numeric"],
        rows=[{"region": "华东", "revenue": 100.0}], row_count=1, datasource_id="d",
        dialect="postgresql", normalized_sql="SELECT ...", result_signature="qualified-semantic-join",
    )

    result = ResultOracle().verify(plan=plan, guard=guard, execution=execution)

    assert result.status == "PASSED"
    assert next(item for item in result.checks if item.name == "join_semantics").passed is True


def test_result_oracle_rejects_ambiguous_unqualified_provider_entity() -> None:
    plan = DeterministicTestProvider().plan(question="按地区统计收入", context=semantic_context()).model_copy(update={
        "selected_tables": ["tenant_a.orders", "tenant_b.orders", "demo_business.regions"],
        "joins": [{
            "left_entity": "orders",
            "right_entity": "regions",
            "join_type": "INNER",
            "join_keys": [{"left": "region_id", "right": "region_id"}],
        }],
    })
    guard = GuardResult(allowed=True, dialect="postgresql", normalized_sql="SELECT ...", statement_type="SELECT")
    execution = ExecutionResult(
        status="SUCCEEDED", columns=["region", "revenue"], column_types=["text", "numeric"],
        rows=[{"region": "华东", "revenue": 100.0}], row_count=1, datasource_id="d",
        dialect="postgresql", normalized_sql="SELECT ...", result_signature="ambiguous-semantic-join",
    )

    result = ResultOracle().verify(plan=plan, guard=guard, execution=execution)

    assert result.status == "MISMATCH"
    assert next(item for item in result.checks if item.name == "join_semantics").passed is False


def test_result_oracle_accepts_validated_provider_join_shape() -> None:
    plan = DeterministicTestProvider().plan(question="按地区统计收入", context=semantic_context()).model_copy(update={
        "joins": [{
            "left_table": "orders",
            "right_table": "regions",
            "join_type": "INNER",
            "left_column": "region_id",
            "right_column": "region_id",
        }],
    })
    guard = GuardResult(allowed=True, dialect="postgresql", normalized_sql="SELECT ...", statement_type="SELECT")
    execution = ExecutionResult(
        status="SUCCEEDED", columns=["region", "revenue"], column_types=["text", "numeric"],
        rows=[{"region": "华东", "revenue": 100.0}], row_count=1, datasource_id="d",
        dialect="postgresql", normalized_sql="SELECT ...", result_signature="provider-join",
    )

    result = ResultOracle().verify(plan=plan, guard=guard, execution=execution)

    assert result.status == "PASSED"
    assert next(item for item in result.checks if item.name == "join_semantics").passed is True


def test_result_oracle_accepts_provider_table_join_keys_shape() -> None:
    plan = DeterministicTestProvider().plan(question="按地区统计收入", context=semantic_context()).model_copy(update={
        "joins": [{
            "left_table": "orders",
            "right_table": "regions",
            "join_type": "INNER",
            "join_keys": [{"left": "region_id", "right": "region_id"}],
        }],
    })
    guard = GuardResult(allowed=True, dialect="postgresql", normalized_sql="SELECT ...", statement_type="SELECT")
    execution = ExecutionResult(
        status="SUCCEEDED", columns=["region", "revenue"], column_types=["text", "numeric"],
        rows=[{"region": "华东", "revenue": 100.0}], row_count=1, datasource_id="d",
        dialect="postgresql", normalized_sql="SELECT ...", result_signature="provider-table-join-keys",
    )

    result = ResultOracle().verify(plan=plan, guard=guard, execution=execution)

    assert result.status == "PASSED"
    assert next(item for item in result.checks if item.name == "join_semantics").passed is True


def test_result_oracle_accepts_provider_table_join_on_shape() -> None:
    plan = DeterministicTestProvider().plan(question="按地区统计收入", context=semantic_context()).model_copy(update={
        "joins": [{
            "left_table": "orders",
            "right_table": "regions",
            "join_type": "INNER",
            "on": "orders.region_id = regions.region_id",
        }],
    })
    guard = GuardResult(allowed=True, dialect="postgresql", normalized_sql="SELECT ...", statement_type="SELECT")
    execution = ExecutionResult(
        status="SUCCEEDED", columns=["region", "revenue"], column_types=["text", "numeric"],
        rows=[{"region": "华东", "revenue": 100.0}], row_count=1, datasource_id="d",
        dialect="postgresql", normalized_sql="SELECT ...", result_signature="provider-table-join-on",
    )

    result = ResultOracle().verify(plan=plan, guard=guard, execution=execution)

    assert result.status == "PASSED"
    assert next(item for item in result.checks if item.name == "join_semantics").passed is True


@pytest.mark.parametrize(
    "join",
    [
        {
            "left_table": "orders", "right_table": "secret_payroll",
            "left_column": "region_id", "right_column": "region_id",
        },
        {
            "left_table": "orders", "right_table": "regions",
            "left_column": "", "right_column": "region_id",
        },
        {
            "left_table": "orders", "right_table": "regions",
            "join_keys": [{"left": "region_id", "right": ""}],
        },
        {
            "left_table": "orders", "right_table": "regions",
            "on": "orders.region_id = regions.region_id OR 1 = 1",
        },
        {
            "left_table": "orders", "right_table": "regions",
            "on": "region_id = region_id",
        },
    ],
)
def test_result_oracle_rejects_incomplete_or_unselected_provider_join_shape(join: dict[str, Any]) -> None:
    plan = DeterministicTestProvider().plan(question="按地区统计收入", context=semantic_context()).model_copy(
        update={"joins": [join]},
    )
    guard = GuardResult(allowed=True, dialect="postgresql", normalized_sql="SELECT ...", statement_type="SELECT")
    execution = ExecutionResult(
        status="SUCCEEDED", columns=["region", "revenue"], column_types=["text", "numeric"],
        rows=[{"region": "华东", "revenue": 100.0}], row_count=1, datasource_id="d",
        dialect="postgresql", normalized_sql="SELECT ...", result_signature="provider-join-rejected",
    )

    result = ResultOracle().verify(plan=plan, guard=guard, execution=execution)

    assert result.status == "MISMATCH"
    assert next(item for item in result.checks if item.name == "join_semantics").passed is False


def test_context_builder_link_score_is_deterministic():
    first = ContextBuilder()
    assert first.token_budget > 0
    from app.query.context_builder import _score

    score_a = _score("按地区统计销售额", ["收入", "销售额"])
    score_b = _score("按地区统计销售额", ["收入", "销售额"])
    assert score_a == score_b
    assert score_a[0] == 1.0
