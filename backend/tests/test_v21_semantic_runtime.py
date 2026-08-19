from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.config import Settings
from app.query.contracts import LinkedObject, QueryContext, SecurityPolicy
from app.query.sql_guard import SqlGuard
from app.semantic_runtime import SemanticRuntime, SemanticRuntimeError
from app.semantic_runtime.contracts import SemanticQuery


def benchmark_context(workspace_id: str = "workspace-a") -> QueryContext:
    entities = [
        {"id": name, "name": name, "source_table": name, "primary_key": key, "time_dimension": time}
        for name, key, time in [
            ("fact_sales", "order_id", "order_date"), ("fact_payment", "payment_id", "invoice_date"),
            ("dim_region", "region_id", None), ("dim_product", "product_id", None),
            ("dim_customer", "customer_id", None),
        ]
    ]
    metrics = [
        {"id": name, "name": name, "label": label, "description": label, "expression": expression, "aggregation": aggregation, "filters": []}
        for name, label, expression, aggregation in [
            ("net_sales", "净销售额", "fact_sales.net_amount - fact_sales.refund_amount", "SUM"),
            ("net_profit", "净利润", "fact_sales.profit_amount - fact_sales.refund_amount", "SUM"),
            ("valid_orders", "有效订单数", "fact_sales.order_id", "COUNT"),
            ("active_customers", "活跃客户", "fact_sales.customer_id", "COUNT_DISTINCT"),
            ("refund_amount", "退款金额", "fact_sales.refund_amount", "SUM"),
            ("cancelled_orders", "取消订单数", "fact_sales.order_id", "COUNT"),
            ("outstanding_amount", "未结应收", "fact_payment.outstanding_amount", "SUM"),
        ]
    ]
    dimensions = [
        {"id": name, "name": name, "label": label, "source_column": source, "type": kind}
        for name, label, source, kind in [
            ("region", "地区", "dim_region.region_group", "STRING"),
            ("product", "产品", "dim_product.product_name", "STRING"),
            ("category", "品类", "dim_product.category", "STRING"),
            ("customer", "客户", "dim_customer.customer_name", "STRING"),
            ("customer_tier", "客户等级", "dim_customer.customer_tier", "STRING"),
            ("month", "月份", "fact_sales.order_date", "TIME"),
            ("status", "订单状态", "fact_sales.order_status", "STRING"),
            ("aging_bucket", "账龄", "fact_payment.aging_bucket", "STRING"),
            ("tenant", "租户", "fact_sales.tenant_id", "NUMBER"),
        ]
    ]
    relationships = [
        {"id": right, "left_entity": "fact_sales", "right_entity": right, "join_type": "LEFT", "join_keys": [{"left": key, "right": key}], "cardinality": "MANY_TO_ONE"}
        for right, key in [("dim_region", "region_id"), ("dim_product", "product_id"), ("dim_customer", "customer_id")]
    ]
    tables = [
        LinkedObject(object_type="table", object_id=name, name=name, label=name, qualified_name=f"chatbi_benchmark_v21.{name}", score=0.2)
        for name in ["fact_sales", "fact_payment", "dim_region", "dim_product", "dim_customer"]
    ]
    columns = [
        LinkedObject(object_type="column", object_id=name, name=name.split(".")[-1], label=name, qualified_name=name, score=0.2)
        for name in [
            "fact_sales.net_amount", "fact_sales.refund_amount", "fact_sales.order_date", "fact_sales.tenant_id",
            "dim_region.region_group", "dim_product.category", "dim_customer.customer_name", "fact_payment.aging_bucket",
        ]
    ]
    allowed_columns = {
        "fact_sales": ["tenant_id", "order_id", "order_date", "customer_id", "product_id", "region_id", "discount_rate", "net_amount", "profit_amount", "refund_amount", "order_status"],
        "fact_payment": ["tenant_id", "payment_id", "invoice_date", "aging_bucket", "outstanding_amount"],
        "dim_region": ["region_id", "region_group"],
        "dim_product": ["product_id", "product_name", "category"],
        "dim_customer": ["customer_id", "customer_name", "customer_tier"],
    }
    return QueryContext(
        workspace_id=workspace_id, workspace_name=workspace_id, datasource_id="benchmark", datasource_name="10M",
        dialect="postgresql", schema_name="chatbi_benchmark_v21", semantic_model_id="semantic-10m",
        semantic_model_name="10M Benchmark", semantic_model_version=1, entities=entities,
        candidate_tables=tables, candidate_columns=columns, metrics=metrics, dimensions=dimensions,
        relationships=relationships, business_terms=[
            {"id": "sales", "term": "销售额", "synonyms": ["营收", "收入"], "definition": "净销售额", "mapped_object": "metric.net_sales"},
        ],
        now=datetime(2026, 8, 18, tzinfo=timezone.utc), row_limit=100, token_budget=6000, estimated_tokens=1000,
        security_policy=SecurityPolicy(
            allowed_schemas=["chatbi_benchmark_v21"], allowed_tables=sorted(allowed_columns),
            allowed_columns=allowed_columns, row_limit=100, timeout_ms=8000,
        ),
    )


