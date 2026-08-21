from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from datetime import date, timedelta
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.model_gateway.configuration import (
    PROVIDER_DEFINITIONS,
    ProviderDefinition,
    ResolvedProvider,
    configured_providers,
    resolve_provider,
)
from app.model_gateway.contracts import BudgetMode, ModelCapability, ModelRequest, RequestContext
from app.model_gateway.service import ModelGateway
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


def _provider_values(settings: Settings, definition: ProviderDefinition) -> tuple[str, str, str]:
    resolved = resolve_provider(settings, definition)
    return resolved.base_url, resolved.api_key, resolved.model_name


def _contains(question: str, values: list[str]) -> bool:
    lowered = question.lower()
    return any(value.lower() in lowered for value in values)


def _time_range(question: str, now: date) -> QueryTimeRange | None:
    year_match = re.search(r"(20\d{2})\s*年", question)
    year = int(year_match.group(1)) if year_match else now.year
    month_match = re.search(r"(?:(20\d{2})\s*年)?\s*(1[0-2]|0?[1-9])\s*月", question)
    if month_match:
        month_year = int(month_match.group(1)) if month_match.group(1) else year
        month = int(month_match.group(2))
        start = date(month_year, month, 1)
        end = date(month_year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1)
        return QueryTimeRange(kind="NATURAL_MONTH", start=start.isoformat(), end_exclusive=end.isoformat())
    quarter_match = re.search(r"(?:第?\s*([一二三四1234])\s*季度|Q([1-4]))", question, re.IGNORECASE)
    if quarter_match:
        token = quarter_match.group(1) or quarter_match.group(2)
        quarter = {"一": 1, "二": 2, "三": 3, "四": 4}.get(token, int(token) if token.isdigit() else 1)
        start_month = (quarter - 1) * 3 + 1
        start = date(year, start_month, 1)
        end = date(year + (1 if quarter == 4 else 0), 1 if quarter == 4 else start_month + 3, 1)
        return QueryTimeRange(kind="QUARTER", start=start.isoformat(), end_exclusive=end.isoformat())
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
        if _contains(question, ["环比", "月环比"]):
            metrics = ["revenue", "revenue_mom"]
        elif _contains(question, ["同比", "年同比"]):
            metrics = ["revenue", "revenue_yoy"]
        elif _contains(question, ["收入占比", "营收占比", "收入贡献度", "营收贡献度"]) or (
            _contains(question, ["贡献度", "贡献率", "占比"])
            and _contains(question, ["收入", "营收", "销售额"])
        ):
            metrics = ["revenue_share"]
        elif _contains(question, ["利润率", "毛利率"]):
            metrics = ["profit_margin"]
        elif _contains(question, ["去重订单量", "不重复订单量"]):
            metrics = ["distinct_order_count"]
        elif _contains(question, ["客单价", "平均订单金额"]):
            metrics = ["avg_order_value"]
        else:
            if _contains(question, ["利润", "毛利"]) and "profit" not in metrics:
                metrics.append("profit")
            if not metrics:
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
            if name == "status" and _contains(question, ["状态为空", "状态是空", "NULL状态", "status is null"]):
                continue
            if _contains(question, aliases):
                dimensions.append(name)
        range_value = _time_range(question, context.now.date())
        if _contains(question, ["趋势", "每月", "按月", "月度", "月份", "环比", "同比"]):
            dimensions.append("month")
        dimensions = list(dict.fromkeys(dimensions))

        filters: list[QueryFilter] = []
        if _contains(question, ["状态为空", "状态是空", "NULL状态", "status is null"]):
            filters.append(QueryFilter(field="orders.status", operator="IS", value=None))
        elif _contains(question, ["退款", "已退款", "refunded"]):
            filters.append(QueryFilter(field="orders.status", operator="=", value="REFUNDED"))
        elif _contains(question, ["已支付", "支付成功", "已完成", "paid"]):
            filters.append(QueryFilter(field="orders.status", operator="=", value="PAID"))
        for region in ["华北", "华东", "华南", "西部", "华中"]:
            if region in question:
                filters.append(QueryFilter(field="regions.region_name", operator="=", value=region))
        for category in ["充电设备", "储能设备", "软件与终端", "服务"]:
            if category in question:
                filters.append(QueryFilter(field="products.category", operator="=", value=category))

        metric_order = ["revenue", "cost", "profit", "order_count", "avg_order_value"] + [
            item["name"] for item in context.metrics
        ] + [
            "revenue_share", "profit_margin", "distinct_order_count", "revenue_mom", "revenue_yoy",
        ]
        order_index: dict[str, int] = {}
        for name in metric_order:
            order_index.setdefault(name, len(order_index))
        metrics.sort(key=lambda item: (order_index.get(item, len(order_index)), item))

        sql, selected_tables, selected_columns, selected_entities, joins, group_by, order_by = self._render_sql(
            context=context, metrics=metrics, dimensions=dimensions, filters=filters,
            time_range=range_value, limit=_limit(question, context.row_limit), question=question,
        )
        warning = []
        known_metrics = set(metric_defs) | {
            "profit", "avg_order_value", "revenue_share", "profit_margin",
            "distinct_order_count", "revenue_mom", "revenue_yoy",
        }
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

        growth_metric = next((item for item in metrics if item in {"revenue_mom", "revenue_yoy"}), None)
        if growth_metric:
            return self._render_growth_sql(
                context=context, metric=growth_metric, time_range=time_range, filters=filters,
                limit=limit, table_name=table("orders"),
            )

        metric_sql = {
            "revenue": "SUM(o.revenue) AS revenue",
            "cost": "SUM(o.cost) AS cost",
            "order_count": "COUNT(o.order_id) AS order_count",
            "profit": "SUM(o.revenue - o.cost) AS profit",
            "avg_order_value": "AVG(o.revenue) AS avg_order_value",
            "distinct_order_count": "COUNT(DISTINCT o.order_id) AS distinct_order_count",
            "revenue_share": "ROUND(SUM(o.revenue) * 100.0 / NULLIF(SUM(SUM(o.revenue)) OVER (), 0), 4) AS revenue_share",
            "profit_margin": "ROUND(SUM(o.revenue - o.cost) * 100.0 / NULLIF(SUM(o.revenue), 0), 4) AS profit_margin",
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
            if metric in {"order_count", "distinct_order_count"}:
                selected_columns.append("orders.order_id")
            elif metric in {"profit", "profit_margin"}:
                selected_columns.extend(["orders.revenue", "orders.cost"])
            elif metric == "revenue_share":
                selected_columns.append("orders.revenue")
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
            if item.operator.upper() in {"IS", "IS NOT"} and item.value is None:
                where_parts.append(f"{alias}.{column} {item.operator.upper()} NULL")
            else:
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

    def _render_growth_sql(
        self,
        *,
        context: QueryContext,
        metric: str,
        time_range: QueryTimeRange | None,
        filters: list[QueryFilter],
        limit: int,
        table_name: str,
    ) -> tuple[str, list[str], list[str], list[str], list[dict[str, Any]], list[str], list[str]]:
        month_expression = (
            "DATE_TRUNC('month', o.order_date)" if context.dialect == "postgresql"
            else "DATE_FORMAT(o.order_date, '%Y-%m-01')"
        )
        where_parts: list[str] = []
        join_lines: list[str] = []
        joins: list[dict[str, Any]] = []
        selected_tables = ["orders"]
        selected_entities = ["orders"]
        selected_columns = ["orders.order_date", "orders.revenue"]
        aliases = {"orders": "o", "regions": "r", "products": "p", "customers": "c"}
        join_specs = {
            "regions": ("regions", "r", "r.region_id = o.region_id", "orders.region_id", "regions.region_id"),
            "products": ("products", "p", "p.product_id = o.product_id", "orders.product_id", "products.product_id"),
            "customers": ("customers", "c", "c.customer_id = o.customer_id", "orders.customer_id", "customers.customer_id"),
        }
        schema = context.schema_name

        def related_table(name: str) -> str:
            return f"{schema}.{name}" if schema and context.dialect == "postgresql" else name

        for item in filters:
            entity, column = item.field.split(".", 1)
            if entity in join_specs and entity not in selected_tables:
                table, alias, condition, left, right = join_specs[entity]
                join_lines.append(f"JOIN {related_table(table)} {alias} ON {condition}")
                selected_tables.append(entity)
                selected_entities.append(entity)
                selected_columns.extend([left, right])
                joins.append({"left": left, "right": right, "type": "INNER"})
            selected_columns.append(item.field)
            alias = aliases[entity]
            if item.operator.upper() in {"IS", "IS NOT"} and item.value is None:
                where_parts.append(f"{alias}.{column} {item.operator.upper()} NULL")
            else:
                escaped = str(item.value).replace("'", "''")
                where_parts.append(f"{alias}.{column} {item.operator} '{escaped}'")
        if time_range and time_range.start and time_range.end_exclusive:
            start = time_range.start
            if metric == "revenue_yoy":
                start_date = date.fromisoformat(str(start))
                start = start_date.replace(year=start_date.year - 1)
            if context.dialect == "postgresql":
                where_parts = [
                    *where_parts,
                    f"o.order_date >= DATE '{start}'",
                    f"o.order_date < DATE '{time_range.end_exclusive}'",
                ]
            else:
                where_parts = [
                    *where_parts,
                    f"o.order_date >= '{start}'",
                    f"o.order_date < '{time_range.end_exclusive}'",
                ]
        offset = 1 if metric == "revenue_mom" else 12
        lag = f"LAG(revenue, {offset}) OVER (ORDER BY month)"
        lines = [
            "WITH monthly AS (",
            f"  SELECT {month_expression} AS month, SUM(o.revenue) AS revenue",
            f"  FROM {table_name} o",
        ]
        lines.extend(f"  {line}" for line in join_lines)
        if where_parts:
            lines.append("  WHERE " + " AND ".join(where_parts))
        lines.extend([
            f"  GROUP BY {month_expression}",
            ")",
            "SELECT month, revenue,",
            f"  ROUND((revenue - {lag}) * 100.0 / NULLIF({lag}, 0), 4) AS {metric}",
            "FROM monthly",
        ])
        if time_range and time_range.start and time_range.end_exclusive:
            if context.dialect == "postgresql":
                lines.append(f"WHERE month >= DATE '{time_range.start}' AND month < DATE '{time_range.end_exclusive}'")
            else:
                lines.append(f"WHERE month >= '{time_range.start}' AND month < '{time_range.end_exclusive}'")
        lines.extend(["ORDER BY month ASC", f"LIMIT {limit}"])
        return (
            "\n".join(lines), selected_tables, list(dict.fromkeys(selected_columns)),
            selected_entities, joins, [month_expression], ["month ASC"],
        )


class OpenAICompatibleProvider(ModelProviderAdapter):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        provider_name: str = "openai-compatible",
        display_name: str = "OpenAI Compatible",
        auth_header: str = "Authorization",
        auth_prefix: str = "Bearer ",
        max_tokens_field: str = "max_tokens",
        request_options: dict[str, Any] | None = None,
        timeout_seconds: float = 30,
        transport: httpx.BaseTransport | None = None,
    ):
        self.name = provider_name
        self.display_name = display_name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.auth_header = auth_header
        self.auth_prefix = auth_prefix
        self.max_tokens_field = max_tokens_field
        self.request_options = request_options or {}
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def capabilities(self) -> dict[str, Any]:
        configured = bool(self.base_url and self.api_key and self.model_name)
        return {
            "provider": self.name,
            "runtime_available": configured,
            "configured": configured,
            "display_name": self.display_name,
            "model_name": self.model_name or None,
            "structured_output": True,
            "external_model": True,
            "protocol": "openai-chat-completions",
        }

    def generate(self, *, question: str, context: QueryContext) -> SQLPlan:
        if not self.capabilities()["configured"]:
            raise RuntimeError("OpenAI-compatible provider is not configured")
        messages = (
                {
                    "role": "system",
                    "content": (
                        "Return only one JSON object that validates against the supplied SQLPlan JSON Schema. "
                        "Use only authorized context objects. generated_sql must be exactly one read-only SELECT "
                        "or WITH ... SELECT statement. Never invent a table or column. "
                        f"SQLPlan JSON Schema: {json.dumps(SQLPlan.model_json_schema(), ensure_ascii=False)}"
                    ),
                },
                {"role": "user", "content": json.dumps({"question": question, "context": context.model_dump(mode="json")}, ensure_ascii=False)},
        )
        provider = ResolvedProvider(
            provider_id=self.name, display_name=self.display_name, base_url=self.base_url,
            api_key=self.api_key, model_name=self.model_name, auth_header=self.auth_header,
            auth_prefix=self.auth_prefix, max_tokens_field=self.max_tokens_field,
            request_options=self.request_options,
        )
        gateway = ModelGateway(
            Settings(_env_file=None, model_budget_mode="quality"),
            transport=self.transport, provider_overrides={self.name: provider}, sleeper=lambda _: None,
        )
        response = gateway.execute(
            ModelRequest(
                capability=ModelCapability.NL2SQL,
                messages=messages,
                requested_alias=self.name,
                json_mode=True,
                complexity_score=60,
                budget_mode=BudgetMode.QUALITY,
                max_output_tokens=4096,
            ),
            RequestContext(
                request_id=context.request_id,
                trace_id=context.trace_id,
                conversation_id=context.conversation_id,
                user_id=context.user_id,
                workspace_id=context.workspace_id,
                datasource_id=context.datasource_id,
                roles=frozenset({context.cache_role}),
                permission_hash=context.permission_hash,
                question=question,
                context_hash=context.input_signature or "none",
                budget_mode=BudgetMode.QUALITY,
            ),
        )
        plan = SQLPlan.model_validate_json(response.content)
        # Provider output is untrusted. Runtime identity and release-critical
        # context must come from the server-owned request, never model JSON.
        return plan.model_copy(update={
            "question": question,
            "dialect": context.dialect,
            "provider": self.name,
            "semantic_model_id": context.semantic_model_id,
            "semantic_model_version": context.semantic_model_version,
            "limit": min(plan.limit, context.row_limit),
            "model_trace": response.trace_payload(),
        })


