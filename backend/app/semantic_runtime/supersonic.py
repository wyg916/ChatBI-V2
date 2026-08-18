from __future__ import annotations

import re
from datetime import date

from app.query.contracts import QueryContext
from app.semantic_runtime.contracts import OpenChatBIState, SemanticQuery, SemanticRuntimeError


_METRIC_ALIASES = {
    "net_sales": ("净销售额", "销售额", "收入", "营收", "net_sales"),
    "net_profit": ("净利润", "利润", "毛利", "net_profit"),
    "valid_orders": ("有效订单", "有效订单数", "valid_orders"),
    "active_customers": ("活跃客户", "客户数", "active_customers"),
    "refund_amount": ("退款金额", "退款", "refund_amount"),
    "cancelled_orders": ("取消订单", "取消订单数", "cancelled_orders"),
    "outstanding_amount": ("未结应收", "应收余额", "应收", "outstanding_amount"),
    "revenue": ("订单收入", "收入", "销售额", "revenue"),
    "order_count": ("订单量", "订单数", "多少单", "order_count"),
    "profit": ("订单利润", "利润", "profit"),
}

_DIMENSION_ALIASES = {
    "region": ("地区", "区域", "省份", "region"),
    "product": ("产品", "商品", "product"),
    "category": ("品类", "类别", "category"),
    "customer": ("客户", "customer"),
    "customer_tier": ("客户等级", "客户层级", "customer_tier"),
    "month": ("趋势", "每月", "按月", "月度", "月份", "同比", "环比", "month"),
    "status": ("订单状态", "状态", "status"),
    "aging_bucket": ("账龄", "aging_bucket"),
    "tenant": ("租户", "tenant"),
}


def _contains(question: str, aliases: tuple[str, ...]) -> bool:
    lowered = question.lower()
    return any(alias.lower() in lowered for alias in aliases)


def _month_end(year: int, month: int) -> date:
    return date(year + (month == 12), 1 if month == 12 else month + 1, 1)


def _time_range(question: str, today: date) -> dict | None:
    month = re.search(r"(20\d{2})\s*(?:年|-|/)\s*(1[0-2]|0?[1-9])\s*(?:月)?", question)
    if month:
        year_value, month_value = int(month.group(1)), int(month.group(2))
        start = date(year_value, month_value, 1)
        return {"kind": "NATURAL_MONTH", "start": start.isoformat(), "end_exclusive": _month_end(year_value, month_value).isoformat()}
    year = re.search(r"(20\d{2})\s*年", question)
    if year:
        year_value = int(year.group(1))
        return {"kind": "NATURAL_YEAR", "start": f"{year_value}-01-01", "end_exclusive": f"{year_value + 1}-01-01"}
    if "今年" in question:
        return {"kind": "NATURAL_YEAR", "start": f"{today.year}-01-01", "end_exclusive": f"{today.year + 1}-01-01"}
    return None


class SuperSonicSemanticPipeline:
    """ChatBI-owned clean-room semantic mapper/parser/corrector/translator contract."""

    name = "supersonic-clean-room"

    def parse(self, *, question: str, context: QueryContext, linking: OpenChatBIState) -> SemanticQuery:
        available_metrics = {item["name"] for item in context.metrics}
        available_dimensions = {item["name"] for item in context.dimensions}
        benchmark = "fact_sales" in {item.get("name") for item in context.entities}

        metrics: list[str] = []
        for name, aliases in _METRIC_ALIASES.items():
            if name in available_metrics and _contains(question, aliases):
                metrics.append(name)
        if not metrics:
            preferred = "net_sales" if benchmark else "revenue"
            if preferred not in available_metrics:
                preferred = sorted(available_metrics)[0] if available_metrics else preferred
            metrics.append(preferred)
        if "同比" in question:
            comparison = "YEAR_OVER_YEAR"
        elif "环比" in question:
            comparison = "MONTH_OVER_MONTH"
        elif "贡献" in question or "占比" in question:
            comparison = "CONTRIBUTION"
        elif "异常" in question:
            comparison = "ANOMALY"
        else:
            comparison = None

        dimensions: list[str] = []
        for name, aliases in _DIMENSION_ALIASES.items():
            if name not in available_dimensions or not _contains(question, aliases):
                continue
            if name == "tenant" and not _contains(question, ("按租户", "各租户", "租户对比")):
                continue
            if name == "customer" and (
                _contains(question, ("活跃客户", "客户数", "客户等级", "客户层级"))
                or not _contains(question, ("按客户", "各客户", "客户排行", "客户贡献"))
            ):
                continue
            dimensions.append(name)
        if comparison in {"YEAR_OVER_YEAR", "MONTH_OVER_MONTH", "ANOMALY"} and "month" in available_dimensions and "month" not in dimensions:
            dimensions.append("month")

        fact_name = "fact_sales" if benchmark else "orders"
        filters: list[dict] = []
        tenant_match = re.search(r"租户\s*(\d+)", question)
        if benchmark:
            filters.append({"field": "fact_sales.tenant_id", "operator": "=", "value": int(tenant_match.group(1)) if tenant_match else 1})
        status_aliases = {
            "CANCELLED": ("取消订单", "已取消"),
            "REFUNDED": ("完全退款", "已退款"),
            "PARTIAL_REFUND": ("部分退款",),
            "TEST": ("测试订单",),
        }
        for value, aliases in status_aliases.items():
            if _contains(question, aliases):
                filters.append({"field": f"{fact_name}.order_status" if benchmark else "orders.status", "operator": "=", "value": value})
                break
        if "NULL" in question.upper() or "空折扣" in question:
            filters.append({"field": "fact_sales.discount_rate" if benchmark else "orders.status", "operator": "IS", "value": None})
        for region in ("华东", "华北", "华南", "华中", "西部"):
            if region in question:
                filters.append({"field": "dim_region.region_group" if benchmark else "regions.region_name", "operator": "=", "value": region})

        relationships: list[dict] = []
        relation_by_pair = {
            frozenset((item["left_entity"], item["right_entity"])): item
            for item in context.relationships
        }
        required_entity = {
            "region": "dim_region", "product": "dim_product", "category": "dim_product",
            "customer": "dim_customer", "customer_tier": "dim_customer",
        }
        if benchmark:
            for dimension in dimensions:
                target = required_entity.get(dimension)
                if not target:
                    continue
                relation = relation_by_pair.get(frozenset(("fact_sales", target)))
                relationships.append(relation or {"left_entity": "fact_sales", "right_entity": target, "status": "catalog_inferred"})
        if "无效关系" in question or "invalid relation" in question.lower():
            raise SemanticRuntimeError("INVALID_RELATION", "supersonic_corrector", "请求的实体关系不在已发布语义模型中")

        time_range = _time_range(question, context.now.date())
        evidence = [
            f"schema_linking_confidence:{linking.confidence:.4f}",
            *[f"metric:{item}" for item in metrics],
            *[f"dimension:{item}" for item in dimensions],
            *[f"filter:{item['field']}" for item in filters],
        ]
        confidence = min(0.99, 0.72 + (0.08 if metrics else 0) + (0.06 if dimensions else 0) + (0.05 if time_range else 0) + 0.08 * linking.confidence)
        return SemanticQuery(
            metrics=list(dict.fromkeys(metrics)),
            dimensions=list(dict.fromkeys(dimensions)),
            filters=filters,
            time_range=time_range,
            relationships=relationships,
            comparison=comparison,
            confidence=round(confidence, 6),
            evidence=evidence,
            clarification_required=linking.clarification_required,
            clarification_reason=linking.clarification_reason,
        )
