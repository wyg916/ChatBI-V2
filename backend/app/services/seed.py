from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import encrypt_secret
from app.models import (
    BusinessTerm,
    Dashboard,
    DataSource,
    Dimension,
    EvaluationRun,
    Metric,
    SemanticEntity,
    SemanticModel,
    SemanticRelation,
    VerifiedAnswer,
)
from app.models.entities import utcnow
from app.services.datasources import default_workspace


DEMO_MODEL_NAME = "新能源经营分析"
DEMO_MYSQL_MODEL_NAME = "新能源经营分析（MySQL兼容）"


def _ensure_day2_semantic_resources(db: Session, model: SemanticModel) -> None:
    entities = {item.name: item for item in db.scalars(select(SemanticEntity).where(SemanticEntity.semantic_model_id == model.id))}
    metrics = {item.name: item for item in db.scalars(select(Metric).where(Metric.semantic_model_id == model.id))}
    dimensions = {item.name: item for item in db.scalars(select(Dimension).where(Dimension.semantic_model_id == model.id))}
    relations = {
        (item.left_entity, item.right_entity): item
        for item in db.scalars(select(SemanticRelation).where(SemanticRelation.semantic_model_id == model.id))
    }
    terms = {item.term: item for item in db.scalars(select(BusinessTerm).where(BusinessTerm.semantic_model_id == model.id))}

    for name, source_table, primary_key, time_dimension in [
        ("regions", "regions", "region_id", None),
    ]:
        if name not in entities:
            db.add(SemanticEntity(
                semantic_model_id=model.id, name=name, source_table=source_table,
                primary_key=primary_key, time_dimension=time_dimension,
            ))
    for name, label, description, expression, aggregation in [
        ("profit", "利润", "订单收入减订单成本", "orders.revenue - orders.cost", "SUM"),
        ("avg_order_value", "客单价", "平均订单收入", "orders.revenue", "AVG"),
    ]:
        if name not in metrics:
            db.add(Metric(
                semantic_model_id=model.id, name=name, label=label, description=description,
                expression=expression, aggregation=aggregation, filters=[],
            ))
    if "region" in dimensions:
        dimensions["region"].source_column = "regions.region_name"
    for name, label, source_column, data_type in [
        ("category", "产品类别", "products.category", "STRING"),
        ("customer_type", "客户类型", "customers.customer_type", "STRING"),
    ]:
        if name not in dimensions:
            db.add(Dimension(
                semantic_model_id=model.id, name=name, label=label,
                source_column=source_column, type=data_type,
            ))
    if ("orders", "regions") not in relations:
        db.add(SemanticRelation(
            semantic_model_id=model.id, left_entity="orders", right_entity="regions", join_type="INNER",
            join_keys=[{"left": "region_id", "right": "region_id"}], cardinality="MANY_TO_ONE",
        ))
    for term, synonyms, definition, mapped_object in [
        ("利润", ["毛利"], "订单收入减订单成本", "metric.profit"),
        ("客单价", ["平均订单金额"], "平均每笔订单收入", "metric.avg_order_value"),
        ("产品类别", ["品类"], "产品所属经营类别", "dimension.category"),
    ]:
        if term not in terms:
            db.add(BusinessTerm(
                semantic_model_id=model.id, term=term, synonyms=synonyms,
                definition=definition, mapped_object=mapped_object,
            ))