class GatewayNl2SqlProvider(ModelProviderAdapter):
    name = "model-gateway"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.gateway = ModelGateway(settings)

    def capabilities(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "runtime_available": bool(self.gateway.providers),
            "configured": bool(self.gateway.providers),
            "structured_output": True,
            "external_model": True,
            "protocol": "chatbi-model-gateway-v1",
        }

    def generate(self, *, question: str, context: QueryContext) -> SQLPlan:
        messages = (
            {
                "role": "system",
                "content": (
                    "Return only one JSON object that validates against the supplied SQLPlan JSON Schema. "
                    "Use only authorized context objects. generated_sql must be exactly one read-only SELECT "
                    "or WITH ... SELECT statement. Never invent a table or column. "
                    f"SQLPlan JSON Schema: {json.dumps(SQLPlan.model_json_schema(), ensure_ascii=False)}"
                ),
            },
            {"role": "user", "content": json.dumps({"question": question, "context": context.model_dump(mode="json")}, ensure_ascii=False)},
        )
        response = self.gateway.execute(
            ModelRequest(
                capability=ModelCapability.NL2SQL, messages=messages, json_mode=True,
                complexity_score=60, budget_mode=BudgetMode(self.settings.model_budget_mode),
                thinking=True,
                max_output_tokens=4096,
            ),
            RequestContext(
                request_id=context.request_id, trace_id=context.trace_id,
                conversation_id=context.conversation_id, user_id=context.user_id,
                workspace_id=context.workspace_id, datasource_id=context.datasource_id,
                roles=frozenset({context.cache_role}), permission_hash=context.permission_hash,
                question=question, context_hash=context.input_signature or "none",
                budget_mode=BudgetMode(self.settings.model_budget_mode),
            ),
        )
        plan = SQLPlan.model_validate_json(response.content)
        return plan.model_copy(update={
            "question": question, "dialect": context.dialect,
            "provider": response.resolved_provider,
            "semantic_model_id": context.semantic_model_id,
            "semantic_model_version": context.semantic_model_version,
            "limit": min(plan.limit, context.row_limit),
            "model_trace": response.trace_payload(),
        })


