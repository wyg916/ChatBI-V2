from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.access import Principal, record_audit, require_permission
from app.db.session import get_db
from app.schemas.evaluation import EvaluationCaseDetail, EvaluationOverviewResponse, EvaluationRunDetail
from app.services.evaluation import evaluation_case_detail, evaluation_overview, evaluation_run_detail, run_golden_evaluation

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.get("/overview", response_model=EvaluationOverviewResponse, dependencies=[Depends(require_permission("evaluation.read"))])
def get_evaluation_overview(db: Session = Depends(get_db)):
    try:
        return evaluation_overview(db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs", response_model=EvaluationRunDetail, status_code=status.HTTP_201_CREATED)
def run_evaluation(db: Session = Depends(get_db), principal: Principal = Depends(require_permission("evaluation.run"))):
    try:
        run = run_golden_evaluation(db)
        record_audit(
            db, principal, action="EVALUATION_RUN", resource_type="EVALUATION_RUN",
            resource_id=run.id, status=run.status, details={"golden_set_count": run.golden_set_count},
        )
        db.commit()
        _, cases = evaluation_run_detail(db, run.id)
        return {"run": run, "cases": cases}
    except (LookupError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=EvaluationRunDetail, dependencies=[Depends(require_permission("evaluation.read"))])
def get_evaluation_run(run_id: str, db: Session = Depends(get_db)):
    try:
        run, cases = evaluation_run_detail(db, run_id)
        return {"run": run, "cases": cases}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/cases/{case_ref}", response_model=EvaluationCaseDetail, dependencies=[Depends(require_permission("evaluation.read"))])
def get_evaluation_case(case_ref: str, db: Session = Depends(get_db)):
    try:
        run, case, previous_id, next_id = evaluation_case_detail(db, case_ref)
        return {"run": run, "case": case, "previous_case_id": previous_id, "next_case_id": next_id}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
