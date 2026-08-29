from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access import Principal, record_audit, require_permission
from app.core.data_safety import (
    SENSITIVE_COMMENT_MARKER,
    is_sensitive_column,
    redact_public_sql_payload,
)
from app.db.session import get_db
from app.models import (
    DataSource,
    DataSourceColumn,
    DataSourceSchema,
    DataSourceTable,
    EvaluationCaseResult,
    QueryRun,
)
from app.schemas.evaluation import (
    EvaluationCaseDetail,
    EvaluationCaseResultRead,
    EvaluationComparisonRequest,
    EvaluationComparisonResponse,
    EvaluationCreate,
    EvaluationDashboardResponse,
    EvaluationOverviewResponse,
    EvaluationRunDetail,
    EvaluationRunRead,
    FeedbackCorrectCreate,
    FeedbackCorrectionCreate,
    FeedbackDecisionRequest,
    FeedbackDashboardResponse,
    FeedbackRecallRequest,
    FeedbackReplayRequest,
    FeedbackReplayResponse,
    FeedbackReviewStartRequest,
    FeedbackReviewRequest,
    FeedbackWorkflowRead,
    UserFeedbackCreate,
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
    decide_feedback_review,
    recall_candidates,
    record_correct_feedback,
    record_user_feedback,
    replay_verified_sql,
    review_correction,
    start_feedback_review,
    submit_correction,
)

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


def _workspace_sensitive_columns(db: Session, workspace_id: str | None) -> list[str]:
    if not workspace_id:
        return []
    rows = db.execute(
        select(DataSourceColumn.name, DataSourceColumn.comment)
        .join(DataSourceTable, DataSourceColumn.table_id == DataSourceTable.id)
        .join(DataSourceSchema, DataSourceTable.schema_id == DataSourceSchema.id)
        .join(DataSource, DataSourceSchema.datasource_id == DataSource.id)
        .where(DataSource.workspace_id == workspace_id)
    )
    return sorted({
        name
        for name, comment in rows
        if is_sensitive_column(name) or SENSITIVE_COMMENT_MARKER in (comment or "")
    })


def _public_evaluation_payload(
    db: Session,
    workspace_id: str | None,
    payload,
    *,
    query_run_id: str | None = None,
):
    sensitive_columns = _workspace_sensitive_columns(db, workspace_id)
    dialect = "postgresql"
    if query_run_id:
        query_run = db.get(QueryRun, query_run_id)
        if query_run is not None:
            context = query_run.context_payload or {}
            dialect = str(
                context.get("dialect")
                or (query_run.execution_payload or {}).get("dialect")
                or "postgresql"
            )
            policy = context.get("security_policy") or {}
            if isinstance(policy, dict):
                sensitive_columns = sorted({
                    *sensitive_columns,
                    *list(policy.get("sensitive_columns") or []),
                })
    return redact_public_sql_payload(
        payload, sensitive_columns, dialect=dialect,
    )


def _public_case(
    db: Session,
    workspace_id: str | None,
    case: EvaluationCaseResult,
) -> dict:
    payload = EvaluationCaseResultRead.model_validate(case).model_dump(mode="python")
    return _public_evaluation_payload(
        db, workspace_id, payload, query_run_id=case.query_run_id,
    )


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
        return {
            "run": evaluation_run_view(run, cases),
            "cases": [_public_case(db, principal.workspace_id, case) for case in cases],
        }
    except (LookupError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=EvaluationRunDetail)
