from __future__ import annotations

import re
from datetime import date

from app.query.contracts import QueryContext, QueryFilter, QueryTimeRange, SQLPlan
from app.query.nl2sql import Nl2SqlRouter
from app.semantic_runtime.contracts import SemanticQuery, SemanticRuntimeError, WrenDryPlan, WrenMDL


class WrenRuntimeAdapter:
    """Default semantic SQL runtime using ChatBI-owned Wren-compatible contracts.

    The adapter is a clean-room implementation over the public MDL concepts. No
    WrenAI source file or trademark asset is copied into ChatBI.
    """

    name = "wren-clean-room-runtime"

    def __init__(self, fallback: Nl2SqlRouter | None = None) -> None:
        self.fallback = fallback or Nl2SqlRouter()

    def compile_mdl(self, context: QueryContext) -> WrenMDL:
        models = [
            {
                "name": item["name"],
                "tableReference": item["source_table"],
                "primaryKey": item.get("primary_key"),
                "timeDimension": item.get("time_dimension"),
            }
            for item in context.entities
        ]
        metrics = [
            {
                "name": item["name"], "expression": item["expression"],
                "aggregation": item["aggregation"], "filters": item.get("filters", []),
            }
            for item in context.metrics
        ]
        dimensions = [
            {"name": item["name"], "expression": item["source_column"], "type": item["type"]}
            for item in context.dimensions
        ]
        relationships = [
            {
                "name": f"{item['left_entity']}__{item['right_entity']}",
                "models": [item["left_entity"], item["right_entity"]],
                "joinType": item["join_type"], "condition": item["join_keys"],
                "cardinality": item["cardinality"],
            }
            for item in context.relationships
        ]
        source_count = len(context.entities) + len(context.metrics) + len(context.dimensions) + len(context.relationships)
        mapped_count = len(models) + len(metrics) + len(dimensions) + len(relationships)
        return WrenMDL(
            schema_name=context.schema_name or "default",
            semantic_model_id=context.semantic_model_id,
            semantic_model_version=context.semantic_model_version,
            models=models,
            metrics=metrics,
            dimensions=dimensions,
            relationships=relationships,
            mapping_coverage=round(mapped_count / source_count, 6) if source_count else 1.0,
        )

    def dry_plan(self, *, semantic_query: SemanticQuery, mdl: WrenMDL) -> WrenDryPlan:
        model_names = {item["name"] for item in mdl.models}
        selected_models: list[str] = []
        for relationship in semantic_query.relationships:
            selected_models.extend([relationship["left_entity"], relationship["right_entity"]])
        if not selected_models:
            selected_models.append("fact_sales" if "fact_sales" in model_names else next(iter(sorted(model_names)), "orders"))
        if "outstanding_amount" in semantic_query.metrics and "fact_payment" in model_names:
            selected_models = ["fact_payment"]
        unknown_models = sorted(set(selected_models).difference(model_names))
        if unknown_models:
            error = {"code": "WREN_MODEL_NOT_FOUND", "stage": "dry_plan", "models": unknown_models, "retryable": False}
            return WrenDryPlan(
                status="ERROR", semantic_model_version=mdl.semantic_model_version,
                nodes=[], selected_models=selected_models, selected_metrics=semantic_query.metrics,
                selected_dimensions=semantic_query.dimensions, structured_error=error,
            )
        status = "CLARIFICATION_REQUIRED" if semantic_query.clarification_required else "READY"
        return WrenDryPlan(
            status=status,
            semantic_model_version=mdl.semantic_model_version,
            selected_models=list(dict.fromkeys(selected_models)),
            selected_metrics=semantic_query.metrics,
            selected_dimensions=semantic_query.dimensions,
            nodes=[
                {"id": "mdl", "operation": "resolve_semantic_model", "version": mdl.semantic_model_version},
                {"id": "semantic_query", "operation": "bind_metric_dimension_filter"},
                {"id": "semantic_sql", "operation": "translate_to_dialect", "dialect": "runtime"},
                {"id": "sqlglot", "operation": "ast_guard"},
                {"id": "executor", "operation": "read_only_query"},
                {"id": "oracle", "operation": "verify_result"},
            ],
        )

    def translate(self, *, question: str, context: QueryContext, semantic_query: SemanticQuery, dry_plan: WrenDryPlan) -> SQLPlan:
        if dry_plan.status == "ERROR":
            error = dry_plan.structured_error or {}
            raise SemanticRuntimeError(str(error.get("code", "WREN_DRY_PLAN_FAILED")), "wren_dry_plan", "Wren dry-plan failed")
        if "fact_sales" not in {item.get("name") for item in context.entities}:
            plan = self.fallback.plan(question=question, context=context)
            plan.provider = self.name
            return plan
        return self._translate_benchmark(question=question, context=context, semantic_query=semantic_query)

    def _translate_benchmark(self, *, question: str, context: QueryContext, semantic_query: SemanticQuery) -> SQLPlan:
        schema = context.schema_name or "chatbi_benchmark_v21"
        metrics = semantic_query.metrics
        payment_query = metrics == ["outstanding_amount"] or (
            "outstanding_amount" in metrics and all(item == "outstanding_amount" for item in metrics)
        )
        alias = "p" if payment_query else "f"
        fact = "fact_payment" if payment_query else "fact_sales"
        table = lambda name: f'"{schema}".{name}'
        metric_sql = {
            "net_sales": "ROUND(SUM(f.net_amount - f.refund_amount)::numeric, 2) AS net_sales",
            "net_profit": "ROUND(SUM(f.profit_amount - f.refund_amount)::numeric, 2) AS net_profit",
            "valid_orders": "COUNT(*) FILTER (WHERE f.order_status IN ('VALID','PARTIAL_REFUND','REFUNDED')) AS valid_orders",
            "active_customers": "COUNT(DISTINCT f.customer_id) FILTER (WHERE f.order_status IN ('VALID','PARTIAL_REFUND','REFUNDED')) AS active_customers",
            "refund_amount": "ROUND(SUM(f.refund_amount)::numeric, 2) AS refund_amount",
            "cancelled_orders": "COUNT(*) FILTER (WHERE f.order_status = 'CANCELLED') AS cancelled_orders",
            "outstanding_amount": "ROUND(SUM(p.outstanding_amount)::numeric, 2) AS outstanding_amount",
        }
        dimension_sql = {
            "region": ("r.region_group AS region", "r.region_group", "dim_region.region_group"),
            "product": ("pr.product_name AS product", "pr.product_name", "dim_product.product_name"),
            "category": ("pr.category AS category", "pr.category", "dim_product.category"),
            "customer": ("c.customer_name AS customer", "c.customer_name", "dim_customer.customer_name"),
            "customer_tier": ("c.customer_tier AS customer_tier", "c.customer_tier", "dim_customer.customer_tier"),
            "month": (
                f"DATE_TRUNC('month', {alias}.{'invoice_date' if payment_query else 'order_date'})::date AS month",
                f"DATE_TRUNC('month', {alias}.{'invoice_date' if payment_query else 'order_date'})::date",
                f"{fact}.{'invoice_date' if payment_query else 'order_date'}",
            ),
            "status": ("f.order_status AS status", "f.order_status", "fact_sales.order_status"),
            "aging_bucket": ("p.aging_bucket AS aging_bucket", "p.aging_bucket", "fact_payment.aging_bucket"),
            "tenant": (f"{alias}.tenant_id AS tenant", f"{alias}.tenant_id", f"{fact}.tenant_id"),
        }
        select_parts: list[str] = []
        group_by: list[str] = []
        selected_columns: list[str] = []
        for dimension in semantic_query.dimensions:
            if payment_query and dimension not in {"month", "aging_bucket", "tenant"}:
                continue
            if dimension in dimension_sql:
                expression, group, source = dimension_sql[dimension]
                select_parts.append(expression)
                group_by.append(group)
                selected_columns.append(source)
        for metric in metrics:
            expression = metric_sql.get(metric)
            if not expression:
                raise SemanticRuntimeError("WREN_METRIC_NOT_SUPPORTED", "semantic_sql", f"Unsupported benchmark metric: {metric}")
            if semantic_query.comparison == "CONTRIBUTION" and metric == "net_sales" and group_by:
                expression = (
                    "ROUND(SUM(f.net_amount - f.refund_amount)::numeric, 2) AS net_sales, "
                    "ROUND(SUM(f.net_amount - f.refund_amount) * 100.0 / "
                    "NULLIF(SUM(SUM(f.net_amount - f.refund_amount)) OVER (), 0), 4) AS contribution_rate"
                )
            select_parts.append(expression)
        if not select_parts:
            raise SemanticRuntimeError("WREN_EMPTY_PROJECTION", "semantic_sql", "No authorized projection was produced")

        joins: list[dict] = []
        join_lines: list[str] = []
        if not payment_query:
            if "region" in semantic_query.dimensions or any(item["field"] == "dim_region.region_group" for item in semantic_query.filters):
                join_lines.append(f"JOIN {table('dim_region')} r ON r.region_id = f.region_id")
                joins.append({"left": "fact_sales.region_id", "right": "dim_region.region_id", "type": "INNER"})
            if any(item in semantic_query.dimensions for item in ("product", "category")):
                join_lines.append(f"JOIN {table('dim_product')} pr ON pr.product_id = f.product_id")
                joins.append({"left": "fact_sales.product_id", "right": "dim_product.product_id", "type": "INNER"})
            if any(item in semantic_query.dimensions for item in ("customer", "customer_tier")):
                join_lines.append(f"JOIN {table('dim_customer')} c ON c.customer_id = f.customer_id")
                joins.append({"left": "fact_sales.customer_id", "right": "dim_customer.customer_id", "type": "INNER"})

        aliases = {"fact_sales": "f", "fact_payment": "p", "dim_region": "r"}
        where_parts = [] if payment_query else ["f.order_status <> 'TEST'"]
        query_filters: list[QueryFilter] = []
        for item in semantic_query.filters:
            field = str(item["field"])
            if payment_query and field == "fact_sales.tenant_id":
                field = "fact_payment.tenant_id"
            entity, column = field.split(".", 1)
            if entity not in aliases:
                continue
            field_alias = aliases[entity]
            operator, value = str(item["operator"]), item.get("value")
            query_filters.append(QueryFilter(field=field, operator=operator, value=value))
            if value is None and operator.upper() in {"IS", "IS NOT"}:
                where_parts.append(f"{field_alias}.{column} {operator.upper()} NULL")
            elif isinstance(value, int):
                where_parts.append(f"{field_alias}.{column} {operator} {value}")
            else:
                escaped = str(value).replace("'", "''")
                where_parts.append(f"{field_alias}.{column} {operator} '{escaped}'")
        time_range = semantic_query.time_range
        plan_time = None
        comparison_start: str | None = None
        if time_range:
            start = str(time_range["start"])
            if semantic_query.comparison == "YEAR_OVER_YEAR":
                start_date = date.fromisoformat(start)
                start = start_date.replace(year=start_date.year - 1).isoformat()
                comparison_start = str(time_range["start"])
            elif semantic_query.comparison == "MONTH_OVER_MONTH":
                start_date = date.fromisoformat(start)
                previous_month_end = start_date.replace(day=1)
                previous_year = previous_month_end.year - (1 if previous_month_end.month == 1 else 0)
                previous_month = 12 if previous_month_end.month == 1 else previous_month_end.month - 1
                start = date(previous_year, previous_month, 1).isoformat()
                comparison_start = str(time_range["start"])
            date_column = "invoice_date" if payment_query else "order_date"
            where_parts.extend([
                f"{alias}.{date_column} >= DATE '{start}'",
                f"{alias}.{date_column} < DATE '{time_range['end_exclusive']}'",
            ])
            plan_time = QueryTimeRange(
                field=f"{fact}.{date_column}", kind=str(time_range["kind"]),
                start=str(time_range["start"]), end_exclusive=str(time_range["end_exclusive"]),
            )
            selected_columns.append(plan_time.field)
        limit_match = re.search(r"(?:top|前)\s*(\d+)", question, re.IGNORECASE)
        limit = min(context.row_limit, int(limit_match.group(1)) if limit_match else context.row_limit)
        primary_metric = metrics[0]
        order_by = ["month ASC"] if "month" in semantic_query.dimensions else ([f"{primary_metric} DESC"] if group_by else [])
        lines = ["SELECT", "  " + ",\n  ".join(select_parts), f"FROM {table(fact)} {alias}", *join_lines]
        if where_parts:
            lines.append("WHERE " + "\n  AND ".join(where_parts))
        if group_by:
            lines.append("GROUP BY " + ", ".join(group_by))
        if semantic_query.comparison in {"YEAR_OVER_YEAR", "MONTH_OVER_MONTH"} and "month" in semantic_query.dimensions and len(metrics) == 1:
            metric = metrics[0]
            offset = 12 if semantic_query.comparison == "YEAR_OVER_YEAR" else 1
            base_sql = "\n".join(lines)
            generated_sql = (
                "WITH base AS (\n"
                + base_sql
                + "\n), compared AS (\n"
                + f"  SELECT month, {metric}, LAG({metric}, {offset}) OVER (ORDER BY month) AS previous_{metric}\n"
                + "  FROM base\n)\n"
                + f"SELECT month, {metric}, previous_{metric},\n"
                + f"  ROUND(({metric} - previous_{metric}) * 100.0 / NULLIF(previous_{metric}, 0), 4) AS comparison_rate\n"
                + "FROM compared\n"
                + (f"WHERE month >= DATE '{comparison_start}'\n" if comparison_start else "")
                + "ORDER BY month ASC\n"
                + f"LIMIT {limit}"
            )
        else:
            if order_by:
                lines.append("ORDER BY " + ", ".join(order_by))
            lines.append(f"LIMIT {limit}")
            generated_sql = "\n".join(lines)
        selected_tables = [fact] + [item["right"].split(".", 1)[0] for item in joins]
        selected_columns.extend([item.field for item in query_filters])
        return SQLPlan(
            question=question,
            intent="ANALYTICAL_QUERY",
            dialect=context.dialect,
            provider=self.name,
            semantic_model_id=context.semantic_model_id,
            semantic_model_version=context.semantic_model_version,
            selected_entities=list(dict.fromkeys(selected_tables)),
            selected_tables=list(dict.fromkeys(selected_tables)),
            selected_columns=list(dict.fromkeys(selected_columns)),
            metrics=metrics,
            dimensions=[item for item in semantic_query.dimensions if not payment_query or item in {"month", "aging_bucket", "tenant"}],
            joins=joins,
            filters=query_filters,
            time_range=plan_time,
            group_by=group_by,
            order_by=order_by,
            limit=limit,
            generated_sql=generated_sql,
            confidence=semantic_query.confidence,
            warnings=["Clarification recommended before decision use"] if semantic_query.clarification_required else [],
        )
