import re
from datetime import datetime, timezone

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    AnswerVersion,
    AuditEvent,
    Dashboard,
    DashboardCard,
    DataSource,
    DataSourceColumn,
    DataSourceSchema,
    DataSourceTable,
    QueryRun,
    VerifiedAnswer,
)
from app.core.access import Principal
from app.core.data_safety import (
    SENSITIVE_COMMENT_MARKER,
    is_sensitive_column,
    redact_public_sql,
    redact_public_sql_payload,
)
from app.services.datasources import runtime_dialect



_ANSWER_PUBLIC_FIELDS = (
    "id", "question", "module", "sql_synced", "model_name", "owner_name", "status",
    "accuracy_percent", "adoption_count", "is_favorite", "query_run_id", "sql_text",
    "result_signature", "semantic_model_version", "semantic_intent", "sql_plan",
    "result_snapshot", "chart_spec", "narrative", "semantic_model_id", "datasource_id",
    "oracle_status", "feedback", "created_at", "updated_at",
)


def _answer_redaction_context(
    db: Session,
    answer: VerifiedAnswer,
) -> tuple[str, list[str]]:
    datasource = db.get(DataSource, answer.datasource_id) if answer.datasource_id else None
    dialect = (
        runtime_dialect(datasource)
        if datasource is not None
        else str(
            (answer.sql_plan or {}).get("dialect")
            or (answer.result_snapshot or {}).get("dialect")
            or "postgresql"
        )
    )
    if datasource is None:
        return dialect, []
    rows = db.execute(
        select(DataSourceColumn.name, DataSourceColumn.comment)
        .join(DataSourceTable, DataSourceColumn.table_id == DataSourceTable.id)
        .join(DataSourceSchema, DataSourceTable.schema_id == DataSourceSchema.id)
        .where(DataSourceSchema.datasource_id == datasource.id)
    )
    sensitive_columns = sorted({
        name
        for name, comment in rows
        if is_sensitive_column(name) or SENSITIVE_COMMENT_MARKER in (comment or "")
    })
    return dialect, sensitive_columns


def _redact_sql_workspace_question(
    value: object,
    sensitive_columns: list[str],
    *,
    dialect: str,
) -> object:
    prefix = "SQL 工作台验证："
    if not isinstance(value, str):
        return value
    if value.startswith(prefix):
        public_sql = redact_public_sql(
            value[len(prefix):], sensitive_columns, dialect=dialect,
        )
        return prefix + (public_sql or "")
    if re.match(r"^\s*(?:SELECT|WITH)\b", value, re.IGNORECASE):
        return redact_public_sql(value, sensitive_columns, dialect=dialect)
    return value


def public_answer_payload(
    db: Session,
    answer: VerifiedAnswer,
    *,
    include_versions: bool = False,
) -> dict:
    """Serialize an answer for API consumers without exposing SQL literals."""

    dialect, sensitive_columns = _answer_redaction_context(db, answer)
    payload = {field: getattr(answer, field) for field in _ANSWER_PUBLIC_FIELDS}
    payload = redact_public_sql_payload(
        payload, sensitive_columns, dialect=dialect,
    )
    payload["question"] = _redact_sql_workspace_question(
        payload.get("question"), sensitive_columns, dialect=dialect,
    )
    if include_versions:
        versions = []
        for version in sorted(answer.versions, key=lambda item: item.version):
            snapshot = redact_public_sql_payload(
                version.snapshot or {}, sensitive_columns, dialect=dialect,
            )
            if "question" in snapshot:
                snapshot["question"] = _redact_sql_workspace_question(
                    snapshot.get("question"), sensitive_columns, dialect=dialect,
                )
            versions.append({
                "id": version.id,
                "version": version.version,
                "snapshot": snapshot,
                "created_at": version.created_at,
            })
        payload["versions"] = versions
    return payload


def _public_answer_bound_payload(
    db: Session,
    answer: VerifiedAnswer | None,
    payload,
):
    if answer is None:
        return redact_public_sql_payload(payload, [], dialect="postgresql")
    dialect, sensitive_columns = _answer_redaction_context(db, answer)
    return redact_public_sql_payload(
        payload, sensitive_columns, dialect=dialect,
    )


def answer_summary(
    db: Session,
    workspace_id: str | None = None,
    *,
    allowed_ids: list[str] | None = None,
) -> dict[str, int | float]:
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
    if allowed_ids is not None:
        statement = statement.where(VerifiedAnswer.id.in_(allowed_ids))
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
    allowed_ids: list[str] | None = None,
) -> tuple[list[VerifiedAnswer], int]:
    statement = select(VerifiedAnswer)
    if workspace_id:
        statement = statement.where(VerifiedAnswer.workspace_id == workspace_id)
    if allowed_ids is not None:
        statement = statement.where(VerifiedAnswer.id.in_(allowed_ids))
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


