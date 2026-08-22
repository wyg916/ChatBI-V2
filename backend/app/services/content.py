from datetime import timedelta

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.models import AnswerVersion, Dashboard, DashboardCard, DataSource, QueryRun, VerifiedAnswer
from app.services.datasources import build_connector


def answer_summary(db: Session, workspace_id: str | None = None) -> dict[str, int | float]:
    statement = select(
            func.count(VerifiedAnswer.id),
            func.coalesce(func.avg(VerifiedAnswer.accuracy_percent), 0),
            func.coalesce(func.sum(VerifiedAnswer.monthly_adoption_count), 0),
            func.coalesce(func.sum(case((VerifiedAnswer.status == "DRAFT", 1), else_=0)), 0),
            func.coalesce(func.sum(case((VerifiedAnswer.is_favorite.is_(True), 1), else_=0)), 0),
            func.coalesce(func.sum(case((VerifiedAnswer.status == "DRAFT", 1), else_=0)), 0),
            func.coalesce(func.sum(case((VerifiedAnswer.status == "VERIFIED", 1), else_=0)), 0),
            func.coalesce(func.sum(case((VerifiedAnswer.status == "REJECTED", 1), else_=0)), 0),
            func.coalesce(func.sum(case((VerifiedAnswer.status == "DEPRECATED", 1), else_=0)), 0),
        )
    if workspace_id:
        statement = statement.where(VerifiedAnswer.workspace_id == workspace_id)
    row = db.execute(statement).one()
    return {
        "total": row[0],
        "average_accuracy": round(float(row[1]), 1),
        "monthly_adoptions": row[2],
        "pending_review": row[3],
        "favorites": row[4],
        "drafts": row[5],
        "published": row[6],
        "verified": row[6],
        "rejected": row[7],
        "deprecated": row[8],
    }


