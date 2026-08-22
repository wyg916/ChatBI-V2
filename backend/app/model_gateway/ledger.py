from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from sqlalchemy.orm import Session

from app.model_gateway.contracts import ModelRequest, ModelResponse, RequestContext


_ledger_session: ContextVar[Session | None] = ContextVar("model_invocation_session", default=None)


@contextmanager
def bind_model_invocation_session(db: Session) -> Iterator[None]:
    """Bind the request transaction without making ModelGateway own DB lifecycle."""

    token = _ledger_session.set(db)
    try:
        yield
    finally:
        _ledger_session.reset(token)


def record_model_invocation(
    context: RequestContext,
    request: ModelRequest,
    *,
    response: ModelResponse | None,
    provider: str,
    model: str = "unknown",
    status: str,
    latency_ms: int,
    fallback_count: int = 0,
    retry_count: int = 0,
    error_code: str | None = None,
    circuit_state: str = "UNKNOWN",
) -> None:
    """Append only allowlisted operational metadata; never persist model content."""

    db = _ledger_session.get()
    if db is None or context.workspace_id == "SYSTEM" or context.user_id == "SYSTEM":
        return

    from app.models.governance import ModelInvocation

    usage = response.usage if response is not None else None
    db.add(ModelInvocation(
        workspace_id=context.workspace_id,
        user_id=context.user_id,
        trace_id=context.trace_id,
        request_id=context.request_id,
        conversation_id=context.conversation_id,
        route=context.route or "UNSPECIFIED",
        capability=request.capability.value,
        provider=provider,
        model=model,
        status=status,
        input_tokens=usage.input_tokens if usage else 0,
        cached_input_tokens=usage.cached_input_tokens if usage else 0,
        output_tokens=usage.output_tokens if usage else 0,
        cost_cny=response.cost_cny if response is not None else 0.0,
        latency_ms=max(0, latency_ms),
        cache_hit=bool(usage and usage.cached_input_tokens > 0),
        fallback_count=max(0, response.fallback_count if response is not None else fallback_count),
        retry_count=max(0, response.retry_count if response is not None else retry_count),
        premium_escalation=provider == "kimi" and bool(request.premium_triggers or request.complexity_score >= 80),
        error_code=error_code,
        circuit_state=circuit_state,
        pricing_version=response.pricing_version if response is not None else None,
    ))
