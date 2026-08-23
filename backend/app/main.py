import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.seed import seed_demo_semantic_model
from app.services.runtime_seed import seed_v1_runtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("ChatBI API starting")
    if get_settings().seed_demo_semantic_model:
        try:
            with SessionLocal() as db:
                model = seed_demo_semantic_model(db)
                seed_v1_runtime(db, model.workspace_id)
        except Exception:
            logger.exception("Demo semantic seed skipped because metadata database is not ready")
    yield
    logger.info("ChatBI API stopped")


settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origin_allowlist),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def attach_request_trace(request: Request, call_next):
    """Give every API response a request trace without trusting client identifiers."""
    trace_id = f"REQUEST-{uuid4()}"
    response = await call_next(request)
    if "X-Trace-ID" not in response.headers:
        response.headers["X-Trace-ID"] = trace_id
    return response


app.include_router(api_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "chatbi-backend", "version": settings.app_version}


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception):
    logger.exception("Unhandled request error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
