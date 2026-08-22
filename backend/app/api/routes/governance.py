from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.access import Principal, require_permission
from app.db.session import get_db
from app.schemas.governance import (
    CostDashboardResponse,
    EvaluationGovernanceDashboardResponse,
    ModelDashboardResponse,
    TraceDashboardResponse,
    TraceDetailResponse,
)
from app.services.governance import (
    cost_dashboard,
    evaluation_governance_dashboard,
    model_dashboard,
    trace_dashboard,
    trace_detail,
)


router = APIRouter(prefix="/governance", tags=["governance"])


@router.get("/cost", response_model=CostDashboardResponse)
def get_cost_dashboard(
    from_at: datetime | None = Query(default=None, alias="from"),
    to_at: datetime | None = Query(default=None, alias="to"),
    user_id: str | None = None,
    conversation_id: str | None = None,
    route: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.read")),
):
    return cost_dashboard(
        db,
        workspace_id=principal.workspace_id,
        from_at=from_at,
        to_at=to_at,
        user_id=user_id,
        conversation_id=conversation_id,
        route=route,
        provider=provider,
        model=model,
    )


@router.get("/traces", response_model=TraceDashboardResponse)
def get_trace_dashboard(
    from_at: datetime | None = Query(default=None, alias="from"),
    to_at: datetime | None = Query(default=None, alias="to"),
    user_id: str | None = None,
    route: str | None = None,
    status: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.read")),
):
    return trace_dashboard(
        db,
        workspace_id=principal.workspace_id,
        from_at=from_at,
        to_at=to_at,
        user_id=user_id,
        route=route,
        status=status,
        limit=limit,
    )


@router.get("/traces/{trace_id}", response_model=TraceDetailResponse)
def get_trace_detail(
    trace_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.read")),
):
    try:
        return trace_detail(db, workspace_id=principal.workspace_id, trace_id=trace_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/models", response_model=ModelDashboardResponse)
def get_model_dashboard(
    from_at: datetime | None = Query(default=None, alias="from"),
    to_at: datetime | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.read")),
):
    return model_dashboard(
        db,
        workspace_id=principal.workspace_id,
        from_at=from_at,
        to_at=to_at,
    )


@router.get("/evaluation", response_model=EvaluationGovernanceDashboardResponse)
def get_evaluation_governance_dashboard(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("evaluation.read")),
):
    return evaluation_governance_dashboard(db, workspace_id=principal.workspace_id)
