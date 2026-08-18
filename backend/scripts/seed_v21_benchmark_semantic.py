from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from urllib.parse import quote_plus

from dotenv import load_dotenv


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish the isolated v2.1 benchmark semantic model.")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--datasource-id", default="")
    parser.add_argument("--model-name", default="V2.1 10M Benchmark Semantic")
    args = parser.parse_args()
    load_dotenv(args.env_file, override=True)
    if not os.getenv("CHATBI_DATABASE_URL") and os.getenv("CHATBI_META_PASSWORD"):
        password = quote_plus(os.environ["CHATBI_META_PASSWORD"])
        os.environ["CHATBI_DATABASE_URL"] = f"postgresql+psycopg://chatbi_app:{password}@127.0.0.1:5432/chatbi_v2"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import BusinessTerm, DataSource, Dimension, Metric, SemanticEntity, SemanticModel, SemanticRelation
    from app.semantic.engine import LocalSemanticEngine

    with SessionLocal() as db:
        datasource = db.get(DataSource, args.datasource_id) if args.datasource_id else db.scalar(
            select(DataSource).where(DataSource.schema == "chatbi_benchmark_v21").order_by(DataSource.created_at.desc())
        )
        if datasource is None:
            raise SystemExit("The synced chatbi_benchmark_v21 datasource was not found")
        existing = db.scalar(select(SemanticModel).where(
            SemanticModel.workspace_id == datasource.workspace_id,
            SemanticModel.datasource_id == datasource.id,
            SemanticModel.name == args.model_name,
        ))
        if existing is not None:
            print(f"DATASOURCE_ID={datasource.id}")
            print(f"SEMANTIC_MODEL_ID={existing.id}")
            print(f"SEMANTIC_MODEL_VERSION={existing.version}")
            print("SEMANTIC_MODEL_REUSED=YES")
            return

        model = SemanticModel(
            workspace_id=datasource.workspace_id,
            datasource_id=datasource.id,
            name=args.model_name,
            description="Fixed-seed 10M PostgreSQL benchmark semantic model for Day 1 gates.",
            status="DRAFT",
        )
        db.add(model)
        db.flush()
        entities = [
            ("fact_sales", "fact_sales", "order_id", "order_date"),
            ("fact_payment", "fact_payment", "payment_id", "invoice_date"),
            ("dim_region", "dim_region", "region_id", None),
            ("dim_product", "dim_product", "product_id", None),
            ("dim_customer", "dim_customer", "customer_id", None),
        ]
        db.add_all([
            SemanticEntity(
                semantic_model_id=model.id, name=name, source_table=source,
                primary_key=primary_key, time_dimension=time_dimension,
            )
            for name, source, primary_key, time_dimension in entities
        ])
        metrics = [
            ("net_sales", "净销售额", "fact_sales.net_amount - fact_sales.refund_amount", "SUM", []),
            ("net_profit", "净利润", "fact_sales.profit_amount - fact_sales.refund_amount", "SUM", []),
            ("valid_orders", "有效订单数", "fact_sales.order_id", "COUNT", [{"field": "fact_sales.order_status", "operator": "IN", "value": ["VALID", "PARTIAL_REFUND", "REFUNDED"]}]),
            ("active_customers", "活跃客户数", "fact_sales.customer_id", "COUNT_DISTINCT", [{"field": "fact_sales.order_status", "operator": "IN", "value": ["VALID", "PARTIAL_REFUND", "REFUNDED"]}]),
            ("refund_amount", "退款金额", "fact_sales.refund_amount", "SUM", []),
            ("cancelled_orders", "取消订单数", "fact_sales.order_id", "COUNT", [{"field": "fact_sales.order_status", "operator": "=", "value": "CANCELLED"}]),
            ("outstanding_amount", "未结应收", "fact_payment.outstanding_amount", "SUM", []),
        ]
        db.add_all([
            Metric(
                semantic_model_id=model.id, name=name, label=label,
                description=label, expression=expression, aggregation=aggregation, filters=filters,
            )
            for name, label, expression, aggregation, filters in metrics
        ])
        dimensions = [
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
        db.add_all([
            Dimension(
                semantic_model_id=model.id, name=name, label=label,
                source_column=source_column, type=dimension_type,
            )
            for name, label, source_column, dimension_type in dimensions
        ])
        relations = [
            ("fact_sales", "dim_region", [{"left": "region_id", "right": "region_id"}], "MANY_TO_ONE"),
            ("fact_sales", "dim_product", [{"left": "product_id", "right": "product_id"}], "MANY_TO_ONE"),
            ("fact_sales", "dim_customer", [{"left": "customer_id", "right": "customer_id"}], "MANY_TO_ONE"),
            ("fact_sales", "fact_payment", [{"left": "order_id", "right": "order_id"}], "ONE_TO_MANY"),
        ]
        db.add_all([
            SemanticRelation(
                semantic_model_id=model.id, left_entity=left, right_entity=right,
                join_type="LEFT", join_keys=keys, cardinality=cardinality,
            )
            for left, right, keys, cardinality in relations
        ])
        terms = [
            ("销售额", ["收入", "营收", "净销售额"], "扣除退款后的订单净额", "metric.net_sales"),
            ("利润", ["净利润", "毛利"], "扣除退款后的利润额", "metric.net_profit"),
            ("订单量", ["有效订单", "订单数"], "有效、部分退款和完全退款订单数", "metric.valid_orders"),
            ("地区", ["区域"], "订单所属大区", "dimension.region"),
            ("应收", ["未结应收", "应收余额"], "尚未收到的应收金额", "metric.outstanding_amount"),
        ]
        db.add_all([
            BusinessTerm(
                semantic_model_id=model.id, term=term, synonyms=synonyms,
                definition=definition, mapped_object=mapped_object,
            )
            for term, synonyms, definition, mapped_object in terms
        ])
        db.flush()
        version = LocalSemanticEngine().publish(db, model)
        print(f"DATASOURCE_ID={datasource.id}")
        print(f"SEMANTIC_MODEL_ID={model.id}")
        print(f"SEMANTIC_MODEL_VERSION={version.version}")
        print("SEMANTIC_MODEL_REUSED=NO")


if __name__ == "__main__":
    main()