def _ensure_mysql_semantic_model(db: Session, datasource: DataSource, source: SemanticModel) -> SemanticModel:
    model = db.scalar(select(SemanticModel).where(SemanticModel.name == DEMO_MYSQL_MODEL_NAME))
    if model is None:
        model = SemanticModel(
            workspace_id=source.workspace_id,
            datasource_id=datasource.id,
            name=DEMO_MYSQL_MODEL_NAME,
            description="Day 2 MySQL 方言兼容语义模型",
            status=source.status,
            version=source.version,
        )
        db.add(model)
        db.flush()
    if db.scalar(select(SemanticEntity.id).where(SemanticEntity.semantic_model_id == model.id).limit(1)) is None:
        db.add_all([
            SemanticEntity(
                semantic_model_id=model.id, name=item.name, source_table=item.source_table,
                primary_key=item.primary_key, time_dimension=item.time_dimension,
            )
            for item in db.scalars(select(SemanticEntity).where(SemanticEntity.semantic_model_id == source.id))
        ])
        db.add_all([
            Metric(
                semantic_model_id=model.id, name=item.name, label=item.label, description=item.description,
                expression=item.expression, aggregation=item.aggregation, filters=item.filters,
            )
            for item in db.scalars(select(Metric).where(Metric.semantic_model_id == source.id))
        ])
        db.add_all([
            Dimension(
                semantic_model_id=model.id, name=item.name, label=item.label,
                source_column=item.source_column, type=item.type,
            )
            for item in db.scalars(select(Dimension).where(Dimension.semantic_model_id == source.id))
        ])
        db.add_all([
            SemanticRelation(
                semantic_model_id=model.id, left_entity=item.left_entity, right_entity=item.right_entity,
                join_type=item.join_type, join_keys=item.join_keys, cardinality=item.cardinality,
            )
            for item in db.scalars(select(SemanticRelation).where(SemanticRelation.semantic_model_id == source.id))
        ])
        db.add_all([
            BusinessTerm(
                semantic_model_id=model.id, term=item.term, synonyms=item.synonyms,
                definition=item.definition, mapped_object=item.mapped_object,
            )
            for item in db.scalars(select(BusinessTerm).where(BusinessTerm.semantic_model_id == source.id))
        ])
    _ensure_day2_semantic_resources(db, model)
    return model


