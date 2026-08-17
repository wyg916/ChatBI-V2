from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

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
from app.query.service import QueryPipeline, query_response, save_feedback, save_verified_answer
from app.schemas.content import AnswerRead

router = APIRouter(tags=["query pipeline"])


def _run_or_404(db: Session, query_id: str) -> QueryRun:
    run = db.get(QueryRun, query_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Query run not found")
    return run


@router.get("/query-capabilities")
def query_capabilities():
    return {
        "nl2sql": Nl2SqlRouter().capabilities(),
        "sql_guard": {"engine": "sqlglot", "ast_validation": True},
        "result_oracle": {"version": "v1", "sql_string_equality": False},
    }


@router.post("/ask", response_model=QueryResponse, status_code=status.HTTP_201_CREATED)
def ask(data: AskRequest, db: Session = Depends(get_db)):
    return query_response(QueryPipeline().execute(db, data))


@router.get("/queries/{query_id}", response_model=QueryResponse)
def get_query(query_id: str, db: Session = Depends(get_db)):
    return query_response(_run_or_404(db, query_id))


@router.post("/queries/{query_id}/verify", response_model=QueryResponse)
def verify_query(query_id: str, data: VerifyResultRequest, db: Session = Depends(get_db)):
    try:
        run = QueryPipeline().verify(db, _run_or_404(db, query_id), data.expected)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return query_response(run)


@router.post("/queries/{query_id}/feedback", status_code=status.HTTP_201_CREATED)
def feedback(query_id: str, data: FeedbackRequest, db: Session = Depends(get_db)):
    item = save_feedback(db, _run_or_404(db, query_id), data)
    return {"id": item.id, "query_id": item.query_run_id, "feedback_type": item.feedback_type, "recorded": True}


@router.post("/queries/{query_id}/save", response_model=AnswerRead, status_code=status.HTTP_201_CREATED)
def save_answer(query_id: str, data: SaveAnswerRequest, db: Session = Depends(get_db)):
    try:
        return save_verified_answer(db, _run_or_404(db, query_id), data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
