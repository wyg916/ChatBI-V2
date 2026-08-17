from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.evaluation import EvaluationCaseDetail, EvaluationOverviewResponse, EvaluationRunDetail
from app.services.evaluation import evaluation_case_detail, evaluation_overview, evaluation_run_detail, run_golden_evaluation

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.get("/overview", response_model=EvaluationOverviewResponse)
def get_evaluation_overview(db: Session = Depends(get_db)):
    try:
        return evaluation_overview(db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs", response_model=EvaluationRunDetail, status_code=status.HTTP_201_CREATED)
def run_evaluation(db: Session = Depends(get_db)):
    try:
        run = run_golden_evaluation(db)
        _, cases = evaluation_run_detail(db, run.id)
        return {"run": run, "cases": cases}
    except (LookupError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=EvaluationRunDetail)
def get_evaluation_run(run_id: str, db: Session = Depends(get_db)):
    try:
        run, cases = evaluation_run_detail(db, run_id)
        return {"run": run, "cases": cases}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/cases/{case_ref}", response_model=EvaluationCaseDetail)
def get_evaluation_case(case_ref: str, db: Session = Depends(get_db)):
    try:
        run, case, previous_id, next_id = evaluation_case_detail(db, case_ref)
        return {"run": run, "case": case, "previous_case_id": previous_id, "next_case_id": next_id}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
