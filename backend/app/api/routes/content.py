from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Dashboard, VerifiedAnswer
from app.schemas.content import (
    AnswerCreate,
    AnswerLibraryResponse,
    AnswerRead,
    DashboardCreate,
    DashboardDetailResponse,
    DashboardLibraryResponse,
    DashboardRead,
)
from app.services.content import answer_summary, dashboard_detail, dashboard_summary, list_answers, list_dashboards
from app.services.datasources import default_workspace

router = APIRouter(tags=["answers and dashboards"])


@router.get("/answers", response_model=AnswerLibraryResponse)
def get_answers(
    query: str = "",
    tab: str = Query(default="all", pattern="^(all|favorites|drafts|published|review)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=6, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = list_answers(db, query=query, tab=tab, page=page, page_size=page_size)
    return {"summary": answer_summary(db), "items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/answers", response_model=AnswerRead, status_code=status.HTTP_201_CREATED)
def create_answer(data: AnswerCreate, db: Session = Depends(get_db)):
    workspace = default_workspace(db)
    sort_order = (db.scalar(select(func.coalesce(func.max(VerifiedAnswer.sort_order), 0))) or 0) + 1
    answer = VerifiedAnswer(
        workspace_id=workspace.id,
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
    db.commit()
    db.refresh(answer)
    return answer


@router.get("/dashboards", response_model=DashboardLibraryResponse)
def get_dashboards(
    query: str = "",
    sort: str = Query(default="recent", pattern="^(recent|name|cards)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=6, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = list_dashboards(db, query=query, sort=sort, page=page, page_size=page_size)
    return {"summary": dashboard_summary(db), "items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/dashboards", response_model=DashboardRead, status_code=status.HTTP_201_CREATED)
def create_dashboard(data: DashboardCreate, db: Session = Depends(get_db)):
    workspace = default_workspace(db)
    sort_order = (db.scalar(select(func.coalesce(func.max(Dashboard.sort_order), 0))) or 0) + 1
    dashboard = Dashboard(
        workspace_id=workspace.id,
        name=data.name,
        description=data.description,
        card_count=data.card_count,
        is_shared=data.is_shared,
        trend_variant=sort_order % 6,
        sort_order=sort_order,
    )
    db.add(dashboard)
    db.commit()
    db.refresh(dashboard)
    return dashboard


@router.get("/dashboards/{dashboard_id}", response_model=DashboardDetailResponse)
def get_dashboard_detail(dashboard_id: str, db: Session = Depends(get_db)):
    dashboard = db.get(Dashboard, dashboard_id)
    if dashboard is None:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    try:
        return dashboard_detail(db, dashboard)
    except LookupError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
