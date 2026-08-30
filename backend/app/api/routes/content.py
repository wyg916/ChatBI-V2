from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.access import (
    Principal,
    ensure_resource_access,
    grant_created_resource,
    record_audit,
    require_permission,
)
from app.db.session import get_db
from app.models import Dashboard, DashboardCard, ResourceGrant, VerifiedAnswer
from app.query.contracts import AskRequest, QueryResponse
from app.query.service import QueryPipeline, query_response
from app.schemas.content import (
    AnswerCreate,
    AnswerDetailResponse,
    AnswerLibraryResponse,
    AnswerRead,
    AnswerStatusUpdate,
    DashboardCardCreate,
    DashboardCardRead,
    DashboardCreate,
    DashboardDetailResponse,
    DashboardLibraryResponse,
    DashboardRead,
)
from app.services.content import (
    answer_summary,
    create_dashboard_card,
    dashboard_card_payload,
    dashboard_detail,
    dashboard_summary,
    list_answers,
    list_dashboards,
    public_answer_payload,
    refresh_dashboard_card,
    update_answer_status,
)
from app.services.datasources import default_workspace

router = APIRouter(tags=["answers and dashboards"])


def _allowed_resource_ids(
    db: Session,
    principal: Principal,
    resource_type: str,
) -> list[str] | None:
    if principal.role == "ADMIN":
        return None
    return list(db.scalars(select(ResourceGrant.resource_id).where(
        ResourceGrant.user_id == principal.user_id,
        ResourceGrant.resource_type == resource_type,
        ResourceGrant.can_read.is_(True),
    )))


@router.get("/answers", response_model=AnswerLibraryResponse)
def get_answers(
    query: str = "",
    tab: str = Query(default="all", pattern="^(all|favorites|drafts|review|published|verified|rejected|deprecated)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=6, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("answer.read")),
):
    allowed_ids = _allowed_resource_ids(db, principal, "ANSWER")
    items, total = list_answers(
        db, query=query, tab=tab, page=page, page_size=page_size,
        workspace_id=principal.workspace_id, allowed_ids=allowed_ids,
    )
    return {
        "summary": answer_summary(db, principal.workspace_id, allowed_ids=allowed_ids),
        "items": [public_answer_payload(db, item) for item in items],
        "total": total, "page": page, "page_size": page_size,
    }


@router.post("/answers", response_model=AnswerRead, status_code=status.HTTP_201_CREATED)
def create_answer(
    data: AnswerCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("answer.manage")),
):
    if data.status != "DRAFT":
        raise HTTPException(status_code=422, detail="Manually created answers must start as DRAFT")
    sort_order = (db.scalar(select(func.coalesce(func.max(VerifiedAnswer.sort_order), 0))) or 0) + 1
    answer = VerifiedAnswer(
        workspace_id=principal.workspace_id,
        question=data.question,
        module=data.module,
        sql_synced=False,
        model_name=data.model_name,
        owner_name=data.owner_name,
        status=data.status,
        accuracy_percent=data.accuracy_percent,
        sort_order=sort_order,
    )
    db.add(answer)
    db.flush()
    grant_created_resource(
        db, principal, resource_type="ANSWER", resource_id=answer.id,
    )
    record_audit(db, principal, action="CREATE", resource_type="ANSWER", resource_id=answer.id)
    db.commit()
    db.refresh(answer)
    return public_answer_payload(db, answer)


@router.get("/answers/{answer_id}", response_model=AnswerDetailResponse)
def get_answer(
    answer_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("answer.read")),
):
    answer = db.get(VerifiedAnswer, answer_id)
    if answer is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    ensure_resource_access(db, principal, resource_type="ANSWER", resource_id=answer_id)
    return public_answer_payload(db, answer, include_versions=True)


@router.patch("/answers/{answer_id}/status", response_model=AnswerRead)
def set_answer_status(
    answer_id: str,
    data: AnswerStatusUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("answer.manage")),
):
    answer = db.get(VerifiedAnswer, answer_id)
    if answer is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    ensure_resource_access(
        db, principal, resource_type="ANSWER", resource_id=answer_id, query=True,
    )
    try:
        updated = update_answer_status(db, answer, status=data.status, feedback=data.feedback)
        record_audit(
            db, principal, action="UPDATE_STATUS", resource_type="ANSWER", resource_id=answer.id,
            details={"status": data.status},
        )
        db.commit()
        return public_answer_payload(db, updated)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/answers/{answer_id}/reuse", response_model=QueryResponse, status_code=status.HTTP_201_CREATED)
def reuse_answer(
    answer_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("answer.manage")),
):
    answer = db.get(VerifiedAnswer, answer_id)
    if answer is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    ensure_resource_access(
        db, principal, resource_type="ANSWER", resource_id=answer_id, query=True,
    )
    if answer.status != "VERIFIED" or not answer.datasource_id or not answer.semantic_model_id:
        raise HTTPException(status_code=422, detail="Only a complete VERIFIED answer can be reused")
    run = QueryPipeline().execute(db, AskRequest(
        question=answer.question,
        datasource_id=answer.datasource_id,
        semantic_model_id=answer.semantic_model_id,
    ), principal=principal)
    answer.adoption_count += 1
    answer.monthly_adoption_count += 1
    record_audit(db, principal, action="REUSE", resource_type="ANSWER", resource_id=answer.id)
    db.commit()
    return query_response(run)


