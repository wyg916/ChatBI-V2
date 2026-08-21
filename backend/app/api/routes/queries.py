from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.access import Principal, require_permission
from app.db.session import get_db
from app.models import QueryRun
from app.query.contracts import (
    AskRequest,
    FeedbackRequest,
    QueryResponse,
    SaveAnswerRequest,
    VerifyResultRequest,
)
from app.query.nl2sql import Nl2SqlRouter
from app.model_gateway import ModelGateway
from app.query.service import QueryPipeline, query_response, save_feedback, save_verified_answer
from app.core.config import get_settings
from app.schemas.content import AnswerRead
from chatbi_agent_contracts import AgentRole, ToolName
from chatbi_rag_adapter import LiveRagAdapter

router = APIRouter(tags=["query pipeline"])


def _run_or_404(db: Session, query_id: str, principal: Principal) -> QueryRun:
    run = db.get(QueryRun, query_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Query run not found")
    if run.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=403, detail="Query run access denied")
    return run


@router.get("/query-capabilities")
def query_capabilities(_: Principal = Depends(require_permission("query.ask"))):
    settings = get_settings()
    model_gateway = ModelGateway(settings)
    rag = LiveRagAdapter(
        base_url=settings.legacy_rag_base_url,
        shared_secret=settings.rag_shared_secret.get_secret_value(),
        retry_count=settings.rag_retry_count,
    )
    return {
        "nl2sql": Nl2SqlRouter().capabilities(),
        "model_control_plane": {
            "version": "v1.3",
            "single_provider_call_plane": True,
            "secrets_exposed": False,
            "providers": model_gateway.health_snapshot(),
            "policy": model_gateway.policy.safe_summary(),
        },
        "sql_guard": {
            "engine": "sqlglot",
            "ast_validation": True,
            "explain_cost_guard": True,
            "maximum_estimated_cost": settings.query_max_estimated_cost,
        },
        "result_oracle": {
            "version": "v1.3",
            "sql_string_equality": False,
            "checks": ["metric", "dimension", "time", "filter", "join", "result_value", "chart", "narrative"],
            "critical_verification_query": settings.verification_query_enabled,
        },
        "controlled_rag": {
            "mode": settings.rag_mode,
            "configured": bool(settings.legacy_rag_base_url),
            "live_bridge": rag.health(timeout_ms=settings.rag_health_timeout_ms),
            "workspace_identity_signed": bool(settings.rag_shared_secret.get_secret_value()),
            "fail_closed": True,
            "fallback_enabled": settings.rag_fallback_enabled,
        },
        "bounded_orchestration": {
            "mode": settings.agent_mode,
            "allowed_routes": sorted(settings.agent_route_allowlist),
            "fallback_enabled": settings.agent_fallback_enabled,
            "roles": [role.value for role in AgentRole],
            "tools": [tool.value for tool in ToolName],
            "budgets": {
                "max_steps": settings.agent_max_steps,
                "max_tool_calls": settings.agent_max_tool_calls,
                "max_replan": settings.agent_max_replan,
                "max_agent_depth": settings.agent_max_depth,
                "timeout_ms": settings.agent_timeout_ms,
            },
        },
    }


@router.post("/ask", response_model=QueryResponse, status_code=status.HTTP_201_CREATED)
def ask(data: AskRequest, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("query.ask"))):
    return query_response(QueryPipeline().execute(db, data, principal=principal))


@router.get("/queries/{query_id}", response_model=QueryResponse)
def get_query(query_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("query.ask"))):
    return query_response(_run_or_404(db, query_id, principal))


@router.post("/queries/{query_id}/verify", response_model=QueryResponse)
def verify_query(query_id: str, data: VerifyResultRequest, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("query.ask"))):
    try:
        run = QueryPipeline().verify(db, _run_or_404(db, query_id, principal), data.expected)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return query_response(run)


@router.post("/queries/{query_id}/feedback", status_code=status.HTTP_201_CREATED)
def feedback(query_id: str, data: FeedbackRequest, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("answer.manage"))):
    item = save_feedback(db, _run_or_404(db, query_id, principal), data)
    return {"id": item.id, "query_id": item.query_run_id, "feedback_type": item.feedback_type, "recorded": True}


@router.post("/queries/{query_id}/save", response_model=AnswerRead, status_code=status.HTTP_201_CREATED)
def save_answer(query_id: str, data: SaveAnswerRequest, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("answer.manage"))):
    try:
        return save_verified_answer(db, _run_or_404(db, query_id, principal), data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
