from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from calendar import monthrange
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
    full_dates = list(re.finditer(r"(20\d{2})\s*年\s*(1[0-2]|0?[1-9])\s*月\s*(3[01]|[12]?\d)\s*日", question))
    if full_dates:
        first = full_dates[0]
        start = date(int(first.group(1)), int(first.group(2)), int(first.group(3)))
        range_tail = question[first.end():]
        short_end = re.search(
            r"至\s*(?:(20\d{2})\s*年\s*)?(1[0-2]|0?[1-9])\s*月\s*(3[01]|[12]?\d)\s*日",
            range_tail,
        )
        if short_end:
            end_year = int(short_end.group(1)) if short_end.group(1) else start.year
            end_month = int(short_end.group(2))
            if short_end.group(1) is None and end_month < start.month:
                end_year += 1
            end = date(end_year, end_month, int(short_end.group(3))) + timedelta(days=1)
            return QueryTimeRange(kind="EXPLICIT_DATE_RANGE", start=start.isoformat(), end_exclusive=end.isoformat())
        if "之后" in range_tail:
            end = date(start.year + (1 if start.month == 12 else 0), 1 if start.month == 12 else start.month + 1, 1)
            return QueryTimeRange(kind="DATE_THROUGH_MONTH_END", start=start.isoformat(), end_exclusive=end.isoformat())
        return QueryTimeRange(
            kind="NATURAL_DAY", start=start.isoformat(), end_exclusive=(start + timedelta(days=1)).isoformat(),
        )

    year_match = re.search(r"(20\d{2})\s*年", question)
    year = int(year_match.group(1)) if year_match else now.year
    last_day_match = re.search(r"(?:(20\d{2})\s*年)?\s*(1[0-2]|0?[1-9])\s*月(?:的)?最后一天", question)
    if last_day_match:
        last_day_year = int(last_day_match.group(1)) if last_day_match.group(1) else year
        last_day_month = int(last_day_match.group(2))
        start = date(last_day_year, last_day_month, monthrange(last_day_year, last_day_month)[1])
        return QueryTimeRange(
            kind="NATURAL_MONTH_LAST_DAY",
            start=start.isoformat(),
            end_exclusive=(start + timedelta(days=1)).isoformat(),
        )
    if _contains(question, ["按自然年", "按年", "逐年", "年份", "年度"]) and len(re.findall(r"20\d{2}", question)) > 1:
        return None
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

        self._require_resolvable_intent(question=question, context=context)

        metric_defs = {item["name"]: item for item in context.metrics}
        term_targets: dict[str, str] = {}
        for term in context.business_terms:
            mapped = str(term.get("mapped_object", ""))
            if mapped.startswith("metric."):
                for token in [term["term"], *term.get("synonyms", [])]:
                    term_targets[str(token).lower()] = mapped.split(".", 1)[1]

        metric_positions: dict[str, tuple[int, int]] = {}
        lowered = question.lower()
        metric_text = re.sub(
            r"按[^，,。；;]*?(?:升序|降序)(?:排列)?",
            "",
            lowered,
        )
        for token, metric_name in sorted(term_targets.items(), key=lambda pair: (-len(pair[0]), pair[0])):
            position = metric_text.rfind(token)
            if token and position >= 0 and metric_name in metric_defs:
                candidate = (position, -len(token))
                if metric_name not in metric_positions or candidate < metric_positions[metric_name]:
                    metric_positions[metric_name] = candidate
        for name, definition in metric_defs.items():
            for token in [name, definition.get("label", ""), definition.get("description", "")]:
                normalized = str(token or "").lower()
                position = metric_text.rfind(normalized) if normalized else -1
                if position >= 0:
                    candidate = (position, -len(normalized))
                    if name not in metric_positions or candidate < metric_positions[name]:
                        metric_positions[name] = candidate
        metrics = sorted(metric_positions, key=lambda item: (*metric_positions[item], item))
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
        elif _contains(question, ["最大购买数量", "最高购买数量", "最大订购数量"]) and _contains(
            question, ["订单数", "订单量", "多少单"],
        ):
            metrics = ["max_quantity", "order_count"]
        else:
            if re.search(r"收入.*减.*成本.*利润", question):
                metrics = ["profit"]
            elif _contains(question, ["订单值", "订单数据"]) and not metrics:
                metrics = ["order_count", "revenue", "cost"]
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
            ("order_id", ["订单编号", "订单号", "订单的编号"]),
            ("year", ["按自然年", "逐年", "年度"]),
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
        if _contains(question, ["空结果", "订单明细", "订单列表"]) and _contains(question, ["查询", "返回", "列出"]):
            dimensions.append("order_id")
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
        if (
            not any(item.field == "regions.region_name" for item in filters)
            and not _contains(question, ["各地区", "各区域", "按地区", "按区域", "所有地区", "所有区域", "每个地区", "每个区域", "不同地区", "不同区域"])
        ):
            unknown_regions = re.findall(
                r"(?:[，,。；;\s]|有|在|查|看)([\u4e00-\u9fffA-Za-z0-9_-]{1,12})(?:区域|地区)",
                question,
            )
            if unknown_regions and unknown_regions[-1] not in {"各", "按", "所有", "每个", "不同"}:
                filters.append(QueryFilter(
                    field="regions.region_name", operator="=", value=unknown_regions[-1],
                ))
        unknown_store = re.search(r"(?:20\d{2}\s*年)?([\u4e00-\u9fffA-Za-z0-9_-]{1,12})门店", question)
        if unknown_store and not any(item.field == "regions.region_name" for item in filters):
            store_name = re.sub(r"^(?:查|看|统计|分析|查询)", "", unknown_store.group(1))
            filters.append(QueryFilter(
                field="regions.region_name", operator="=", value=f"{store_name}门店",
            ))
        for category in ["充电设备", "储能设备", "软件与终端", "服务"]:
            if category in question:
                filters.append(QueryFilter(field="products.category", operator="=", value=category))

        customer_types = self._linked_exact_values(context, question, "customers.customer_type")
        if not customer_types and "customer_type" in context.security_policy.allowed_columns.get("customers", []):
            customer_type_match = re.search(r"(?:统计|汇总|核对)([\u4e00-\u9fff]{1,8})客户(?:的)?", question)
            if customer_type_match:
                customer_types = [customer_type_match.group(1)]
        if customer_types:
            filters.append(QueryFilter(field="customers.customer_type", operator="=", value=customer_types[0]))
            if not _contains(question, ["按客户类型", "按用户类型"]):
                dimensions = [item for item in dimensions if item not in {"customer", "customer_type"}]
        product_names = self._linked_exact_values(context, question, "products.product_name")
        if not product_names and "product_name" in context.security_policy.allowed_columns.get("products", []):
            product_scope = re.sub(r"20\d{2}\s*年", "", question)
            product_scope = re.sub(r"第?[一二三四1234]\s*季度|\d{1,2}\s*月", "", product_scope)
            product_name_match = re.search(r"([\u4e00-\u9fffA-Za-z0-9_-]{2,20})订单(?:的)?订单量", product_scope)
            if product_name_match:
                candidate = product_name_match.group(1)
                filter_markers = [
                    "华北", "华东", "华南", "西部", "华中", "已支付", "支付成功", "退款", "已退款",
                    "企业客户", "个人客户", "渠道客户",
                ]
                if not any(marker in candidate for marker in filter_markers):
                    product_names = [candidate]
        if product_names:
            filters.append(QueryFilter(field="products.product_name", operator="=", value=product_names[0]))
            if not _contains(question, ["按产品", "按商品"]):
                dimensions = [item for item in dimensions if item != "product"]
        revenue_range = re.search(
            r"(?:收入|营收|销售额).*?大于等于\s*(\d+(?:\.\d+)?)\s*.*?小于\s*(\d+(?:\.\d+)?)",
            question,
        )
        if revenue_range:
            filters.append(QueryFilter(
                field="orders.revenue",
                operator="RANGE",
                value=f"[{revenue_range.group(1)},{revenue_range.group(2)})",
            ))
        region_filters = [item for item in filters if item.field == "regions.region_name"]
        if len(region_filters) > 1 and _contains(question, ["或", "或者", "任一"]):
            filters = [item for item in filters if item.field != "regions.region_name"]
            filters.append(QueryFilter(
                field="regions.region_name",
                operator="IN",
                value=[str(item.value) for item in region_filters],
            ))
        standalone_category_dimension = re.search(
            r"(?:^|[\s，,；;])(?:品类|类别)(?:$|[\s，,；;])",
            question,
        ) is not None
        if (
            any(item.field == "products.category" for item in filters)
            and not standalone_category_dimension
            and not _contains(question, ["按品类", "按类别", "分品类", "分类型"])
        ):
            dimensions = [item for item in dimensions if item != "category"]

        sql, selected_tables, selected_columns, selected_entities, joins, group_by, order_by = self._render_sql(
            context=context, metrics=metrics, dimensions=dimensions, filters=filters,
            time_range=range_value, limit=_limit(question, context.row_limit), question=question,
        )
        warning = []
        known_metrics = set(metric_defs) | {
            "profit", "avg_order_value", "revenue_share", "profit_margin",
            "distinct_order_count", "revenue_mom", "revenue_yoy", "max_quantity",
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

    @staticmethod
    def _linked_exact_values(context: QueryContext, question: str, qualified_name: str) -> list[str]:
        values: list[str] = []
        for candidate in context.candidate_columns:
            if str(candidate.qualified_name or "").lower() != qualified_name:
                continue
            for evidence in candidate.evidence:
                if not evidence.startswith("exact:"):
                    continue
                value = evidence.split(":", 1)[1]
                if value in question and value.lower() not in {candidate.name.lower(), candidate.label.lower()}:
                    values.append(value)
        return list(dict.fromkeys(values))

    @staticmethod
    def _require_resolvable_intent(*, question: str, context: QueryContext) -> None:
        explicit_analysis_axis = _contains(question, [
            "按月", "每月", "月份", "月度", "趋势", "环比", "同比",
            "按地区", "按区域", "按客户", "按产品", "按品类", "按状态",
        ])
        if (
            _contains(question, ["怎么样", "哪个最好", "把它", "那个维度", "前一段", "后一段"])
            and not explicit_analysis_axis
        ):
            raise ValueError("SEMANTIC_CLARIFICATION_REQUIRED")
        known_text = " ".join(
            str(value)
            for item in [*context.metrics, *context.business_terms]
            for value in item.values()
        ).lower()
        if "指数" in question and "指数" not in known_text:
            raise ValueError("SEMANTIC_UNKNOWN_METRIC")
        if "价值" in question and "价值" not in known_text:
            raise ValueError("SEMANTIC_UNKNOWN_METRIC")
        compound_profit = re.search(r"([\u4e00-\u9fff]{2})利润(?!率)", question)
        if compound_profit and compound_profit.group(1) not in {
            "订单", "后的", "总计", "累计", "分析", "季度", "年度", "月度", "总体", "全部",
        }:
            profit_index = compound_profit.end(1)
            if question[profit_index - 1:profit_index] not in {"和", "及", "与", "、", "的"}:
                raise ValueError("SEMANTIC_UNKNOWN_METRIC")

    def _render_sql(
        self, *, context: QueryContext, metrics: list[str], dimensions: list[str], filters: list[QueryFilter],
        time_range: QueryTimeRange | None, limit: int, question: str,
    ) -> tuple[str, list[str], list[str], list[str], list[dict[str, Any]], list[str], list[str]]:
        dialect = context.dialect
        schema = context.schema_name

        def table(name: str) -> str:
            return f"{schema}.{name}" if schema and dialect == "postgresql" else name

        if metrics == ["max_quantity", "order_count"]:
            sql = "\n".join([
                f"WITH maximum AS (SELECT MAX(o.quantity) AS max_quantity FROM {table('orders')} o)",
                "SELECT maximum.max_quantity, COUNT(o.order_id) AS order_count",
                f"FROM {table('orders')} o",
                "CROSS JOIN maximum",
                "WHERE o.quantity = maximum.max_quantity",
                "GROUP BY maximum.max_quantity",
                f"LIMIT {limit}",
            ])
            return (
                sql, ["orders"], ["orders.quantity", "orders.order_id"], ["orders"], [],
                ["maximum.max_quantity"], [],
            )

        if dimensions == ["order_id"] and len(metrics) == 1 and metrics[0] in {"revenue", "cost"}:
            metric = metrics[0]
            where_parts: list[str] = []
            if time_range and time_range.start and time_range.end_exclusive:
                literal = "DATE " if dialect == "postgresql" else ""
                where_parts.extend([
                    f"o.order_date >= {literal}'{time_range.start}'",
                    f"o.order_date < {literal}'{time_range.end_exclusive}'",
                ])
            is_extreme = _contains(question, ["最大", "最高", "最小", "最低"])
            maximum_positions = [question.find(token) for token in ("最大", "最高") if token in question]
            minimum_positions = [question.find(token) for token in ("最小", "最低") if token in question]
            first_maximum = min(maximum_positions, default=len(question) + 1)
            first_minimum = min(minimum_positions, default=len(question) + 1)
            descending = first_maximum < first_minimum
            lines = [f"SELECT o.order_id, o.{metric} AS {metric}", f"FROM {table('orders')} o"]
            if where_parts:
                lines.append("WHERE " + "\n  AND ".join(where_parts))
            lines.append(
                f"ORDER BY o.{metric} {'DESC' if descending else 'ASC'}, o.order_id ASC"
                if is_extreme else "ORDER BY o.order_id ASC"
            )
            lines.append(f"LIMIT {1 if is_extreme else limit}")
            selected_columns = ["orders.order_id", f"orders.{metric}"]
            if time_range:
                selected_columns.append("orders.order_date")
            return (
                "\n".join(lines), ["orders"], selected_columns, ["orders"], [], [],
                [f"o.{metric} {'DESC' if descending else 'ASC'}", "o.order_id ASC"] if is_extreme else ["o.order_id ASC"],
            )

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
            "region": (
                "r.region_name AS region", "r.region_name", "regions.region_name",
                "r.region_id", "regions.region_id",
            ),
            "product": (
                "p.product_name AS product", "p.product_name", "products.product_name",
                "p.product_id", "products.product_id",
            ),
            "category": (
                "p.category AS category", "p.category", "products.category",
                "p.category", "products.category",
            ),
            "customer": (
                "c.customer_name AS customer", "c.customer_name", "customers.customer_name",
                "c.customer_id", "customers.customer_id",
            ),
            "customer_type": (
                "c.customer_type AS customer_type", "c.customer_type", "customers.customer_type",
                "c.customer_type", "customers.customer_type",
            ),
            "status": (
                "o.status AS status", "o.status", "orders.status",
                "o.status", "orders.status",
            ),
            "month": (
                "DATE_TRUNC('month', o.order_date) AS month" if dialect == "postgresql" else "DATE_FORMAT(o.order_date, '%Y-%m-01') AS month",
                "DATE_TRUNC('month', o.order_date)" if dialect == "postgresql" else "DATE_FORMAT(o.order_date, '%Y-%m-01')",
                "orders.order_date",
                None,
                None,
            ),
            "order_id": (
                "o.order_id AS order_id", "o.order_id", "orders.order_id",
                "o.order_id", "orders.order_id",
            ),
            "year": (
                "EXTRACT(YEAR FROM o.order_date)::integer AS year" if dialect == "postgresql" else "YEAR(o.order_date) AS year",
                "EXTRACT(YEAR FROM o.order_date)" if dialect == "postgresql" else "YEAR(o.order_date)",
                "orders.order_date",
                None,
                None,
            ),
        }
        select_parts: list[str] = []
        group_parts: list[str] = []
        stable_order_parts: list[str] = []
        selected_columns: list[str] = []
        for dimension in dimensions:
            if dimension in dimension_sql:
                select_value, group_value, source, stable_group, stable_source = dimension_sql[dimension]
                select_parts.append(select_value)
                group_parts.append(group_value)
                selected_columns.append(source)
                if stable_group is not None:
                    if stable_group not in group_parts:
                        group_parts.append(stable_group)
                    stable_order_parts.append(f"{stable_group} ASC")
                if stable_source is not None and stable_source not in selected_columns:
                    selected_columns.append(stable_source)
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
        if any(item in dimensions for item in ("customer", "customer_type")) or any(
            item.field.startswith("customers.") for item in filters
        ):
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
            elif item.operator.upper() == "IN" and isinstance(item.value, list):
                values = ", ".join(f"'{str(value).replace(chr(39), chr(39) * 2)}'" for value in item.value)
                where_parts.append(f"{alias}.{column} IN ({values})")
            elif item.operator.upper() == "RANGE":
                bounds = re.fullmatch(r"\[([^,]+),([^\)]+)\)", str(item.value))
                if not bounds:
                    raise ValueError("INVALID_RANGE_FILTER")
                where_parts.extend([
                    f"{alias}.{column} >= {bounds.group(1)}",
                    f"{alias}.{column} < {bounds.group(2)}",
                ])
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
        metric_alias = "revenue" if len(metrics) > 1 and "revenue" in metrics else (metrics[0] if metrics else "revenue")
        order_parts = (
            [f"{metric_alias} {'DESC' if descending else 'ASC'}", *stable_order_parts]
            if dimensions else []
        )
        if "month" in dimensions:
            order_parts = (
                ["month ASC"]
                + ([f"{metric_alias} DESC"] if len(dimensions) > 1 else [])
                + stable_order_parts
            )
        elif "year" in dimensions:
            order_parts = ["year ASC"]

        lines = ["SELECT", "  " + ",\n  ".join(select_parts), f"FROM {table('orders')} o"]
        lines.extend(join_lines)
        if where_parts:
            lines.append("WHERE " + "\n  AND ".join(where_parts))
        if group_parts:
            lines.append("GROUP BY " + ", ".join(group_parts))
        elif metrics and any(metric not in {"order_count", "distinct_order_count"} for metric in metrics):
            # SUM/AVG over an empty input otherwise returns one synthetic NULL row,
            # which is not an evidence row and must not be presented as data.
            lines.append("HAVING COUNT(*) > 0")
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
                route=context.route,
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
                route=context.route,
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
        stripped = question.strip().rstrip(";")
        if re.match(
            r"^(SELECT|WITH|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|COPY|CALL|GRANT|REVOKE|SET|USE|LOAD)\b",
            stripped,
            re.IGNORECASE,
        ):
            # Explicit SQL must not be semantically rewritten by a probabilistic
            # provider.  Preserve it verbatim, then let the normal SqlGuard,
            # EXPLAIN cost gate, read-only executor and Result Oracle decide.
            return DeterministicTestProvider().plan(question=question, context=context)
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