@router.get("/dashboards", response_model=DashboardLibraryResponse)
def get_dashboards(
    query: str = "",
    sort: str = Query(default="recent", pattern="^(recent|name|cards)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=6, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("dashboard.read")),
):
    allowed_ids = _allowed_resource_ids(db, principal, "DASHBOARD")
    items, total = list_dashboards(
        db, query=query, sort=sort, page=page, page_size=page_size,
        workspace_id=principal.workspace_id, allowed_ids=allowed_ids,
    )
    return {
        "summary": dashboard_summary(db, principal.workspace_id, allowed_ids=allowed_ids),
        "items": items, "total": total, "page": page, "page_size": page_size,
    }


@router.post("/dashboards", response_model=DashboardRead, status_code=status.HTTP_201_CREATED)
def create_dashboard(
    data: DashboardCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("dashboard.manage")),
):
    sort_order = (db.scalar(select(func.coalesce(func.max(Dashboard.sort_order), 0))) or 0) + 1
    dashboard = Dashboard(
        workspace_id=principal.workspace_id,
        name=data.name,
        description=data.description,
        card_count=0,
        is_shared=data.is_shared,
        trend_variant=sort_order % 6,
        sort_order=sort_order,
    )
    db.add(dashboard)
    db.flush()
    grant_created_resource(
        db, principal, resource_type="DASHBOARD", resource_id=dashboard.id,
    )
    record_audit(db, principal, action="CREATE", resource_type="DASHBOARD", resource_id=dashboard.id)
    db.commit()
    db.refresh(dashboard)
    return dashboard


@router.get("/dashboards/{dashboard_id}", response_model=DashboardDetailResponse)
def get_dashboard_detail(
    dashboard_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("dashboard.read")),
):
    dashboard = db.get(Dashboard, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    ensure_resource_access(
        db, principal, resource_type="DASHBOARD", resource_id=dashboard_id, query=True,
    )
    try:
        return dashboard_detail(db, dashboard, principal)
    except (LookupError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/dashboards/{dashboard_id}/cards", response_model=DashboardCardRead, status_code=status.HTTP_201_CREATED)
def add_dashboard_card(
    dashboard_id: str,
    data: DashboardCardCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("dashboard.manage")),
):
    dashboard = db.get(Dashboard, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    ensure_resource_access(
        db, principal, resource_type="DASHBOARD", resource_id=dashboard_id, query=True,
    )
    answer = db.get(VerifiedAnswer, data.answer_id)
    if answer is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    ensure_resource_access(
        db, principal, resource_type="ANSWER", resource_id=answer.id, query=True,
    )
    try:
        card = create_dashboard_card(db, dashboard, answer=answer, data=data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = dashboard_card_payload(db, card)
    record_audit(db, principal, action="ADD_CARD", resource_type="DASHBOARD", resource_id=dashboard.id, details={"card_id": card.id})
    db.commit()
    return payload


def _card_or_404(db: Session, dashboard_id: str, card_id: str) -> DashboardCard:
    card = db.get(DashboardCard, card_id)
    if card is None or card.dashboard_id != dashboard_id:
        raise HTTPException(status_code=404, detail="Dashboard card not found")
    return card


@router.post("/dashboards/{dashboard_id}/cards/{card_id}/refresh", response_model=DashboardCardRead)
def refresh_card(
    dashboard_id: str,
    card_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("dashboard.manage")),
):
    ensure_resource_access(
        db, principal, resource_type="DASHBOARD", resource_id=dashboard_id, query=True,
    )
    try:
        card = _card_or_404(db, dashboard_id, card_id)
        ensure_resource_access(
            db, principal, resource_type="ANSWER", resource_id=card.answer_id, query=True,
        )
        card = refresh_dashboard_card(db, card, principal=principal)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = dashboard_card_payload(db, card)
    record_audit(db, principal, action="REFRESH_CARD", resource_type="DASHBOARD", resource_id=dashboard_id, details={"card_id": card.id})
    db.commit()
    return payload


@router.delete("/dashboards/{dashboard_id}/cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_card(
    dashboard_id: str,
    card_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("dashboard.manage")),
):
    ensure_resource_access(
        db, principal, resource_type="DASHBOARD", resource_id=dashboard_id, query=True,
    )
    card = _card_or_404(db, dashboard_id, card_id)
    dashboard = db.get(Dashboard, dashboard_id)
    db.delete(card)
    db.flush()
    if dashboard:
        dashboard.card_count = len(list(db.scalars(select(DashboardCard.id).where(DashboardCard.dashboard_id == dashboard_id))))
    record_audit(db, principal, action="DELETE_CARD", resource_type="DASHBOARD", resource_id=dashboard_id, details={"card_id": card_id})
    db.commit()