def list_answers(
    db: Session,
    *,
    query: str = "",
    tab: str = "all",
    page: int = 1,
    page_size: int = 6,
    workspace_id: str | None = None,
) -> tuple[list[VerifiedAnswer], int]:
    statement = select(VerifiedAnswer)
    if workspace_id:
        statement = statement.where(VerifiedAnswer.workspace_id == workspace_id)
    if query.strip():
        keyword = f"%{query.strip()}%"
        statement = statement.where(or_(
            VerifiedAnswer.question.ilike(keyword),
            VerifiedAnswer.model_name.ilike(keyword),
            VerifiedAnswer.owner_name.ilike(keyword),
        ))
    if tab == "favorites":
        statement = statement.where(VerifiedAnswer.is_favorite.is_(True))
    elif tab in {"drafts", "review"}:
        statement = statement.where(VerifiedAnswer.status == "DRAFT")
    elif tab in {"published", "verified"}:
        statement = statement.where(VerifiedAnswer.status == "VERIFIED")
    elif tab == "rejected":
        statement = statement.where(VerifiedAnswer.status == "REJECTED")
    elif tab == "deprecated":
        statement = statement.where(VerifiedAnswer.status == "DEPRECATED")

    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = list(db.scalars(
        statement.order_by(VerifiedAnswer.sort_order, VerifiedAnswer.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ))
    return items, total


def dashboard_summary(db: Session, workspace_id: str | None = None) -> dict[str, int]:
    statement = select(
        func.count(Dashboard.id),
        func.coalesce(func.sum(case((Dashboard.is_shared.is_(True), 1), else_=0)), 0),
        func.coalesce(func.sum(Dashboard.refresh_count_today), 0),
    )
    if workspace_id:
        statement = statement.where(Dashboard.workspace_id == workspace_id)
    row = db.execute(statement).one()
    cards_statement = select(func.count(DashboardCard.id)).join(Dashboard, DashboardCard.dashboard_id == Dashboard.id)
    if workspace_id:
        cards_statement = cards_statement.where(Dashboard.workspace_id == workspace_id)
    return {
        "total": row[0],
        "cards": db.scalar(cards_statement) or 0,
        "shared": row[1],
        "refreshes_today": row[2],
    }


def _dashboard_payload(dashboard: Dashboard, card_count: int) -> dict:
    return {
        "id": dashboard.id,
        "name": dashboard.name,
        "description": dashboard.description,
        "card_count": card_count,
        "is_shared": dashboard.is_shared,
        "refresh_count_today": dashboard.refresh_count_today,
        "status": dashboard.status,
        "trend_variant": dashboard.trend_variant,
        "updated_at": dashboard.updated_at,
    }


def list_dashboards(
    db: Session,
    *,
    query: str = "",
    sort: str = "recent",
    page: int = 1,
    page_size: int = 6,
    workspace_id: str | None = None,
) -> tuple[list[dict], int]:
    actual_card_count = func.count(DashboardCard.id).label("actual_card_count")
    statement = select(Dashboard, actual_card_count).outerjoin(
        DashboardCard, DashboardCard.dashboard_id == Dashboard.id,
    ).group_by(Dashboard.id)
    total_statement = select(func.count(Dashboard.id))
    if workspace_id:
        statement = statement.where(Dashboard.workspace_id == workspace_id)
        total_statement = total_statement.where(Dashboard.workspace_id == workspace_id)
    if query.strip():
        keyword = f"%{query.strip()}%"
        statement = statement.where(or_(Dashboard.name.ilike(keyword), Dashboard.description.ilike(keyword)))
        total_statement = total_statement.where(or_(Dashboard.name.ilike(keyword), Dashboard.description.ilike(keyword)))
    total = db.scalar(total_statement) or 0
    ordering = {
        "name": (Dashboard.name.asc(),),
        "cards": (actual_card_count.desc(), Dashboard.name.asc()),
        "recent": (Dashboard.updated_at.desc(), Dashboard.sort_order.asc()),
    }.get(sort, (Dashboard.updated_at.desc(), Dashboard.sort_order.asc()))
    rows = list(db.execute(
        statement.order_by(*ordering).offset((page - 1) * page_size).limit(page_size)
    ))
    return [_dashboard_payload(dashboard, card_count) for dashboard, card_count in rows], total


def _number(value) -> float:
    return float(value or 0)


def _percent_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return round((current - previous) / previous * 100, 1)


def dashboard_detail(db: Session, dashboard: Dashboard) -> dict:
    datasource = db.scalar(
        select(DataSource)
        .where(DataSource.type == "postgresql", DataSource.name == "Demo PostgreSQL", DataSource.workspace_id == dashboard.workspace_id)
        .order_by(DataSource.created_at)
    )
    if datasource is None:
        raise LookupError("Demo PostgreSQL datasource is not configured")
    connector = build_connector(datasource)

    summary = connector.read_rows("""
        WITH bounds AS (SELECT max(kpi_date) AS max_date FROM demo_business.daily_kpi),
        current_period AS (
          SELECT sum(revenue) AS revenue, sum(revenue-cost) AS profit,
                 sum(order_count) AS order_count, sum(charging_kwh) AS charging_kwh
          FROM demo_business.daily_kpi, bounds
          WHERE kpi_date BETWEEN max_date - interval '29 days' AND max_date
        ),
        previous_period AS (
          SELECT sum(revenue) AS revenue, sum(revenue-cost) AS profit,
                 sum(order_count) AS order_count, sum(charging_kwh) AS charging_kwh
          FROM demo_business.daily_kpi, bounds
          WHERE kpi_date BETWEEN max_date - interval '59 days' AND max_date - interval '30 days'
        ),
        active_customers AS (
          SELECT count(DISTINCT customer_id) AS customers
          FROM demo_business.orders, bounds
          WHERE order_date BETWEEN max_date - interval '29 days' AND max_date
        ),
        previous_customers AS (
          SELECT count(DISTINCT customer_id) AS customers
          FROM demo_business.orders, bounds
          WHERE order_date BETWEEN max_date - interval '59 days' AND max_date - interval '30 days'
        )
        SELECT bounds.max_date, current_period.revenue, current_period.profit,
               current_period.order_count, current_period.charging_kwh,
               previous_period.revenue AS previous_revenue,
               previous_period.profit AS previous_profit,
               active_customers.customers, previous_customers.customers AS previous_customers
        FROM bounds, current_period, previous_period, active_customers, previous_customers
    """)[0]
    trend = connector.read_rows("""
        WITH bounds AS (SELECT max(kpi_date) AS max_date FROM demo_business.daily_kpi)
        SELECT kpi_date, sum(revenue) AS revenue
        FROM demo_business.daily_kpi, bounds
        WHERE kpi_date BETWEEN max_date - interval '7 days' AND max_date
        GROUP BY kpi_date ORDER BY kpi_date
    """)
    regions = connector.read_rows("""
        WITH bounds AS (SELECT max(kpi_date) AS max_date FROM demo_business.daily_kpi),
        current_period AS (
          SELECT region_id, sum(revenue) AS revenue, sum(revenue-cost) AS profit,
                 sum(order_count) AS order_count, sum(charging_kwh) AS charging_kwh
          FROM demo_business.daily_kpi, bounds
          WHERE kpi_date BETWEEN max_date - interval '29 days' AND max_date
          GROUP BY region_id
        ),
        previous_period AS (
          SELECT region_id, sum(revenue) AS revenue
          FROM demo_business.daily_kpi, bounds
          WHERE kpi_date BETWEEN max_date - interval '59 days' AND max_date - interval '30 days'
          GROUP BY region_id
        )
        SELECT r.region_name AS region, c.order_count, c.revenue, c.profit, c.charging_kwh,
               p.revenue AS previous_revenue
        FROM current_period c
        JOIN previous_period p USING (region_id)
        JOIN demo_business.regions r ON r.region_id = c.region_id
        ORDER BY c.revenue DESC
    """)

    revenue = _number(summary["revenue"])
    profit = _number(summary["profit"])
    previous_revenue = _number(summary["previous_revenue"])
    previous_profit = _number(summary["previous_profit"])
    customers = int(summary["customers"] or 0)
    previous_customers = int(summary["previous_customers"] or 0)
    margin = round(profit / revenue * 100, 1) if revenue else 0.0
    previous_margin = round(previous_profit / previous_revenue * 100, 1) if previous_revenue else 0.0

    region_rows = []
    for row in regions:
        row_revenue = _number(row["revenue"])
        row_profit = _number(row["profit"])
        region_rows.append({
            "region": row["region"],
            "order_count": int(row["order_count"] or 0),
            "revenue": round(row_revenue, 2),
            "charging_kwh": round(_number(row["charging_kwh"]), 2),
            "margin_percent": round(row_profit / row_revenue * 100, 1) if row_revenue else 0,
            "change_percent": _percent_change(row_revenue, _number(row["previous_revenue"])),
        })
    leader = region_rows[0] if region_rows else None
    focus_candidates = [row for row in region_rows if not leader or row["region"] != leader["region"]]
    focus = min(focus_candidates or region_rows, key=lambda row: row["change_percent"], default=None)
    insight = "暂无足够数据生成经营洞察。"
    if leader and focus:
        insight = (
            f"{leader['region']}收入在当前周期领先，环比{leader['change_percent']:+.1f}%；"
            f"{focus['region']}环比{focus['change_percent']:+.1f}%，建议结合订单量与利润率继续核查区域增长质量。"
        )

    cards = []
    for card in db.scalars(select(DashboardCard).where(DashboardCard.dashboard_id == dashboard.id).order_by(DashboardCard.created_at)):
        answer = db.get(VerifiedAnswer, card.answer_id)
        run = db.get(QueryRun, card.query_run_id)
        cards.append({
            "id": card.id,
            "dashboard_id": card.dashboard_id,
            "answer_id": card.answer_id,
            "query_run_id": card.query_run_id,
            "chart_spec": card.chart_spec,
            "title": card.title,
            "position": card.position,
            "size": card.size,
            "filter_context": card.filter_context,
            "semantic_model_version": card.semantic_model_version,
            "result_signature": card.result_signature,
            "refresh_policy": card.refresh_policy,
            "source_question": answer.question if answer else "",
            "result_snapshot": run.execution_payload if run else {},
            "created_at": card.created_at,
            "updated_at": card.updated_at,
        })
    return {
        "dashboard": _dashboard_payload(dashboard, len(cards)),
        "data_as_of": summary["max_date"].isoformat(),
        "range_start": (summary["max_date"] - timedelta(days=29)).isoformat(),
        "range_end": summary["max_date"].isoformat(),
        "kpis": [
            {"label": "总收入", "value": round(revenue, 2), "unit": "元", "change": _percent_change(revenue, previous_revenue)},
            {"label": "总利润", "value": round(profit, 2), "unit": "元", "change": _percent_change(profit, previous_profit)},
            {"label": "利润率", "value": margin, "unit": "%", "change": round(margin - previous_margin, 1), "change_unit": "pp"},
            {"label": "活跃客户", "value": customers, "unit": "个", "change": _percent_change(customers, previous_customers)},
        ],
        "revenue_trend": [{"date": row["kpi_date"].isoformat(), "revenue": round(_number(row["revenue"]), 2)} for row in trend],
        "regions": region_rows,
        "insight": insight,
        "cards": cards,
    }


def answer_version_snapshot(answer: VerifiedAnswer) -> dict:
    return {
        "question": answer.question,
        "status": answer.status,
        "semantic_intent": answer.semantic_intent,
        "sql_plan": answer.sql_plan,
        "sql": answer.sql_text,
        "result_snapshot": answer.result_snapshot,
        "result_signature": answer.result_signature,
        "chart_spec": answer.chart_spec,
        "narrative": answer.narrative,
        "semantic_model_id": answer.semantic_model_id,
        "semantic_model_version": answer.semantic_model_version,
        "datasource_id": answer.datasource_id,
        "oracle_status": answer.oracle_status,
        "feedback": answer.feedback,
    }


def update_answer_status(db: Session, answer: VerifiedAnswer, *, status: str, feedback: str | None) -> VerifiedAnswer:
    if status == "VERIFIED" and answer.oracle_status != "PASSED":
        raise ValueError("Only an Oracle-passed answer can be VERIFIED")
    answer.status = status
    if feedback is not None:
        answer.feedback = {**(answer.feedback or {}), "status_comment": feedback}
    next_version = (db.scalar(select(func.coalesce(func.max(AnswerVersion.version), 0)).where(AnswerVersion.answer_id == answer.id)) or 0) + 1
    db.flush()
    db.add(AnswerVersion(answer_id=answer.id, version=next_version, snapshot=answer_version_snapshot(answer)))
    db.commit()
    db.refresh(answer)
    return answer


def create_dashboard_card(db: Session, dashboard: Dashboard, *, answer: VerifiedAnswer, data) -> DashboardCard:
    if answer.status != "VERIFIED" or answer.oracle_status != "PASSED":
        raise ValueError("Only a VERIFIED Oracle-passed answer can become a dashboard card")
    if not answer.query_run_id or not answer.chart_spec:
        raise ValueError("Answer has no bound query result or ChartSpec")
    card = DashboardCard(
        dashboard_id=dashboard.id,
        answer_id=answer.id,
        query_run_id=answer.query_run_id,
        chart_spec=answer.chart_spec,
        title=data.title or answer.question[:255],
        position=data.position,
        size=data.size,
        filter_context=data.filter_context,
        semantic_model_version=answer.semantic_model_version or 1,
        result_signature=answer.result_signature,
        refresh_policy=data.refresh_policy,
    )
    db.add(card)
    db.flush()
    dashboard.card_count = len(list(db.scalars(select(DashboardCard.id).where(DashboardCard.dashboard_id == dashboard.id))))
    db.commit()
    db.refresh(card)
    return card


def refresh_dashboard_card(db: Session, card: DashboardCard) -> DashboardCard:
    from app.query.contracts import AskRequest
    from app.query.service import QueryPipeline

    answer = db.get(VerifiedAnswer, card.answer_id)
    if answer is None or not answer.datasource_id or not answer.semantic_model_id:
        raise ValueError("Card source answer is incomplete")
    run = QueryPipeline().execute(db, AskRequest(
        question=answer.question,
        datasource_id=answer.datasource_id,
        semantic_model_id=answer.semantic_model_id,
    ))
    if run.status != "SUCCEEDED":
        raise ValueError(f"Card refresh query failed: {run.status}")
    card.query_run_id = run.id
    card.chart_spec = run.chart_spec_payload
    card.result_signature = run.result_signature
    card.semantic_model_version = run.semantic_model_version
    dashboard = db.get(Dashboard, card.dashboard_id)
    if dashboard:
        dashboard.refresh_count_today += 1
    db.commit()
    db.refresh(card)
    return card


def dashboard_card_payload(db: Session, card: DashboardCard) -> dict:
    answer = db.get(VerifiedAnswer, card.answer_id)
    run = db.get(QueryRun, card.query_run_id)
    return {
        **{name: getattr(card, name) for name in (
            "id", "dashboard_id", "answer_id", "query_run_id", "chart_spec", "title", "position", "size",
            "filter_context", "semantic_model_version", "result_signature", "refresh_policy", "created_at", "updated_at",
        )},
        "source_question": answer.question if answer else "",
        "result_snapshot": run.execution_payload if run else {},
    }
