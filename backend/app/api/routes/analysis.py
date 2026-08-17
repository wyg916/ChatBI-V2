import json
from queue import Queue
from threading import Thread

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.access import Principal, require_permission
from app.db.session import get_db
from app.db.session import SessionLocal
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


@router.post("/analysis/stream")
def analyze_stream(
    data: AnalysisRequest,
    principal: Principal = Depends(require_permission("query.ask")),
) -> StreamingResponse:
    """Stream finite stage events only; no model reasoning or chain-of-thought."""
    events: Queue[tuple[str, dict] | None] = Queue()

    def progress(stage, detail):
        allowed = {key: detail[key] for key in ("elapsed_ms", "role", "tool", "status") if key in detail}
        events.put(("progress", {"stage": stage.value, **allowed}))

    def worker() -> None:
        try:
            with SessionLocal() as db:
                result = AnalysisService().execute(
                    db, data, principal, progress_callback=progress
                )
            events.put(("result", result.model_dump(mode="json")))
        except Exception as exc:
            events.put(("error", {"code": f"ANALYSIS_STREAM_{type(exc).__name__.upper()}"}))
        finally:
            events.put(None)

    Thread(target=worker, name="chatbi-analysis-stream", daemon=True).start()

    def event_stream():
        while True:
            item = events.get()
            if item is None:
                break
            event, payload = item
            yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
