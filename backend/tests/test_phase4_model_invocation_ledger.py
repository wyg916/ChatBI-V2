from __future__ import annotations

from threading import Event

import httpx
import pytest

from app.core.config import Settings
from app.model_gateway.configuration import ResolvedProvider
from app.model_gateway.contracts import ModelCapability, ModelRequest, RequestContext
from app.model_gateway.ledger import bind_model_invocation_session
from app.model_gateway.service import ModelGateway, ModelUnavailable
from app.models import AppUser, ModelInvocation, Workspace


def _provider() -> ResolvedProvider:
    return ResolvedProvider(
        provider_id="mimo",
        display_name="MiMo",
        base_url="https://model.invalid/v1",
        api_key="test-only",
        model_name="mimo-v2.5",
        auth_header="Authorization",
        auth_prefix="Bearer ",
        max_tokens_field="max_tokens",
        request_options={},
    )


def test_one_model_gateway_persists_only_sanitized_invocation_metadata(db_session):
    workspace = Workspace(name="Ledger Workspace")
    db_session.add(workspace)
    db_session.flush()
    user = AppUser(
        workspace_id=workspace.id,
        email="ledger@example.invalid",
        display_name="Ledger User",
        role="ADMIN",
        status="ACTIVE",
    )
    db_session.add(user)
    db_session.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        assert "never-persist-this-prompt" in request.content.decode()
        return httpx.Response(
            200,
            json={
                "model": "mimo-v2.5",
                "choices": [{"message": {"content": "safe answer", "reasoning_content": "private"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 12,
                    "prompt_tokens_details": {"cached_tokens": 4},
                    "completion_tokens": 5,
                    "total_tokens": 17,
                },
            },
        )

    gateway = ModelGateway(
        Settings(_env_file=None),
        transport=httpx.MockTransport(handler),
        provider_overrides={"mimo": _provider()},
        sleeper=lambda _: None,
    )
    context = RequestContext(
        request_id="REQ-ledger-1",
        trace_id="TRACE-ledger-1",
        conversation_id="conversation-1",
        route="DATA_QUERY",
        workspace_id=workspace.id,
        user_id=user.id,
    )
    request = ModelRequest(
        capability=ModelCapability.NL2SQL,
        requested_alias="mimo",
        messages=({"role": "user", "content": "never-persist-this-prompt"},),
    )
    with bind_model_invocation_session(db_session):
        response = gateway.execute(request, context)
    db_session.commit()

    row = db_session.query(ModelInvocation).one()
    assert row.workspace_id == workspace.id
    assert row.user_id == user.id
    assert row.trace_id == "TRACE-ledger-1"
    assert row.route == "DATA_QUERY"
    assert row.provider == "mimo"
    assert row.model == "mimo-v2.5"
    assert row.status == "SUCCEEDED"
    assert (row.input_tokens, row.cached_input_tokens, row.output_tokens) == (12, 4, 5)
    assert row.cache_hit is True
    assert row.circuit_state == "CLOSED"
    assert row.pricing_version == response.pricing_version
    assert not hasattr(row, "prompt")
    assert not hasattr(row, "content")
    assert not hasattr(row, "reasoning_content")


def test_model_gateway_records_each_provider_attempt_including_retry(db_session):
    workspace = Workspace(name="Retry Ledger Workspace")
    db_session.add(workspace)
    db_session.flush()
    user = AppUser(
        workspace_id=workspace.id,
        email="retry-ledger@example.invalid",
        display_name="Retry Ledger User",
        role="ADMIN",
        status="ACTIVE",
    )
    db_session.add(user)
    db_session.flush()
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(200, json={
            "model": "mimo-v2.5",
            "choices": [{"message": {"content": "safe answer"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        })

    gateway = ModelGateway(
        Settings(_env_file=None),
        transport=httpx.MockTransport(handler),
        provider_overrides={"mimo": _provider()},
        sleeper=lambda _: None,
    )
    context = RequestContext(
        request_id="REQ-ledger-retry",
        trace_id="TRACE-ledger-retry",
        conversation_id="conversation-retry",
        route="GENERAL_CHAT",
        workspace_id=workspace.id,
        user_id=user.id,
    )
    request = ModelRequest(
        capability=ModelCapability.GENERAL,
        requested_alias="mimo",
        messages=({"role": "user", "content": "retry without persisting me"},),
    )
    with bind_model_invocation_session(db_session):
        gateway.execute(request, context)
    db_session.commit()

    rows = db_session.query(ModelInvocation).order_by(ModelInvocation.retry_count, ModelInvocation.status).all()
    assert attempts == 2
    assert [row.status for row in rows] == ["FAILED", "SUCCEEDED"]
    assert rows[0].error_code == "HTTP_503"
    assert {row.request_id for row in rows} == {"REQ-ledger-retry"}
    assert all(row.conversation_id == "conversation-retry" for row in rows)


def test_stream_cancellation_is_recorded_without_prompt_or_partial_content(db_session):
    workspace = Workspace(name="Cancelled Ledger Workspace")
    db_session.add(workspace)
    db_session.flush()
    user = AppUser(
        workspace_id=workspace.id,
        email="cancel-ledger@example.invalid",
        display_name="Cancel Ledger User",
        role="ADMIN",
        status="ACTIVE",
    )
    db_session.add(user)
    db_session.flush()
    cancellation = Event()

    class CancellingStream(httpx.SyncByteStream):
        def __iter__(self):
            cancellation.set()
            yield b'data: {"choices":[{"delta":{"content":"must-not-persist"}}]}\n\n'

    gateway = ModelGateway(
        Settings(_env_file=None),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, stream=CancellingStream())
        ),
        provider_overrides={"mimo": _provider()},
        sleeper=lambda _: None,
    )
    context = RequestContext(
        request_id="REQ-ledger-cancel",
        trace_id="TRACE-ledger-cancel",
        conversation_id="conversation-cancel",
        route="GENERAL_CHAT",
        workspace_id=workspace.id,
        user_id=user.id,
    )
    with bind_model_invocation_session(db_session):
        with pytest.raises(ModelUnavailable, match="cancelled"):
            list(gateway.stream(
                system="safe system",
                user="never-persist-cancelled-prompt",
                requested_alias="mimo",
                context=context,
                cancellation_event=cancellation,
            ))
    db_session.commit()

    row = db_session.query(ModelInvocation).one()
    assert row.status == "CANCELLED"
    assert row.error_code == "REQUEST_CANCELLED"
    assert row.request_id == "REQ-ledger-cancel"
    assert not hasattr(row, "prompt")
    assert not hasattr(row, "content")
