from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from datetime import date, timedelta
from typing import Any

import httpx

from app.core.config import get_settings
from app.query.contracts import QueryContext, QueryFilter, QueryTimeRange, SQLPlan


class ModelProviderAdapter(ABC):
    name: str

    @abstractmethod
    def generate(self, *, question: str, context: QueryContext) -> SQLPlan:
        raise NotImplementedError

    @abstractmethod
    def capabilities(self) -> dict[str, Any]:
        raise NotImplementedError


class Nl2SqlEngine(ABC):
    @abstractmethod
    def plan(self, *, question: str, context: QueryContext) -> SQLPlan:
        raise NotImplementedError


def _contains(question: str, values: list[str]) -> bool:
    lowered = question.lower()
    return any(value.lower() in lowered for value in values)


def _time_range(question: str, now: date) -> QueryTimeRange | None:
    year_match = re.search(r"(20\d{2})\s*年", question)
    year = int(year_match.group(1)) if year_match else now.year
    if "上半年" in question:
        return QueryTimeRange(kind="HALF_YEAR", start=f"{year}-01-01", end_exclusive=f"{year}-07-01")
    if "下半年" in question:
        return QueryTimeRange(kind="HALF_YEAR", start=f"{year}-07-01", end_exclusive=f"{year + 1}-01-01")
    if year_match:
        return QueryTimeRange(kind="YEAR", start=f"{year}-01-01", end_exclusive=f"{year + 1}-01-01")
    day_match = re.search(r"(?:近|最近|过去)\s*(\d+)\s*天", question)
    if day_match:
        days = min(366, max(1, int(day_match.group(1))))
        start = now - timedelta(days=days - 1)
        return QueryTimeRange(kind=f"LAST_{days}_DAYS", start=start.isoformat(), end_exclusive=(now + timedelta(days=1)).isoformat())
    if "本月" in question:
        start = now.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return QueryTimeRange(kind="CURRENT_MONTH", start=start.isoformat(), end_exclusive=end.isoformat())
    if "今年" in question:
        return QueryTimeRange(kind="CURRENT_YEAR", start=f"{now.year}-01-01", end_exclusive=f"{now.year + 1}-01-01")
    return None


def _limit(question: str, default: int) -> int:
    match = re.search(r"(?:top|前|最高的?|最低的?)\s*(\d+)", question, re.IGNORECASE)
    if match:
        return min(default, max(1, int(match.group(1))))
    return default