def dashboard_summary(
    db: Session,
    workspace_id: str | None = None,
    *,
    allowed_ids: list[str] | None = None,
) -> dict[str, int]:
    statement = select(
        func.count(Dashboard.id),
        func.coalesce(func.sum(case((Dashboard.is_shared.is_(True), 1), else_=0)), 0),
    )
    if workspace_id:
        statement = statement.where(Dashboard.workspace_id == workspace_id)
    if allowed_ids is not None:
        statement = statement.where(Dashboard.id.in_(allowed_ids))
    row = db.execute(statement).one()
    cards_statement = select(func.count(DashboardCard.id)).join(Dashboard, DashboardCard.dashboard_id == Dashboard.id)
    if workspace_id:
        cards_statement = cards_statement.where(Dashboard.workspace_id == workspace_id)
    if allowed_ids is not None:
        cards_statement = cards_statement.where(Dashboard.id.in_(allowed_ids))
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    refreshes_statement = select(func.count(AuditEvent.id)).where(
        AuditEvent.action == "REFRESH_CARD",
        AuditEvent.resource_type == "DASHBOARD",
        AuditEvent.status == "SUCCESS",
        AuditEvent.created_at >= today_start,
    )
    if workspace_id:
        refreshes_statement = refreshes_statement.where(AuditEvent.workspace_id == workspace_id)
    if allowed_ids is not None:
        refreshes_statement = refreshes_statement.where(AuditEvent.resource_id.in_(allowed_ids))
    return {
        "total": row[0],
        "cards": db.scalar(cards_statement) or 0,
        "shared": row[1],
        "refreshes_today": db.scalar(refreshes_statement) or 0,
    }


def _dashboard_payload(dashboard: Dashboard, card_count: int, refresh_count_today: int) -> dict:
    return {
        "id": dashboard.id,
        "name": dashboard.name,
        "description": dashboard.description,
        "card_count": card_count,
        "is_shared": dashboard.is_shared,
        "refresh_count_today": refresh_count_today,
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
    allowed_ids: list[str] | None = None,
) -> tuple[list[dict], int]:
    actual_card_count = func.count(DashboardCard.id).label("actual_card_count")
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    actual_refresh_count = (
        select(func.count(AuditEvent.id))
        .where(
            AuditEvent.resource_id == Dashboard.id,
            AuditEvent.workspace_id == Dashboard.workspace_id,
            AuditEvent.action == "REFRESH_CARD",
            AuditEvent.resource_type == "DASHBOARD",
            AuditEvent.status == "SUCCESS",
            AuditEvent.created_at >= today_start,
        )
        .correlate(Dashboard)
        .scalar_subquery()
        .label("actual_refresh_count")
    )
    statement = select(Dashboard, actual_card_count, actual_refresh_count).outerjoin(
        DashboardCard, DashboardCard.dashboard_id == Dashboard.id,
    ).group_by(Dashboard.id)
    total_statement = select(func.count(Dashboard.id))
    if workspace_id:
        statement = statement.where(Dashboard.workspace_id == workspace_id)
        total_statement = total_statement.where(Dashboard.workspace_id == workspace_id)
    if allowed_ids is not None:
        statement = statement.where(Dashboard.id.in_(allowed_ids))
        total_statement = total_statement.where(Dashboard.id.in_(allowed_ids))
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
    return [_dashboard_payload(dashboard, card_count, refresh_count) for dashboard, card_count, refresh_count in rows], total


def _number(value) -> float:
    return float(value or 0)


def _percent_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return round((current - previous) / previous * 100, 1)


def dashboard_detail(db: Session, dashboard: Dashboard, principal: Principal) -> dict:
    cards = []
    for card in db.scalars(select(DashboardCard).where(DashboardCard.dashboard_id == dashboard.id).order_by(DashboardCard.created_at)):
        answer = db.get(VerifiedAnswer, card.answer_id)
        run = db.get(QueryRun, card.query_run_id)
        source_question = answer.question if answer else ""
        if answer is not None:
            dialect, sensitive_columns = _answer_redaction_context(db, answer)
            source_question = _redact_sql_workspace_question(
                source_question, sensitive_columns, dialect=dialect,
            )
        cards.append(_public_answer_bound_payload(db, answer, {
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
            "source_question": source_question,
            "result_snapshot": run.execution_payload if run else {},
            "created_at": card.created_at,
            "updated_at": card.updated_at,
        }))
    return {
        "dashboard": _dashboard_payload(
            dashboard,
            len(cards),
            db.scalar(select(func.count(AuditEvent.id)).where(
                AuditEvent.resource_id == dashboard.id,
                AuditEvent.workspace_id == dashboard.workspace_id,
                AuditEvent.action == "REFRESH_CARD",
                AuditEvent.resource_type == "DASHBOARD",
                AuditEvent.status == "SUCCESS",
                AuditEvent.created_at >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0),
            )) or 0,
        ),
        "data_as_of": dashboard.updated_at.date().isoformat(),
        "range_start": "",
        "range_end": "",
        "kpis": [],
        "revenue_trend": [],
        "regions": [],
        "insight": "",
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


def refresh_dashboard_card(
    db: Session,
    card: DashboardCard,
    *,
    principal: Principal,
) -> DashboardCard:
    from app.query.contracts import AskRequest
    from app.query.service import QueryPipeline

    answer = db.get(VerifiedAnswer, card.answer_id)
    if answer is None or not answer.datasource_id or not answer.semantic_model_id:
        raise ValueError("Card source answer is incomplete")
    run = QueryPipeline().execute(db, AskRequest(
        question=answer.question,
        datasource_id=answer.datasource_id,
        semantic_model_id=answer.semantic_model_id,
    ), principal=principal)
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
    source_question = answer.question if answer else ""
    if answer is not None:
        dialect, sensitive_columns = _answer_redaction_context(db, answer)
        source_question = _redact_sql_workspace_question(
            source_question, sensitive_columns, dialect=dialect,
        )
    return _public_answer_bound_payload(db, answer, {
        **{name: getattr(card, name) for name in (
            "id", "dashboard_id", "answer_id", "query_run_id", "chart_spec", "title", "position", "size",
            "filter_context", "semantic_model_version", "result_signature", "refresh_policy", "created_at", "updated_at",
        )},
        "source_question": source_question,
        "result_snapshot": run.execution_payload if run else {},
    })