def get_evaluation_run(run_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("evaluation.read"))):
    try:
        run, cases = evaluation_run_detail(db, run_id, principal.workspace_id)
        return {
            "run": evaluation_run_view(run, cases),
            "cases": [_public_case(db, principal.workspace_id, case) for case in cases],
        }
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/cases/{case_ref}", response_model=EvaluationCaseDetail)
def get_evaluation_case(case_ref: str, db: Session = Depends(get_db), principal: Principal = Depends(require_permission("evaluation.read"))):
    try:
        run, case, previous_id, next_id = evaluation_case_detail(db, case_ref, principal.workspace_id)
        _, cases = evaluation_run_detail(db, run.id, principal.workspace_id)
        return {
            "run": evaluation_run_view(run, cases),
            "case": _public_case(db, principal.workspace_id, case),
            "previous_case_id": previous_id,
            "next_case_id": next_id,
        }
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
        return {
            "run": evaluation_run_view(run, cases),
            "cases": [_public_case(db, principal.workspace_id, case) for case in cases],
        }
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
    return _public_evaluation_payload(
        db, principal.workspace_id,
        feedback_dashboard(db, principal=principal),
    )


@router.post("/feedback", response_model=FeedbackWorkflowRead, status_code=status.HTTP_201_CREATED)
def create_user_feedback(
    data: UserFeedbackCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("answer.manage")),
):
    try:
        item = record_user_feedback(db, data=data, principal=principal)
        record_audit(
            db, principal, action="FEEDBACK_OPEN", resource_type="VERIFIED_ANSWER",
            resource_id=item["answer_id"], details={"workflow_state": item["workflow_state"], "sentiment": data.sentiment, "reason": data.reason},
        )
        db.commit()
        return _public_evaluation_payload(db, principal.workspace_id, item)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/feedback/{answer_id}/review/start", response_model=FeedbackWorkflowRead)
def start_user_feedback_review(
    answer_id: str,
    data: FeedbackReviewStartRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("evaluation.run")),
):
    try:
        item = start_feedback_review(db, answer_id=answer_id, data=data, principal=principal)
        record_audit(
            db, principal, action="FEEDBACK_REVIEW_START", resource_type="VERIFIED_ANSWER",
            resource_id=answer_id, details={"workflow_state": item["workflow_state"]},
        )
        db.commit()
        return _public_evaluation_payload(db, principal.workspace_id, item)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/feedback/{answer_id}/decision", response_model=FeedbackWorkflowRead)
def decide_user_feedback_review(
    answer_id: str,
    data: FeedbackDecisionRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("evaluation.run")),
):
    try:
        item = decide_feedback_review(db, answer_id=answer_id, data=data, principal=principal)
        record_audit(
            db, principal, action="FEEDBACK_DECISION", resource_type="VERIFIED_ANSWER",
            resource_id=answer_id, status=item["workflow_state"],
            details={"decision": data.decision, "workflow_state": item["workflow_state"], "version": item["version"]},
        )
        db.commit()
        return _public_evaluation_payload(db, principal.workspace_id, item)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/feedback/correct", status_code=status.HTTP_201_CREATED)
def correct_feedback(
    data: FeedbackCorrectCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("answer.manage")),
):
    try:
        item = record_correct_feedback(
            db,
            query_run_id=data.query_run_id,
            comment=data.comment,
            principal=principal,
        )
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
        return _public_evaluation_payload(
            db, principal.workspace_id,
            submit_correction(db, data=data, principal=principal),
        )
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
    return _public_evaluation_payload(db, principal.workspace_id, {
        "candidates": recall_candidates(db, data=data, principal=principal),
    })


@router.post("/feedback/{answer_id}/review", response_model=FeedbackWorkflowRead)
def review_feedback(
    answer_id: str,
    data: FeedbackReviewRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("evaluation.run")),
):
    try:
        return _public_evaluation_payload(
            db, principal.workspace_id,
            review_correction(
                db, answer_id=answer_id, data=data, principal=principal,
            ),
        )
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
        item = replay_verified_sql(db, answer_id=answer_id, data=data, principal=principal)
        record_audit(
            db, principal, action="FEEDBACK_REGRESSION_REPLAY", resource_type="VERIFIED_ANSWER",
            resource_id=answer_id, status="PASS" if item["replay_passed"] else "FAIL",
            details={"query_run_id": item["query_run_id"], "oracle_status": item["oracle_status"]},
        )
        db.commit()
        return _public_evaluation_payload(db, principal.workspace_id, item)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