CASES = [
    ("租户 1 在 2025-07 的净销售额是多少？", {"net_sales"}, set(), True, True),
    ("租户 1 2025年净销售额和净利润", {"net_sales", "net_profit"}, set(), True, True),
    ("租户 1 2025年按地区统计销售额", {"net_sales"}, {"region"}, True, True),
    ("租户 1 2025年按产品统计销售额前5", {"net_sales"}, {"product"}, True, True),
    ("租户 1 2025年按客户统计销售额前5", {"net_sales"}, {"customer"}, True, True),
    ("租户 1 2025年销售额月度趋势", {"net_sales"}, {"month"}, True, True),
    ("租户 1 2025年销售额同比", {"net_sales"}, {"month"}, True, True),
    ("租户 1 2025年销售额环比", {"net_sales"}, {"month"}, True, True),
    ("租户 1 2025年按品类销售额前10", {"net_sales"}, {"category"}, True, True),
    ("租户 1 2025年地区销售贡献度", {"net_sales"}, {"region"}, True, True),
    ("租户 1 2025年退款金额", {"refund_amount"}, set(), True, True),
    ("租户 1 2025年取消订单数", {"cancelled_orders"}, set(), True, True),
    ("租户 1 2025年空折扣订单销售额", {"net_sales"}, set(), True, True),
    ("租户 1 2025年按客户等级统计销售额", {"net_sales"}, {"customer_tier"}, True, True),
    ("租户 1 2025年未结应收", {"outstanding_amount"}, set(), True, True),
    ("租户 1 2025年按账龄统计应收余额", {"outstanding_amount"}, {"aging_bucket"}, True, True),
    ("租户 2 2025年销售额异常趋势", {"net_sales"}, {"month"}, True, True),
    ("租户 7 在 2025-02 的活跃客户数", {"active_customers"}, set(), True, True),
]


@pytest.mark.parametrize(("question", "metrics", "dimensions", "has_time", "has_filter"), CASES)
def test_day1_semantic_runtime_produces_traceable_guarded_plan(question, metrics, dimensions, has_time, has_filter):
    context = benchmark_context()
    runtime = SemanticRuntime(Settings(_env_file=None, semantic_runtime_mode="wren"))
    plan, trace = runtime.plan(question=question, context=context)
    assert set(plan.metrics) == metrics
    assert set(plan.dimensions) == dimensions
    assert bool(plan.time_range) is has_time
    assert bool(plan.filters) is has_filter
    assert trace.call_chain == ["OpenChatBI", "SuperSonic", "WrenAI", "SQLGlot", "QueryExecutor", "ResultOracle"]
    assert trace.openchatbi_called and trace.supersonic_called and trace.wren_called
    assert trace.schema_linking.state_history == [
        "START", "CATALOG_RETRIEVING", "HYBRID_RETRIEVAL", "SCHEMA_LINKED", "END",
    ]
    assert trace.wren_mdl.mapping_coverage == 1.0
    assert trace.wren_dry_plan.status == "READY"
    guarded = SqlGuard().validate(plan.generated_sql, dialect="postgresql", policy=context.security_policy)
    assert guarded.allowed is True, guarded.issues
    if "同比" in question:
        assert "LAG(net_sales, 12)" in plan.generated_sql
        assert "comparison_rate" in plan.generated_sql
    if "环比" in question:
        assert "LAG(net_sales, 1)" in plan.generated_sql
        assert "comparison_rate" in plan.generated_sql


def test_invalid_relation_is_blocked_with_structured_error():
    runtime = SemanticRuntime(Settings(_env_file=None, semantic_runtime_mode="wren"))
    with pytest.raises(SemanticRuntimeError) as error:
        runtime.plan(question="租户 1 查询客户和无效关系的销售额", context=benchmark_context())
    assert error.value.payload == {
        "code": "INVALID_RELATION", "stage": "supersonic_corrector",
        "message": "请求的实体关系不在已发布语义模型中", "retryable": False,
    }