def _seed_demo_content(db: Session, workspace_id: str) -> None:
    if db.scalar(select(VerifiedAnswer.id).limit(1)) is None:
        answer_rows = [
            ("2026年二季度环比增长率入围多少?", "全体收入", "文心", "PUBLISHED", 98, 432, 84),
            ("各负责人近三年利润总额趋势?", "共用收入", "弘岳", "PUBLISHED", 96, 321, 73),
            ("各地区订单金额年度分布", "订单量 / 销售额", "文心", "PUBLISHED", 90, 252, 62),
            ("过去 30 天退款笔数最高的商品", "订单与发票", "弘岳", "REVIEW", 89, 182, 58),
            ("驾驶舱毛利率表现", "毛利率", "盘古内", "PUBLISHED", 97, 232, 55),
            ("各省份营收完成率", "营业完成率", "钉钉", "REVIEW", 86, 92, 48),
        ]
        db.add_all([
            VerifiedAnswer(
                workspace_id=workspace_id,
                question=question,
                module="模块 C1.1.8",
                sql_synced=True,
                model_name=model_name,
                owner_name=owner,
                status=status,
                accuracy_percent=accuracy,
                adoption_count=adoptions,
                monthly_adoption_count=monthly,
                is_favorite=True,
                sort_order=index,
            )
            for index, (question, model_name, owner, status, accuracy, adoptions, monthly) in enumerate(answer_rows, 1)
        ])
        generated_accuracy = (96.4 * 128 - sum(row[4] for row in answer_rows)) / 122
        generated_models = ["全体收入", "订单量 / 销售额", "客户增长", "毛利率", "区域经营"]
        generated_owners = ["文心", "弘岳", "盘古内", "钉钉"]
        for offset in range(122):
            status = "REVIEW" if offset < 12 else "DRAFT" if offset < 26 else "PUBLISHED" if offset < 28 else "ARCHIVED"
            db.add(VerifiedAnswer(
                workspace_id=workspace_id,
                question=f"经营分析标准问题 {offset + 7:03d}",
                module="模块 C1.1.8",
                sql_synced=True,
                model_name=generated_models[offset % len(generated_models)],
                owner_name=generated_owners[offset % len(generated_owners)],
                status=status,
                accuracy_percent=generated_accuracy,
                adoption_count=48 + (offset * 13) % 280,
                monthly_adoption_count=8 if offset < 50 else 7,
                is_favorite=True,
                sort_order=offset + 7,
            ))

    if db.scalar(select(Dashboard.id).limit(1)) is None:
        dashboard_rows = [
            ("经营总览看板", "收入、利润、订单与客户增长总览", 8, True, 5),
            ("区域经营看板", "各区域收入、订单、毛利与完成率", 12, True, 4),
            ("客户增长看板", "新增、活跃、留存、复购和渠道", 9, True, 4),
            ("供应链运营看板", "库存、采购、交付、履约和异常", 10, True, 3),
            ("市场投放看板", "渠道、线索、转化、获客成本", 7, False, 3),
            ("财务分析看板", "收入、费用、现金流与应收应付", 11, False, 2),
        ]
        minute_offsets = [0, 5, 12, 60, 24 * 60, 24 * 60]
        now = utcnow()
        db.add_all([
            Dashboard(
                workspace_id=workspace_id,
                name=name,
                description=description,
                card_count=card_count,
                is_shared=is_shared,
                refresh_count_today=refreshes,
                status="REALTIME",
                trend_variant=index - 1,
                sort_order=index,
                updated_at=now - timedelta(minutes=minute_offsets[index - 1]),
            )
            for index, (name, description, card_count, is_shared, refreshes) in enumerate(dashboard_rows, 1)
        ])
        for offset in range(12):
            db.add(Dashboard(
                workspace_id=workspace_id,
                name=f"经营分析看板 {offset + 7:02d}",
                description="基于已验证答案生成的可刷新经营分析页面",
                card_count=8 if offset < 6 else 7,
                is_shared=offset < 5,
                refresh_count_today=2 if offset < 3 else 1,
                status="REALTIME",
                trend_variant=offset % 6,
                sort_order=offset + 7,
                updated_at=now - timedelta(days=offset + 2),
            ))

    if db.scalar(select(EvaluationRun.id).limit(1)) is None:
        now = utcnow()
        common_errors = [
            {"label": "数据库表", "percent": 30, "color": "#5b5cf6"},
            {"label": "多表关联", "percent": 28, "color": "#2f80ed"},
            {"label": "过滤条件", "percent": 17, "color": "#f59e0b"},
            {"label": "聚合函数", "percent": 12, "color": "#f04444"},
            {"label": "其他", "percent": 13, "color": "#c8cfdd"},
        ]
        db.add_all([
            EvaluationRun(
                workspace_id=workspace_id, release_name="ChatBI Core v1.13",
                model_name="Render v1.2.0 + GPT-4.1", status="FULL_RELEASE", is_current=True,
                golden_set_count=296, sql_generation_rate=98.8, result_accuracy=96.4,
                semantic_accuracy=97.1, relevance_accuracy=96.6, average_response_seconds=3.2,
                error_distribution=common_errors,
                trend_points=[
                    {"date": "04/21", "value": 89.0}, {"date": "04/25", "value": 91.2},
                    {"date": "04/29", "value": 90.1}, {"date": "05/03", "value": 94.0},
                    {"date": "05/07", "value": 92.5}, {"date": "05/11", "value": 96.1},
                    {"date": "05/15", "value": 94.6}, {"date": "05/19", "value": 97.4},
                ],
                completed_at=now - timedelta(minutes=28), duration_seconds=763, sort_order=1,
            ),
            EvaluationRun(
                workspace_id=workspace_id, release_name="ChatBI Core v1.12",
                model_name="Render v1.1.0 + DeepSeek", status="COMPLETED", is_current=False,
                golden_set_count=296, sql_generation_rate=95.7, result_accuracy=94.8,
                semantic_accuracy=95.6, relevance_accuracy=94.4, average_response_seconds=2.9,
                error_distribution=common_errors, trend_points=[],
                completed_at=now - timedelta(days=7), duration_seconds=701, sort_order=2,
            ),
            EvaluationRun(
                workspace_id=workspace_id, release_name="SQLAPI Baseline",
                model_name="SQLAPI Shadow", status="BASELINE", is_current=False,
                golden_set_count=296, sql_generation_rate=93.7, result_accuracy=92.3,
                semantic_accuracy=93.8, relevance_accuracy=91.2, average_response_seconds=4.1,
                error_distribution=common_errors, trend_points=[],
                completed_at=now - timedelta(days=14), duration_seconds=918, sort_order=3,
            ),
        ])


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
        mysql_datasource = DataSource(
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
        )
        db.add(mysql_datasource)
        db.flush()

    existing = db.scalar(select(SemanticModel).where(SemanticModel.name == DEMO_MODEL_NAME))
    if existing:
        _ensure_day2_semantic_resources(db, existing)
        db.flush()
        _ensure_mysql_semantic_model(db, mysql_datasource, existing)
        _seed_demo_content(db, workspace.id)
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
    _ensure_day2_semantic_resources(db, model)
    db.flush()
    _ensure_mysql_semantic_model(db, mysql_datasource, model)
    _seed_demo_content(db, workspace.id)
    db.commit()
    db.refresh(model)
    return model