class DeterministicTestProvider(ModelProviderAdapter, Nl2SqlEngine):
    """Semantic-rule runtime for development, tests, and offline demos.

    It composes a plan from linked semantic objects and generic analytical intent;
    it never maps a complete question string to a fixed SQL statement.
    """

    name = "deterministic-semantic-v1"

    def capabilities(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "runtime_available": True,
            "dialects": ["postgresql", "mysql"],
            "structured_output": True,
            "external_model": False,
        }

    def generate(self, *, question: str, context: QueryContext) -> SQLPlan:
        return self.plan(question=question, context=context)

    def plan(self, *, question: str, context: QueryContext) -> SQLPlan:
        stripped = question.strip().rstrip(";")
        if re.match(r"^(SELECT|WITH|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|COPY|CALL|GRANT|REVOKE|SET|USE|LOAD)\b", stripped, re.IGNORECASE):
            return SQLPlan(
                question=question, intent="DIRECT_SQL", dialect=context.dialect, provider=self.name,
                semantic_model_id=context.semantic_model_id, semantic_model_version=context.semantic_model_version,
                selected_entities=[], selected_tables=[], selected_columns=[], metrics=[], dimensions=[], joins=[], filters=[],
                group_by=[], order_by=[], limit=context.row_limit, generated_sql=stripped,
                confidence=0.45, warnings=["Direct SQL request requires full AST authorization"],
            )

        metric_defs = {item["name"]: item for item in context.metrics}
        term_targets: dict[str, str] = {}
        for term in context.business_terms:
            mapped = str(term.get("mapped_object", ""))
            if mapped.startswith("metric."):
                for token in [term["term"], *term.get("synonyms", [])]:
                    term_targets[str(token).lower()] = mapped.split(".", 1)[1]

        metrics: list[str] = []
        lowered = question.lower()
        for token, metric_name in sorted(term_targets.items(), key=lambda pair: (-len(pair[0]), pair[0])):
            if token and token in lowered and metric_name in metric_defs and metric_name not in metrics:
                metrics.append(metric_name)
        for name, definition in metric_defs.items():
            if _contains(question, [name, definition.get("label", ""), definition.get("description", "")]) and name not in metrics:
                metrics.append(name)
        if _contains(question, ["利润", "毛利"]):
            metrics = ["profit"]
        elif _contains(question, ["客单价", "平均订单金额"]):
            metrics = ["avg_order_value"]
        elif not metrics:
            metrics = ["order_count"] if _contains(question, ["多少单", "订单数", "订单量"]) else ["revenue"]

        dimensions: list[str] = []
        dimension_aliases = [
            ("region", ["地区", "区域", "省份", "region"]),
            ("product", ["产品", "商品", "product"]),
            ("category", ["品类", "类别", "category"]),
            ("customer", ["客户", "用户", "customer"]),
            ("customer_type", ["客户类型", "用户类型"]),
            ("status", ["状态", "status"]),
        ]
        for name, aliases in dimension_aliases:
            if name == "customer" and _contains(question, ["客户类型", "用户类型"]):
                continue
            if name == "product" and _contains(question, ["产品类别", "商品类别", "品类"]):
                continue
            if _contains(question, aliases):
                dimensions.append(name)
        range_value = _time_range(question, context.now.date())
        if _contains(question, ["趋势", "每月", "按月", "月度", "月份"]):
            dimensions.append("month")
        dimensions = list(dict.fromkeys(dimensions))

        filters: list[QueryFilter] = []
        if _contains(question, ["退款", "已退款", "refunded"]):
            filters.append(QueryFilter(field="orders.status", operator="=", value="REFUNDED"))
        elif _contains(question, ["已支付", "支付成功", "已完成", "paid"]):
            filters.append(QueryFilter(field="orders.status", operator="=", value="PAID"))
        for region in ["华北", "华东", "华南", "西部", "华中"]:
            if region in question:
                filters.append(QueryFilter(field="regions.region_name", operator="=", value=region))
        for category in ["充电设备", "储能设备", "软件与终端", "服务"]:
            if category in question:
                filters.append(QueryFilter(field="products.category", operator="=", value=category))

        sql, selected_tables, selected_columns, selected_entities, joins, group_by, order_by = self._render_sql(
            context=context, metrics=metrics, dimensions=dimensions, filters=filters,
            time_range=range_value, limit=_limit(question, context.row_limit), question=question,
        )
        warning = []
        known_metrics = set(metric_defs) | {"profit", "avg_order_value"}
        if any(metric not in known_metrics for metric in metrics):
            warning.append("One or more metrics use local derived definitions")
        confidence = min(0.96, 0.68 + min(0.18, len(context.linking_trace) * 0.025) + (0.05 if dimensions else 0))
        return SQLPlan(
            question=question, intent="ANALYTICAL_QUERY", dialect=context.dialect, provider=self.name,
            semantic_model_id=context.semantic_model_id, semantic_model_version=context.semantic_model_version,
            selected_entities=selected_entities, selected_tables=selected_tables, selected_columns=selected_columns,
            metrics=metrics, dimensions=dimensions, joins=joins, filters=filters, time_range=range_value,
            group_by=group_by, order_by=order_by, limit=_limit(question, context.row_limit),
            generated_sql=sql, confidence=confidence, warnings=warning,
        )

    def _render_sql(
        self, *, context: QueryContext, metrics: list[str], dimensions: list[str], filters: list[QueryFilter],
        time_range: QueryTimeRange | None, limit: int, question: str,
    ) -> tuple[str, list[str], list[str], list[str], list[dict[str, Any]], list[str], list[str]]:
        dialect = context.dialect
        schema = context.schema_name

        def table(name: str) -> str:
            return f"{schema}.{name}" if schema and dialect == "postgresql" else name

        metric_sql = {
            "revenue": "SUM(o.revenue) AS revenue",
            "cost": "SUM(o.cost) AS cost",
            "order_count": "COUNT(o.order_id) AS order_count",
            "profit": "SUM(o.revenue - o.cost) AS profit",
            "avg_order_value": "AVG(o.revenue) AS avg_order_value",
        }
        dimension_sql = {
            "region": ("r.region_name AS region", "r.region_name", "regions.region_name"),
            "product": ("p.product_name AS product", "p.product_name", "products.product_name"),
            "category": ("p.category AS category", "p.category", "products.category"),
            "customer": ("c.customer_name AS customer", "c.customer_name", "customers.customer_name"),
            "customer_type": ("c.customer_type AS customer_type", "c.customer_type", "customers.customer_type"),
            "status": ("o.status AS status", "o.status", "orders.status"),
            "month": (
                "DATE_TRUNC('month', o.order_date) AS month" if dialect == "postgresql" else "DATE_FORMAT(o.order_date, '%Y-%m-01') AS month",
                "DATE_TRUNC('month', o.order_date)" if dialect == "postgresql" else "DATE_FORMAT(o.order_date, '%Y-%m-01')",
                "orders.order_date",
            ),
        }
        select_parts: list[str] = []
        group_parts: list[str] = []
        selected_columns: list[str] = []
        for dimension in dimensions:
            if dimension in dimension_sql:
                select_value, group_value, source = dimension_sql[dimension]
                select_parts.append(select_value)
                group_parts.append(group_value)
                selected_columns.append(source)
        for metric in metrics:
            select_parts.append(metric_sql.get(metric, metric_sql["revenue"]))
            if metric == "order_count":
                selected_columns.append("orders.order_id")
            elif metric == "profit":
                selected_columns.extend(["orders.revenue", "orders.cost"])
            else:
                selected_columns.append("orders.revenue" if metric == "avg_order_value" else f"orders.{metric}")

        selected_tables = ["orders"]
        selected_entities = ["orders"]
        joins: list[dict[str, Any]] = []
        join_lines: list[str] = []
        if "region" in dimensions or any(item.field.startswith("regions.") for item in filters):
            selected_tables.append("regions")
            selected_entities.append("regions")
            join_lines.append(f"JOIN {table('regions')} r ON r.region_id = o.region_id")
            joins.append({"left": "orders.region_id", "right": "regions.region_id", "type": "INNER"})
        if any(item in dimensions for item in ("product", "category")) or any(item.field.startswith("products.") for item in filters):
            selected_tables.append("products")
            selected_entities.append("products")
            join_lines.append(f"JOIN {table('products')} p ON p.product_id = o.product_id")
            joins.append({"left": "orders.product_id", "right": "products.product_id", "type": "INNER"})
        if any(item in dimensions for item in ("customer", "customer_type")):
            selected_tables.append("customers")
            selected_entities.append("customers")
            join_lines.append(f"JOIN {table('customers')} c ON c.customer_id = o.customer_id")
            joins.append({"left": "orders.customer_id", "right": "customers.customer_id", "type": "INNER"})

        where_parts: list[str] = []
        for item in filters:
            alias = {"orders": "o", "regions": "r", "products": "p", "customers": "c"}[item.field.split(".")[0]]
            column = item.field.split(".")[1]
            escaped = str(item.value).replace("'", "''")
            where_parts.append(f"{alias}.{column} {item.operator} '{escaped}'")
        if time_range and time_range.start and time_range.end_exclusive:
            if dialect == "postgresql":
                where_parts.extend([
                    f"o.order_date >= DATE '{time_range.start}'",
                    f"o.order_date < DATE '{time_range.end_exclusive}'",
                ])
            else:
                where_parts.extend([
                    f"o.order_date >= '{time_range.start}'",
                    f"o.order_date < '{time_range.end_exclusive}'",
                ])
            selected_columns.append("orders.order_date")

        descending = not _contains(question, ["最低", "最少", "升序"])
        metric_alias = metrics[0] if metrics else "revenue"
        order_parts = [f"{metric_alias} {'DESC' if descending else 'ASC'}"] if dimensions else []
        if "month" in dimensions:
            order_parts = ["month ASC"] + ([f"{metric_alias} DESC"] if len(dimensions) > 1 else [])

        lines = ["SELECT", "  " + ",\n  ".join(select_parts), f"FROM {table('orders')} o"]
        lines.extend(join_lines)
        if where_parts:
            lines.append("WHERE " + "\n  AND ".join(where_parts))
        if group_parts:
            lines.append("GROUP BY " + ", ".join(group_parts))
        if order_parts:
            lines.append("ORDER BY " + ", ".join(order_parts))
        lines.append(f"LIMIT {limit}")
        return "\n".join(lines), selected_tables, list(dict.fromkeys(selected_columns)), selected_entities, joins, group_parts, order_parts