def test_wren_dry_plan_returns_structured_error_for_unknown_model():
    runtime = SemanticRuntime(Settings(_env_file=None, semantic_runtime_mode="wren"))
    context = benchmark_context()
    mdl = runtime.wren.compile_mdl(context)
    semantic_query = SemanticQuery(
        metrics=["net_sales"], dimensions=[], filters=[], time_range=None,
        relationships=[{"left_entity": "fact_sales", "right_entity": "secret_payroll"}],
        confidence=0.9, evidence=["negative-test"],
    )
    dry_plan = runtime.wren.dry_plan(semantic_query=semantic_query, mdl=mdl)
    assert dry_plan.status == "ERROR"
    assert dry_plan.structured_error == {
        "code": "WREN_MODEL_NOT_FOUND", "stage": "dry_plan",
        "models": ["secret_payroll"], "retryable": False,
    }
    with pytest.raises(SemanticRuntimeError) as error:
        runtime.wren.translate(
            question="negative", context=context,
            semantic_query=semantic_query, dry_plan=dry_plan,
        )
    assert error.value.payload["code"] == "WREN_MODEL_NOT_FOUND"


def test_ambiguous_question_requires_clarification_and_keeps_evidence():
    runtime = SemanticRuntime(Settings(_env_file=None, semantic_runtime_mode="wren"))
    _, trace = runtime.plan(question="销售情况怎么样", context=benchmark_context())
    assert trace.schema_linking.clarification_required is True
    assert trace.semantic_query.clarification_required is True
    assert trace.wren_dry_plan.status == "CLARIFICATION_REQUIRED"
    assert trace.semantic_query.evidence


def test_workspace_cache_isolation_and_local_rollback():
    runtime = SemanticRuntime(Settings(_env_file=None, semantic_runtime_mode="wren"))
    _, trace_a = runtime.plan(question="2025年销售额", context=benchmark_context("workspace-a"))
    _, trace_b = runtime.plan(question="2025年销售额", context=benchmark_context("workspace-b"))
    assert runtime.openchatbi.cache_scopes() == {"workspace-a", "workspace-b"}
    assert trace_a.schema_linking.workspace_id == "workspace-a"
    assert trace_b.schema_linking.workspace_id == "workspace-b"
    assert trace_a.schema_linking.cache_scope != trace_b.schema_linking.cache_scope

    role_context = benchmark_context("workspace-a").model_copy(update={
        "cache_role": "ANALYST",
        "knowledge_version": "knowledge-v2",
        "data_version": "data-v3",
        "input_signature": "input-v4",
    })
    _, role_trace = runtime.plan(question="2025年销售额", context=role_context)
    cache_scope = role_trace.schema_linking.cache_scope
    for token in ("workspace:workspace-a", "role:ANALYST", "v1", "knowledge:knowledge-v2", "data:data-v3", "input:input-v4"):
        assert token in cache_scope
    assert role_trace.schema_linking.cache_scope != trace_a.schema_linking.cache_scope

    _, unauthorized = runtime.plan(question="查询 secret_payroll 中的工资", context=benchmark_context("workspace-a"))
    recalled = {item.qualified_name or item.name for item in unauthorized.schema_linking.candidates}
    assert all("secret_payroll" not in item for item in recalled)

    rollback = SemanticRuntime(Settings(_env_file=None, semantic_runtime_mode="local"))
    plan, trace = rollback.plan(question="2025年按地区统计收入", context=benchmark_context())
    assert trace.mode == "local"
    assert trace.wren_called is False
    assert plan.provider != "wren-clean-room-runtime"


def test_openchatbi_schema_linking_recall_at_five_meets_gate():
    runtime = SemanticRuntime(Settings(_env_file=None, semantic_runtime_mode="wren"))
    hits = total = 0
    misses = []
    for question, expected_metrics, expected_dimensions, _, _ in CASES:
        _, trace = runtime.plan(question=question, context=benchmark_context())
        candidates = trace.schema_linking.candidates
        metric_top5 = [item.name for item in candidates if item.object_type == "metric"][:5]
        dimension_top5 = [item.name for item in candidates if item.object_type == "dimension"][:5]
        total += len(expected_metrics) + len(expected_dimensions)
        hits += sum(item in metric_top5 for item in expected_metrics)
        hits += sum(item in dimension_top5 for item in expected_dimensions)
        misses.extend((question, "metric", item, metric_top5) for item in expected_metrics if item not in metric_top5)
        misses.extend((question, "dimension", item, dimension_top5) for item in expected_dimensions if item not in dimension_top5)
    assert hits / total >= 0.95, misses
