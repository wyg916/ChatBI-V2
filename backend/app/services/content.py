from datetime import timedelta

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.models import Dashboard, DataSource, VerifiedAnswer
from app.services.datasources import build_connector


def answer_summary(db: Session) -> dict[str, int | float]:
    row = db.execute(
        select(
            func.count(VerifiedAnswer.id),
            func.coalesce(func.avg(VerifiedAnswer.accuracy_percent), 0),
            func.coalesce(func.sum(VerifiedAnswer.monthly_adoption_count), 0),
            func.coalesce(func.sum(case((VerifiedAnswer.status == "REVIEW", 1), else_=0)), 0),
            func.coalesce(func.sum(case((VerifiedAnswer.is_favorite.is_(True), 1), else_=0)), 0),
            func.coalesce(func.sum(case((VerifiedAnswer.status == "DRAFT", 1), else_=0)), 0),
            func.coalesce(func.sum(case((VerifiedAnswer.status == "PUBLISHED", 1), else_=0)), 0),
        )
    ).one()
    return {
        "total": row[0],
        "average_accuracy": round(float(row[1]), 1),
        "monthly_adoptions": row[2],
        "pending_review": row[3],
        "favorites": row[4],
        "drafts": row[5],
        "published": row[6],
    }


def list_answers(
    db: Session,
    *,
    query: str = "",
    tab: str = "all",
    page: int = 1,
    page_size: int = 6,
) -> tuple[list[VerifiedAnswer], int]:
    statement = select(VerifiedAnswer)
    if query.strip():
        keyword = f"%{query.strip()}%"
        statement = statement.where(or_(
            VerifiedAnswer.question.ilike(keyword),
            VerifiedAnswer.model_name.ilike(keyword),
            VerifiedAnswer.owner_name.ilike(keyword),
        ))
    if tab == "favorites":
        statement = statement.where(VerifiedAnswer.is_favorite.is_(True))
    elif tab == "drafts":
        statement = statement.where(VerifiedAnswer.status == "DRAFT")
    elif tab == "published":
        statement = statement.where(VerifiedAnswer.status == "PUBLISHED")
    elif tab == "review":
        statement = statement.where(VerifiedAnswer.status == "REVIEW")

    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = list(db.scalars(
        statement.order_by(VerifiedAnswer.sort_order, VerifiedAnswer.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ))
    return items, total


def dashboard_summary(db: Session) -> dict[str, int]:
    row = db.execute(
        select(
            func.count(Dashboard.id),
            func.coalesce(func.sum(Dashboard.card_count), 0),
            func.coalesce(func.sum(case((Dashboard.is_shared.is_(True), 1), else_=0)), 0),
            func.coalesce(func.sum(Dashboard.refresh_count_today), 0),
        )
    ).one()
    return {"total": row[0], "cards": row[1], "shared": row[2], "refreshes_today": row[3]}


def list_dashboards(
    db: Session,
    *,
    query: str = "",
    sort: str = "recent",
    page: int = 1,
    page_size: int = 6,
) -> tuple[list[Dashboard], int]:
    statement = select(Dashboard)
    if query.strip():
        keyword = f"%{query.strip()}%"
        statement = statement.where(or_(Dashboard.name.ilike(keyword), Dashboard.description.ilike(keyword)))
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    ordering = {
        "name": (Dashboard.name.asc(),),
        "cards": (Dashboard.card_count.desc(), Dashboard.name.asc()),
        "recent": (Dashboard.updated_at.desc(), Dashboard.sort_order.asc()),
    }.get(sort, (Dashboard.updated_at.desc(), Dashboard.sort_order.asc()))
    items = list(db.scalars(
        statement.order_by(*ordering).offset((page - 1) * page_size).limit(page_size)
    ))
    return items, total


def _number(value) -> float:
    return float(value or 0)


def _percent_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return round((current - previous) / previous * 100, 1)


def dashboard_detail(db: Session, dashboard: Dashboard) -> dict:
    datasource = db.scalar(
        select(DataSource)
        .where(DataSource.type == "postgresql", DataSource.name == "Demo PostgreSQL")
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

    return {
        "dashboard": dashboard,
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
    }