def build_model_provider(settings: Settings | None = None) -> ModelProviderAdapter:
    settings = settings or get_settings()
    selected = settings.model_provider.strip().lower()
    if selected == "auto":
        return GatewayNl2SqlProvider(settings) if configured_providers(settings) else DeterministicTestProvider()
    for definition in PROVIDER_DEFINITIONS:
        if selected != definition.provider_id:
            continue
        base_url, api_key, model_name = _provider_values(settings, definition)
        if base_url and api_key and model_name:
            return OpenAICompatibleProvider(
                provider_name=definition.provider_id,
                display_name=definition.display_name,
                base_url=base_url,
                api_key=api_key,
                model_name=model_name,
                auth_header=definition.auth_header,
                auth_prefix=definition.auth_prefix,
                max_tokens_field=definition.max_tokens_field,
                request_options=definition.request_options,
            )
        break
    return DeterministicTestProvider()


def model_provider_catalog(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    selected = settings.model_provider.strip().lower()
    if selected == "auto":
        selected = "model-gateway" if configured_providers(settings) else "deterministic"
    entries: list[dict[str, Any]] = []
    selected_is_configured = selected in {"deterministic", "model-gateway"}
    for definition in PROVIDER_DEFINITIONS:
        base_url, api_key, model_name = _provider_values(settings, definition)
        configured = bool(base_url and api_key and model_name)
        selected_is_configured = selected_is_configured or (selected == definition.provider_id and configured)
        entries.append({
            "id": definition.provider_id,
            "display_name": definition.display_name,
            "model_name": model_name or None,
            "base_url": base_url or None,
            "configured": configured,
            "active": selected == definition.provider_id and configured,
            "external_model": True,
            "structured_output": True,
            "protocol": "openai-chat-completions",
            "credential_env": definition.credential_env,
        })
    if selected == "model-gateway":
        entries.append({
            "id": "model-gateway",
            "display_name": "ChatBI V1.3 Control Plane",
            "model_name": None,
            "base_url": None,
            "configured": True,
            "active": True,
            "external_model": False,
            "structured_output": True,
            "protocol": "chatbi-model-gateway-v1",
            "credential_env": None,
        })
    active_provider = selected if selected_is_configured else "deterministic"
    entries.append({
        "id": "deterministic",
        "display_name": "Local Semantic Runtime",
        "model_name": "deterministic-semantic-v1",
        "base_url": None,
        "configured": True,
        "active": active_provider == "deterministic",
        "external_model": False,
        "structured_output": True,
        "protocol": "local",
        "credential_env": None,
    })
    return {
        "active_provider": active_provider,
        "selection_strategy": "capability-complexity-cost" if active_provider == "model-gateway" else "fixed",
        "secrets_exposed": False,
        "items": entries,
    }


class Nl2SqlRouter(Nl2SqlEngine):
    def __init__(self, provider: ModelProviderAdapter | None = None, settings: Settings | None = None):
        self.provider = provider if provider is not None else build_model_provider(settings)

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
