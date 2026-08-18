from queue import Empty, Queue
from threading import Thread
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.access import Principal, require_permission
from app.db.session import get_db
from app.db.session import SessionLocal
from app.integration.contracts import AnalysisRequest, AnalysisResponse
from app.integration.service import AnalysisService
from app.streaming import StreamEventFactory, event_for_stage, format_sse


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
    factory = StreamEventFactory(trace_id=f"STREAM-{uuid4()}")

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
        yield format_sse("accepted", factory.create("accepted", data={"route_hint": data.route.value if data.route else "auto"}))
        while True:
            try:
                item = events.get(timeout=2.5)
            except Empty:
                yield format_sse("heartbeat", factory.create("heartbeat"))
                continue
            if item is None:
                break
            event, payload = item
            if event == "progress":
                stage = str(payload.get("stage", ""))
                if stage.upper() == "COMPLETED":
                    envelope = factory.create("completed", capability="analysis", data=payload)
                    yield format_sse("progress", {**envelope, "stage": stage})
                    continue
                protocol_event = event_for_stage(stage)
                if protocol_event:
                    capability = str(payload.get("tool") or payload.get("role") or "analysis")
                    envelope = factory.create(protocol_event, capability=capability, data=payload)
                    yield format_sse(protocol_event, envelope)
                    yield format_sse("progress", {**envelope, "stage": stage})
                continue
            if event == "result":
                yield format_sse("answer_delta", factory.create("answer_delta", capability="analysis"))
                yield format_sse("completed", factory.create(
                    "completed",
                    capability="analysis",
                    data={"stage": "COMPLETED", "status": payload.get("status")},
                ))
                yield format_sse("result", payload)
                continue
            if event == "error":
                yield format_sse("error", factory.create("error", capability="analysis", data=payload))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
