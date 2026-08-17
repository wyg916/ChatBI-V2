from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.rag_runtime.service import IdentityDenied, RuntimeIdentity, retrieve


class BridgeContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=64)
    roles: list[str] = Field(min_length=1)
    allowed_datasources: list[str]
    allowed_semantic_models: list[str]
    allowed_tools: list[str]
    trace_id: str = Field(min_length=8, max_length=96)
    timeout_ms: int = Field(ge=100, le=30_000)
    max_steps: int = Field(ge=1, le=8)
    token_budget: int = Field(ge=1, le=32_768)


class BridgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4_000)
    scenario_id: str = Field(min_length=1, max_length=64)
    limit: int = Field(ge=1, le=10)
    trace_id: str = Field(min_length=8, max_length=96)
    chatbi_context: BridgeContext


app = FastAPI(title="ChatBI V1 RAG Runtime", version="1.0.1")


@app.get("/health")
def health() -> dict[str, Any]:
    secret_configured = bool(get_settings().rag_shared_secret.get_secret_value())
    return {
        "status": "ok" if secret_configured else "degraded",
        "component": "chatbi-rag-runtime",
        "version": "1.0.1",
        "identity_signing": secret_configured,
    }


@app.post("/api/v1/retrieve")
async def retrieve_knowledge(request: Request, response: Response) -> dict[str, Any]:
    raw = await request.body()
    _verify_signature(request, raw)
    try:
        payload = BridgeRequest.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="INVALID_RAG_REQUEST") from exc
    context = payload.chatbi_context
    if payload.trace_id != context.trace_id:
        raise HTTPException(status_code=403, detail="TRACE_IDENTITY_MISMATCH")
    expected_headers = {
        "x-chatbi-workspace-id": context.workspace_id,
        "x-chatbi-user-id": context.user_id,
        "x-chatbi-trace-id": context.trace_id,
        "x-chatbi-roles": ",".join(sorted(context.roles)),
    }
    for header, expected in expected_headers.items():
        if request.headers.get(header) != expected:
            raise HTTPException(status_code=403, detail="BRIDGE_IDENTITY_MISMATCH")
    if "RETRIEVE_KNOWLEDGE" not in context.allowed_tools:
        raise HTTPException(status_code=403, detail="RETRIEVAL_TOOL_DENIED")

    identity = RuntimeIdentity(
        workspace_id=context.workspace_id,
        user_id=context.user_id,
        roles=frozenset(context.roles),
    )
    try:
        with SessionLocal() as db:
            citations = retrieve(
                db,
                query=payload.query,
                identity=identity,
                limit=payload.limit,
            )
    except IdentityDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    response.headers["X-ChatBI-Workspace-Id"] = context.workspace_id
    response.headers["X-ChatBI-Trace-Id"] = context.trace_id
    run_id = str(uuid4())
    if not citations:
        return {
            "trace_id": context.trace_id,
            "run_id": run_id,
            "retrieval_mode": "workspace_acl_token_rank_v1",
            "answer_guard_status": "REFUSED",
            "refusal_reason": "NO_AUTHORIZED_EVIDENCE",
            "citations": [],
        }
    return {
        "trace_id": context.trace_id,
        "run_id": run_id,
        "retrieval_mode": "workspace_acl_token_rank_v1",
        "answer_guard_status": "PASSED",
        "vector_status": "NOT_REQUIRED_DETERMINISTIC_V1",
        "citations": [
            {
                "citation_id": f"citation-{index}",
                "document_id": item.document_id,
                "document_version_id": item.document_version_id,
                "chunk_id": item.chunk_id,
                "title": item.title,
                "citation_text": item.text,
                "source": item.source,
                "locator": item.locator,
                "retrieval_score": item.score,
            }
            for index, item in enumerate(citations, 1)
        ],
    }


def _verify_signature(request: Request, raw: bytes) -> None:
    secret = get_settings().rag_shared_secret.get_secret_value()
    if not secret:
        raise HTTPException(status_code=503, detail="RAG_SIGNING_SECRET_UNAVAILABLE")
    timestamp = request.headers.get("X-ChatBI-Timestamp", "")
    signature = request.headers.get("X-ChatBI-Signature", "")
    try:
        timestamp_int = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="INVALID_BRIDGE_SIGNATURE") from exc
    if abs(int(time.time()) - timestamp_int) > 60:
        raise HTTPException(status_code=401, detail="EXPIRED_BRIDGE_SIGNATURE")
    expected = hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("ascii") + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="INVALID_BRIDGE_SIGNATURE")
