from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.evaluation import EvaluationOverviewResponse
from app.services.evaluation import evaluation_overview

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.get("/overview", response_model=EvaluationOverviewResponse)
def get_evaluation_overview(db: Session = Depends(get_db)):
    try:
        return evaluation_overview(db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
