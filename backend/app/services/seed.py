from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import encrypt_secret
from app.models import BusinessTerm, DataSource, Dimension, Metric, SemanticEntity, SemanticModel, SemanticRelation
from app.services.datasources import default_workspace


DEMO_MODEL_NAME = "新能源经营分析"


def seed_demo_semantic_model(db: Session) -> SemanticModel:
    settings = get_settings()
    workspace = default_workspace(db)
    datasource = db.scalar(select(DataSource).where(DataSource.name == "Demo PostgreSQL"))
    if datasource is None:
        datasource = DataSource(
            workspace_id=workspace.id,
            name="Demo PostgreSQL",
            type="postgresql",
            host=settings.demo_postgres_host,
            port=settings.demo_postgres_port,
            database=settings.demo_postgres_database,
            username=settings.demo_postgres_username,
            password_encrypted=encrypt_secret(settings.demo_postgres_password),
            ssl=False,
            schema=settings.demo_postgres_schema,
            status="CREATED",
        )
        db.add(datasource)
        db.flush()
    mysql_datasource = db.scalar(select(DataSource).where(DataSource.name == "Demo MySQL"))
    if mysql_datasource is None:
        db.add(DataSource(
            workspace_id=workspace.id,
            name="Demo MySQL",
            type="mysql",
            host=settings.demo_mysql_host,
            port=settings.demo_mysql_port,
            database=settings.demo_mysql_database,
            username=settings.demo_mysql_username,
            password_encrypted=encrypt_secret(settings.demo_mysql_password),
            ssl=False,
            schema=settings.demo_mysql_database,
            status="CREATED",
        ))

    existing = db.scalar(select(SemanticModel).where(SemanticModel.name == DEMO_MODEL_NAME))
    if existing:
        db.commit()
        return existing

    model = SemanticModel(
        workspace_id=workspace.id,
        datasource_id=datasource.id,
        name=DEMO_MODEL_NAME,
        description="可复现的 Day 1 演示语义模型",
    )
    db.add(model)
    db.flush()
    db.add_all([
        SemanticEntity(semantic_model_id=model.id, name="orders", source_table="orders", primary_key="order_id", time_dimension="order_date"),
        SemanticEntity(semantic_model_id=model.id, name="customers", source_table="customers", primary_key="customer_id"),
        SemanticEntity(semantic_model_id=model.id, name="products", source_table="products", primary_key="product_id"),
        Metric(semantic_model_id=model.id, name="revenue", label="收入", description="订单收入总额", expression="orders.revenue", aggregation="SUM", filters=[]),
        Metric(semantic_model_id=model.id, name="cost", label="成本", description="订单成本总额", expression="orders.cost", aggregation="SUM", filters=[]),
        Metric(semantic_model_id=model.id, name="order_count", label="订单量", description="订单数量", expression="orders.order_id", aggregation="COUNT", filters=[]),
        Dimension(semantic_model_id=model.id, name="order_date", label="订单日期", source_column="orders.order_date", type="DATE"),
        Dimension(semantic_model_id=model.id, name="region", label="地区", source_column="orders.region_id", type="STRING"),
        Dimension(semantic_model_id=model.id, name="customer", label="客户", source_column="customers.customer_name", type="STRING"),
        Dimension(semantic_model_id=model.id, name="product", label="产品", source_column="products.product_name", type="STRING"),
        Dimension(semantic_model_id=model.id, name="status", label="订单状态", source_column="orders.status", type="STRING"),
        SemanticRelation(semantic_model_id=model.id, left_entity="orders", right_entity="customers", join_type="LEFT", join_keys=[{"left": "customer_id", "right": "customer_id"}], cardinality="MANY_TO_ONE"),
        SemanticRelation(semantic_model_id=model.id, left_entity="orders", right_entity="products", join_type="LEFT", join_keys=[{"left": "product_id", "right": "product_id"}], cardinality="MANY_TO_ONE"),
        BusinessTerm(semantic_model_id=model.id, term="收入", synonyms=["营收", "销售额"], definition="已确认订单收入总额", mapped_object="metric.revenue"),
        BusinessTerm(semantic_model_id=model.id, term="成本", synonyms=["支出"], definition="订单直接成本总额", mapped_object="metric.cost"),
        BusinessTerm(semantic_model_id=model.id, term="订单量", synonyms=["订单数"], definition="订单记录数量", mapped_object="metric.order_count"),
        BusinessTerm(semantic_model_id=model.id, term="地区", synonyms=["区域"], definition="订单所属经营区域", mapped_object="dimension.region"),
        BusinessTerm(semantic_model_id=model.id, term="客户", synonyms=["用户"], definition="产生订单的客户", mapped_object="dimension.customer"),
    ])
    db.commit()
    db.refresh(model)
    return model