class OpenAICompatibleProvider(ModelProviderAdapter):
    name = "openai-compatible"

    def __init__(self, *, base_url: str, api_key: str, model_name: str, timeout_seconds: float = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def capabilities(self) -> dict[str, Any]:
        configured = bool(self.base_url and self.api_key and self.model_name)
        return {
            "provider": self.name,
            "runtime_available": configured,
            "configured": configured,
            "model_name": self.model_name or None,
            "structured_output": True,
        }

    def generate(self, *, question: str, context: QueryContext) -> SQLPlan:
        if not self.capabilities()["configured"]:
            raise RuntimeError("OpenAI-compatible provider is not configured")
        payload = {
            "model": self.model_name,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Return only a JSON SQLPlan. Use only authorized context objects and one read-only SELECT."},
                {"role": "user", "content": json.dumps({"question": question, "context": context.model_dump(mode="json")}, ensure_ascii=False)},
            ],
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return SQLPlan.model_validate_json(content)


class Nl2SqlRouter(Nl2SqlEngine):
    def __init__(self, provider: ModelProviderAdapter | None = None):
        settings = get_settings()
        if provider is not None:
            self.provider = provider
        elif settings.model_provider == "openai-compatible" and settings.model_base_url and settings.model_api_key and settings.model_name:
            self.provider = OpenAICompatibleProvider(
                base_url=settings.model_base_url, api_key=settings.model_api_key, model_name=settings.model_name,
            )
        else:
            self.provider = DeterministicTestProvider()

    def capabilities(self) -> dict[str, Any]:
        return self.provider.capabilities()

    def plan(self, *, question: str, context: QueryContext) -> SQLPlan:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                plan = self.provider.generate(question=question, context=context)
                if plan.dialect != context.dialect:
                    raise ValueError("Provider returned a plan for the wrong dialect")
                if plan.semantic_model_id != context.semantic_model_id:
                    raise ValueError("Provider returned a plan for the wrong semantic model")
                if attempt:
                    plan.repair_count = attempt
                return plan
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                last_error = exc
                if isinstance(self.provider, DeterministicTestProvider):
                    break
        raise RuntimeError(f"NL2SQL structured output invalid: {last_error}") from last_error
