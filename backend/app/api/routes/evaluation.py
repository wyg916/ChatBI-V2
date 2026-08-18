from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.access import Principal, record_audit, require_permission
from app.db.session import get_db
from app.schemas.evaluation import (
    EvaluationCaseDetail,
    EvaluationComparisonRequest,
    EvaluationComparisonResponse,
    EvaluationCreate,
    EvaluationDashboardResponse,
    EvaluationOverviewResponse,
    EvaluationRunDetail,
    EvaluationRunRead,
    FeedbackCorrectCreate,
    FeedbackCorrectionCreate,
    FeedbackDashboardResponse,
    FeedbackRecallRequest,
    FeedbackReplayRequest,
    FeedbackReplayResponse,
    FeedbackReviewRequest,
    FeedbackWorkflowRead,
    ReleaseGateResponse,
)
from app.services.evaluation import (
    compare_evaluation_runs,
    create_evaluation,
    evaluation_case_detail,
    evaluation_dashboard,
    evaluation_overview,
    evaluation_run_detail,
    evaluation_run_view,
    release_gate,
    run_golden_evaluation,
)
from app.services.feedback_loop import (
    feedback_dashboard,
    recall_candidates,
    record_correct_feedback,
    replay_verified_sql,
    review_correction,
    submit_correction,
)

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.get("/overview", response_model=EvaluationOverviewResponse)
def get_evaluation_overview(db: Session = Depends(get_db), principal: Principal = Depends(require_permission("evaluation.read"))):
    try:
        return evaluation_overview(db, principal.workspace_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs", response_model=EvaluationRunDetail, status_code=status.HTTP_201_CREATED)
def run_evaluation(db: Session = Depends(get_db), principal: Principal = Depends(require_permission("evaluation.run"))):
    try:
        run = run_golden_evaluation(db, principal)
        record_audit(
            db, principal, action="EVALUATION_RUN", resource_type="EVALUATION_RUN",
            resource_id=run.id, status=run.status, details={"golden_set_count": run.golden_set_count},
        )
        db.commit()
        _, cases = evaluation_run_detail(db, run.id, principal.workspace_id)
        return {"run": evaluation_run_view(run, cases), "cases": cases}
    except (LookupError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=EvaluationRunDetail)
def get_evaluation_run(run_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("evaluation.read"))):
    try:
        run, cases = evaluation_run_detail(db, run_id, principal.workspace_id)
        return {"run": evaluation_run_view(run, cases), "cases": cases}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/cases/{case_ref}", response_model=EvaluationCaseDetail)
def get_evaluation_case(case_ref: str, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("evaluation.read"))):
    try:
        run, case, previous_id, next_id = evaluation_case_detail(db, case_ref, principal.workspace_id)
        _, cases = evaluation_run_detail(db, run.id, principal.workspace_id)
        return {"run": evaluation_run_view(run, cases), "case": case, "previous_case_id": previous_id, "next_case_id": next_id}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/definitions", response_model=EvaluationRunRead, status_code=status.HTTP_201_CREATED)
def create_evaluation_definition(
    data: EvaluationCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("evaluation.run")),
):
    try:
        run = create_evaluation(
            db,
            workspace_id=principal.workspace_id,
            name=data.name,
            profile=data.profile.model_dump(),
        )
        record_audit(db, principal, action="EVALUATION_CREATE", resource_type="EVALUATION_RUN", resource_id=run.id, details={"profile": data.profile.model_dump()})
        db.commit()
        return evaluation_run_view(run, [])
    except (LookupError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/runs/{run_id}/execute", response_model=EvaluationRunDetail)
def execute_evaluation_definition(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("evaluation.run")),
):
    try:
        run = run_golden_evaluation(db, principal, run_id=run_id)
        _, cases = evaluation_run_detail(db, run.id, principal.workspace_id)
        record_audit(db, principal, action="EVALUATION_EXECUTE", resource_type="EVALUATION_RUN", resource_id=run.id, status=run.status)
        db.commit()
        return {"run": evaluation_run_view(run, cases), "cases": cases}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/compare", response_model=EvaluationComparisonResponse)
def compare_runs(
    data: EvaluationComparisonRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("evaluation.read")),
):
    try:
        return compare_evaluation_runs(db, data.run_ids, principal.workspace_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/dashboard", response_model=EvaluationDashboardResponse)
def get_evaluation_dashboard(
    run_id: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("evaluation.read")),
):
    try:
        return evaluation_dashboard(db, principal.workspace_id, run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/gate", response_model=ReleaseGateResponse)
def get_release_gate(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("evaluation.read")),
):
    try:
        return release_gate(db, run_id, principal.workspace_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/feedback/dashboard", response_model=FeedbackDashboardResponse)
def get_feedback_dashboard(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("evaluation.read")),
):
    return feedback_dashboard(db, workspace_id=principal.workspace_id)


@router.post("/feedback/correct", status_code=status.HTTP_201_CREATED)
def correct_feedback(
    data: FeedbackCorrectCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("answer.manage")),
):
    try:
        item = record_correct_feedback(db, query_run_id=data.query_run_id, comment=data.comment, workspace_id=principal.workspace_id)
        return {"id": item.id, "query_run_id": item.query_run_id, "feedback_type": item.feedback_type, "recorded": True}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/feedback/incorrect", response_model=FeedbackWorkflowRead, status_code=status.HTTP_201_CREATED)
def incorrect_feedback(
    data: FeedbackCorrectionCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("answer.manage")),
):
    try:
        return submit_correction(db, data=data, principal=principal)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/feedback/recall")
def recall_verified_sql(
    data: FeedbackRecallRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("evaluation.read")),
):
    return {"candidates": recall_candidates(db, data=data, workspace_id=principal.workspace_id)}


@router.post("/feedback/{answer_id}/review", response_model=FeedbackWorkflowRead)
def review_feedback(
    answer_id: str,
    data: FeedbackReviewRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("evaluation.run")),
):
    try:
        return review_correction(db, answer_id=answer_id, data=data, reviewer=principal.email, workspace_id=principal.workspace_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/feedback/{answer_id}/replay", response_model=FeedbackReplayResponse)
def replay_feedback(
    answer_id: str,
    data: FeedbackReplayRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("evaluation.run")),
):
    try:
        return replay_verified_sql(db, answer_id=answer_id, data=data, principal=principal)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
