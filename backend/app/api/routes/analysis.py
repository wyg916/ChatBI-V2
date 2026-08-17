from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.access import Principal, require_permission
from app.db.session import get_db
from app.integration.contracts import AnalysisRequest, AnalysisResponse
from app.integration.service import AnalysisService


router = APIRouter(tags=["controlled analysis"])


@router.post("/analysis", response_model=AnalysisResponse, status_code=status.HTTP_201_CREATED)
def analyze(
    data: AnalysisRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("query.ask")),
) -> AnalysisResponse:
    return AnalysisService().execute(db, data, principal)
