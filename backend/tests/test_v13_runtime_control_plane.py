from __future__ import annotations

import gzip
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread, Timer
from time import monotonic, sleep

import httpx
import pytest

import app.model_gateway.service as model_gateway_service
from app.core.config import Settings
from app.integration.question_router import QuestionRouter
from app.model_gateway.control import bind_model_request_control
from app.model_gateway import (
    BudgetMode,
    ModelCapability,
    ModelGateway,
    ModelRequest,
    ModelUnavailable,
    RequestContext,
)
from app.model_gateway.test_cost_control import TestCostControlError as CostControlError
from app.streaming import StreamEventFactory


class _ForbiddenGateway:
    def classify(self, *_args, **_kwargs):
        raise AssertionError("L0 route must not call a model")


class _Level0BlockedGateway:
    def classify(self, *_args, **_kwargs):
        raise CostControlError("LEVEL0_PAID_PROVIDER_CALL_BLOCKED")


class _SlowNoNewlineStream(httpx.SyncByteStream):
    def __init__(self) -> None:
        self.started = Event()
        self.exited = Event()
        self.read_count = 0

    def __iter__(self):
        self.started.set()
        try:
            for _ in range(500):
                sleep(0.005)
                self.read_count += 1
                yield b"x"
        finally:
            self.exited.set()


_SSE_DELTA = b'data: {"choices":[{"delta":{"content":"x"}}]}\n'


class _BurstSseStream(httpx.SyncByteStream):
    def __init__(self) -> None:
        self.queue_saturated = Event()
        self.exited = Event()
        self.read_count = 0

    def __iter__(self):
        try:
            for _ in range(10_000):
                self.read_count += 1
                if self.read_count == 4:
                    self.queue_saturated.set()
                yield _SSE_DELTA
        finally:
            self.exited.set()


class _TrackedChunksStream(httpx.SyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self.chunks = chunks
        self.exited = Event()
        self.read_count = 0

    def __iter__(self):
        try:
            for chunk in self.chunks:
                self.read_count += 1
                yield chunk
        finally:
            self.exited.set()


class _TwoPhaseSseStream(httpx.SyncByteStream):
    def __init__(self) -> None:
        self.release_second = Event()
        self.waiting_for_release = Event()
        self.exited = Event()
        self.read_count = 0

    def __iter__(self):
        try:
            self.read_count += 1
            yield _SSE_DELTA
            self.waiting_for_release.set()
            if self.release_second.wait(1):
                self.read_count += 1
                yield _SSE_DELTA
        finally:
            self.exited.set()


def _context(**updates) -> RequestContext:
    values = {
        "request_id": "client-request-001",
        "trace_id": "TRACE-runtime-control-001",
        "conversation_id": "conversation-a",
        "user_id": "user-a",
        "workspace_id": "workspace-a",
        "roles": frozenset({"ANALYST"}),
        "permission_hash": "permission-a",
        "context_hash": "context-a",
    }
    values.update(updates)
    return RequestContext(**values)


def _provider_id(request: httpx.Request) -> str:
    return {
        "api.xiaomimimo.com": "mimo",
        "api.deepseek.com": "deepseek",
        "api.moonshot.cn": "kimi",
    }[str(request.url.host)]


def test_credentialed_cors_uses_explicit_configured_origins():
    settings = Settings(
        _env_file=None,
        cors_allow_origins="http://127.0.0.1:5173,http://127.0.0.1:5177/",
    )
    assert settings.cors_origin_allowlist == (
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5177",
    )


@pytest.mark.parametrize("origins", ["", "*"])
def test_credentialed_cors_rejects_empty_or_wildcard_origins(origins):
    with pytest.raises(ValueError, match="explicit origins"):
        Settings(_env_file=None, cors_allow_origins=origins).cors_origin_allowlist


def test_date_question_is_l0_model_none():
    decision = QuestionRouter(_ForbiddenGateway()).decide("今天是几号？")
    assert decision.route.value == "GENERAL_CHAT"
    assert decision.reason == "DATE_TIME_L0"
    assert decision.model_required is False
    assert decision.requested_alias == "none"


def test_date_chat_persists_model_none_trace(client):
    conversation = client.post("/api/v1/conversations", json={"title": "Date L0"}).json()
    response = client.post("/api/v1/chat", json={
        "conversation_id": conversation["id"],
        "client_message_id": "client-date-zero-model-001",
        "content": "今天是几号？",
    })
    assert response.status_code == 201
    assistant = response.json()["assistant_message"]
    assert assistant["status"] == "SUCCEEDED"
    assert "当前日期是" in assistant["content"]
    trace = assistant["trace_payload"]
    assert trace["model_provider"] == "none"
    assert trace["model_name"] == "none"
    assert trace["router_decision"]["requested_alias"] == "none"
    assert trace["router_decision"]["model_required"] is False


def test_unrelated_revenue_phrase_does_not_fall_into_data_query():
    decision = QuestionRouter(_ForbiddenGateway()).decide("请写一首关于收入这个词的诗")
    assert decision.route.value == "GENERAL_CHAT"
    assert decision.reason == "NON_DATA_CONTEXT_L0"
    assert decision.needs_sql is False


@pytest.mark.parametrize(
    ("question", "route"),
    [
        ("有哪些模型可用？", "MODEL_STATUS"),
        ("当前系统版本和能力是什么？", "SYSTEM_CAPABILITY"),
        ("我当前有哪些权限？", "ADMIN_QUERY"),
    ],
)
def test_explicit_new_intents_do_not_inherit_prior_data_context(question, route):
    decision = QuestionRouter(_ForbiddenGateway()).decide(
        question, history_summary="指标=销售额；时间=今年；维度=地区",
    )
    assert decision.route.value == route
    assert decision.needs_sql is False
    assert decision.reason.startswith("EXPLICIT_NEW_INTENT")


def test_short_data_follow_up_is_the_only_route_that_inherits_data_context():
    decision = QuestionRouter(_ForbiddenGateway()).decide(
        "那华南呢？", history_summary="指标=销售额；时间=今年；维度=地区",
    )
    assert decision.route.value == "DATA_FOLLOW_UP"
    assert decision.needs_sql is True


def test_unknown_intent_fails_safe_when_level0_blocks_model_router():
    decision = QuestionRouter(_Level0BlockedGateway()).decide("请处理这个不明确请求")
    assert decision.route.value == "GENERAL_CHAT"
    assert decision.reason == "INTENT_MODEL_UNAVAILABLE_SAFE_GENERAL"
    assert decision.model_required is False


def test_request_cache_key_isolated_by_conversation_permission_and_context():
    baseline = _context().cache_key("chat-response")
    assert baseline != _context(conversation_id="conversation-b").cache_key("chat-response")
    assert baseline != _context(permission_hash="permission-b").cache_key("chat-response")
    assert baseline != _context(context_hash="context-b").cache_key("chat-response")


def test_balanced_general_route_selects_mimo_and_records_exact_cost():
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "model": "mimo-v2.5",
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": "受控回答", "reasoning_content": "must-not-be-persisted"},
            }],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "total_tokens": 1500,
                "prompt_tokens_details": {"cached_tokens": 200},
            },
        })

    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="unit-test-only",
        kimi_api_key="unit-test-only",
        general_model_provider="auto",
    ), transport=httpx.MockTransport(handler))
    reply = gateway.complete(system="system", user="hello", context=_context())
    assert reply.provider == "mimo"
    assert observed["url"].startswith("https://api.xiaomimimo.com/")
    assert observed["payload"]["thinking"] == {"type": "disabled"}
    trace = reply.trace or {}
    assert trace["cost_cny"] == pytest.approx(0.001804)
    assert trace["usage"]["exact"] is True
    assert trace["reasoning_observed"] is True
    assert "must-not-be-persisted" not in json.dumps(trace)


def test_model_complete_rejects_unexpected_compressed_response_before_decode(monkeypatch):
    body = gzip.compress(b"x" * (17 * 1024 * 1024))
    statuses: list[str] = []
    observed_accept_encoding = ""

    monkeypatch.setattr(
        model_gateway_service,
        "record_model_invocation",
        lambda *_args, **kwargs: statuses.append(str(kwargs.get("status"))),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_accept_encoding
        observed_accept_encoding = request.headers.get("Accept-Encoding", "")
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Encoding": "gzip",
                "Content-Length": str(len(body)),
                "Content-Type": "application/json",
                "Transfer-Encoding": "chunked",
            },
        )

    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="",
        kimi_api_key="",
    ), transport=httpx.MockTransport(handler))

    with pytest.raises(ModelUnavailable, match="All configured model providers failed"):
        gateway.complete(system="system", user="compressed response")

    assert observed_accept_encoding == "identity"
    assert statuses == ["FAILED"]
    assert gateway.last_response is None


def test_model_stream_rejects_unexpected_compressed_response_without_delta_or_success(monkeypatch):
    body = gzip.compress(_SSE_DELTA + b"data: [DONE]\n")
    statuses: list[str] = []
    observed_accept_encoding = ""

    monkeypatch.setattr(
        model_gateway_service,
        "record_model_invocation",
        lambda *_args, **kwargs: statuses.append(str(kwargs.get("status"))),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_accept_encoding
        observed_accept_encoding = request.headers.get("Accept-Encoding", "")
        return httpx.Response(
            200,
            content=body,
            headers={
                "Content-Encoding": "gzip",
                "Content-Length": str(len(body)),
                "Content-Type": "text/event-stream",
            },
        )

    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="",
        kimi_api_key="",
    ), transport=httpx.MockTransport(handler))

    with pytest.raises(ModelUnavailable, match="All configured model provider streams failed"):
        list(gateway.stream(system="system", user="compressed stream"))

    assert observed_accept_encoding == "identity"
    assert statuses == ["FAILED"]
    assert gateway.last_response is None


def test_model_complete_rejects_excessive_decoded_response(monkeypatch):
    statuses: list[str] = []
    monkeypatch.setattr(model_gateway_service, "_NETWORK_RESPONSE_MAX_BYTES", 64)
    monkeypatch.setattr(
        model_gateway_service,
        "record_model_invocation",
        lambda *_args, **kwargs: statuses.append(str(kwargs.get("status"))),
    )
    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="",
        kimi_api_key="",
    ), transport=httpx.MockTransport(
        lambda _request: httpx.Response(200, content=b"x" * 65)
    ))

    with pytest.raises(ModelUnavailable, match="All configured model providers failed"):
        gateway.complete(system="system", user="excessive response")

    assert statuses == ["FAILED"]
    assert gateway.last_response is None


def test_request_scoped_agent_deadline_reaches_model_http_timeout():
    observed = {}

    class DeadlineSignal:
        remaining_seconds = 0.25

        @staticmethod
        def is_set():
            return False

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "model": "mimo-v2.5",
            "choices": [{"message": {"content": "bounded"}}],
        })

    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="",
        kimi_api_key="",
    ), transport=httpx.MockTransport(handler))
    original = gateway._request_timeout

    def capture_timeout(request, cancellation_event):
        observed["signal"] = cancellation_event
        observed["timeout"] = original(request, cancellation_event)
        return observed["timeout"]

    gateway._request_timeout = capture_timeout
    signal = DeadlineSignal()
    with bind_model_request_control(signal):
        reply = gateway.complete(system="system", user="bounded request")

    assert reply.content == "bounded"
    assert observed["signal"] is signal
    assert observed["timeout"] == pytest.approx(0.25)


def test_model_complete_absolute_deadline_reaps_slow_drip_reader():
    class DeadlineSignal:
        def __init__(self) -> None:
            self.deadline = monotonic() + 0.05

        @property
        def remaining_seconds(self) -> float:
            return max(0.0, self.deadline - monotonic())

        def is_set(self) -> bool:
            return self.remaining_seconds == 0.0

    body = _SlowNoNewlineStream()
    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="",
        kimi_api_key="",
    ), transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=body)))
    started = monotonic()

    with pytest.raises(ModelUnavailable, match="cancelled"):
        gateway.complete(
            system="system",
            user="absolute deadline",
            cancellation_event=DeadlineSignal(),
        )

    assert monotonic() - started < 0.25
    assert body.exited.wait(0.05)
    reads_at_terminal = body.read_count
    sleep(0.03)
    assert body.read_count == reads_at_terminal
    assert gateway.last_response is None


def test_model_complete_cancellation_during_normalization_prevents_success_publication(monkeypatch):
    cancellation = Event()
    completed: list[dict] = []
    invocations: list[str] = []
    original_normalize = model_gateway_service.normalize_chat_completion

    def cancel_after_normalization(body):
        result = original_normalize(body)
        cancellation.set()
        return result

    monkeypatch.setattr(
        model_gateway_service,
        "normalize_chat_completion",
        cancel_after_normalization,
    )
    monkeypatch.setattr(
        model_gateway_service,
        "record_model_invocation",
        lambda *_args, **kwargs: invocations.append(str(kwargs.get("status"))),
    )
    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="",
        kimi_api_key="",
    ), transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={
        "model": "mimo-v2.5",
        "choices": [{"message": {"content": "must not publish"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    })))
    monkeypatch.setattr(
        gateway.test_cost_control,
        "complete_attempt",
        lambda _attempt, **kwargs: completed.append(kwargs),
    )

    with pytest.raises(ModelUnavailable, match="cancelled"):
        gateway.complete(
            system="system",
            user="cancel during normalize",
            cancellation_event=cancellation,
        )

    assert len(completed) == 1
    assert completed[0]["status"] == "CANCELLED"
    assert completed[0]["error_code"] == "REQUEST_CANCELLED"
    assert completed[0]["response"].usage.total_tokens == 7
    assert completed[0]["response"].cost_cny > 0
    assert invocations == ["CANCELLED"]
    assert gateway.last_response is None


def test_model_stream_cancellation_during_delta_parse_prevents_yield_and_success(monkeypatch):
    cancellation = Event()
    completed: list[tuple[str, str | None]] = []
    invocations: list[str] = []
    original_loads = model_gateway_service.json.loads

    def cancel_after_delta_parse(value, *args, **kwargs):
        result = original_loads(value, *args, **kwargs)
        if isinstance(value, str) and '"delta"' in value:
            cancellation.set()
        return result

    monkeypatch.setattr(model_gateway_service.json, "loads", cancel_after_delta_parse)
    monkeypatch.setattr(
        model_gateway_service,
        "record_model_invocation",
        lambda *_args, **kwargs: invocations.append(str(kwargs.get("status"))),
    )
    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="",
        kimi_api_key="",
    ), transport=httpx.MockTransport(lambda _request: httpx.Response(
        200,
        content=_SSE_DELTA + b"data: [DONE]\n",
    )))
    monkeypatch.setattr(
        gateway.test_cost_control,
        "complete_attempt",
        lambda _attempt, **kwargs: completed.append((
            str(kwargs.get("status")), kwargs.get("error_code"),
        )),
    )

    with pytest.raises(ModelUnavailable, match="cancelled"):
        list(gateway.stream(
            system="system",
            user="cancel during stream parse",
            cancellation_event=cancellation,
        ))

    assert completed == [("CANCELLED", "REQUEST_CANCELLED")]
    assert invocations == ["CANCELLED"]
    assert gateway.last_response is None


def test_model_stream_consumer_close_terminalizes_reserved_attempt(monkeypatch):
    completed: list[dict] = []
    invocations: list[tuple[str, str | None, int | None]] = []
    body = _TrackedChunksStream(
        b'data: {"model":"mimo-v2.5","usage":{"prompt_tokens":3,'
        b'"completion_tokens":1,"total_tokens":4},'
        b'"choices":[{"delta":{"content":"x"}}]}\n'
        + _SSE_DELTA
        + b"data: [DONE]\n"
    )
    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="",
        kimi_api_key="",
    ), transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=body)))
    monkeypatch.setattr(
        gateway.test_cost_control,
        "complete_attempt",
        lambda _attempt, **kwargs: completed.append(kwargs),
    )
    monkeypatch.setattr(
        model_gateway_service,
        "record_model_invocation",
        lambda *_args, **kwargs: invocations.append((
            str(kwargs.get("status")),
            kwargs.get("error_code"),
            kwargs.get("retry_count"),
        )),
    )
    replies = gateway.stream(system="system", user="close after first delta")

    assert next(replies).content == "x"
    replies.close()

    assert len(completed) == 1
    assert completed[0]["status"] == "CANCELLED"
    assert completed[0]["error_code"] == "STREAM_CONSUMER_CLOSED"
    assert completed[0]["response"].usage.total_tokens == 4
    assert completed[0]["response"].cost_cny > 0
    assert invocations == [("CANCELLED", "STREAM_CONSUMER_CLOSED", 0)]
    assert body.exited.wait(0.2)
    assert gateway.last_response is None


def test_model_stream_midflight_cancel_reaps_no_newline_reader_without_publishing():
    body = _SlowNoNewlineStream()
    cancellation = Event()
    timer = Timer(0.05, cancellation.set)
    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="",
        kimi_api_key="",
    ), transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=body)))
    timer.start()
    started = monotonic()
    try:
        with pytest.raises(ModelUnavailable, match="cancelled"):
            list(gateway.stream(
                system="system",
                user="midflight cancel",
                cancellation_event=cancellation,
            ))
    finally:
        timer.join(timeout=1)

    assert monotonic() - started < 0.25
    assert body.exited.wait(0.05)
    reads_at_terminal = body.read_count
    sleep(0.03)
    assert body.read_count == reads_at_terminal
    assert gateway.last_response is None


def test_model_stream_slow_consumer_backpressures_and_cancels_blocked_reader(monkeypatch):
    body = _BurstSseStream()
    cancellation = Event()
    statuses: list[str] = []
    monkeypatch.setattr(model_gateway_service, "_NETWORK_STREAM_QUEUE_MAX_EVENTS", 2)
    monkeypatch.setattr(
        model_gateway_service,
        "record_model_invocation",
        lambda *_args, **kwargs: statuses.append(str(kwargs.get("status"))),
    )
    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="",
        kimi_api_key="",
    ), transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=body)))
    replies = gateway.stream(
        system="system",
        user="slow consumer cancellation",
        cancellation_event=cancellation,
    )

    try:
        assert next(replies).content == "x"
        assert body.queue_saturated.wait(0.2)
        sleep(0.04)
        reads_while_blocked = body.read_count
        sleep(0.04)
        assert reads_while_blocked == 4
        assert body.read_count == reads_while_blocked

        cancellation.set()
        with pytest.raises(ModelUnavailable, match="cancelled"):
            next(replies)
    finally:
        replies.close()

    assert body.exited.wait(0.2)
    reads_at_terminal = body.read_count
    sleep(0.03)
    assert body.read_count == reads_at_terminal
    assert statuses == ["CANCELLED"]
    assert gateway.last_response is None


def test_model_stream_slow_consumer_deadline_stops_blocked_reader(monkeypatch):
    body = _BurstSseStream()
    statuses: list[str] = []
    monkeypatch.setattr(model_gateway_service, "_NETWORK_STREAM_QUEUE_MAX_EVENTS", 2)
    monkeypatch.setattr(
        model_gateway_service,
        "record_model_invocation",
        lambda *_args, **kwargs: statuses.append(str(kwargs.get("status"))),
    )
    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="",
        kimi_api_key="",
    ), transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=body)))
    gateway._request_timeout = lambda _request, _event: 0.08
    replies = gateway.stream(system="system", user="slow consumer deadline")

    try:
        assert next(replies).content == "x"
        assert body.queue_saturated.wait(0.2)
        assert body.read_count == 4
        sleep(0.1)
        with pytest.raises(ModelUnavailable, match="failed after content was emitted"):
            next(replies)
    finally:
        replies.close()

    assert body.exited.wait(0.2)
    reads_at_terminal = body.read_count
    sleep(0.03)
    assert body.read_count == reads_at_terminal
    assert statuses == ["FAILED"]
    assert gateway.last_response is None


def test_model_stream_rejects_overlong_line_without_newline(monkeypatch):
    body = _TrackedChunksStream(b"x" * 33)
    statuses: list[str] = []
    monkeypatch.setattr(model_gateway_service, "_NETWORK_STREAM_MAX_LINE_BYTES", 32)
    monkeypatch.setattr(model_gateway_service, "_NETWORK_STREAM_MAX_RESPONSE_BYTES", 256)
    monkeypatch.setattr(
        model_gateway_service,
        "record_model_invocation",
        lambda *_args, **kwargs: statuses.append(str(kwargs.get("status"))),
    )
    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="",
        kimi_api_key="",
    ), transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=body)))

    with pytest.raises(ModelUnavailable, match="All configured model provider streams failed"):
        list(gateway.stream(system="system", user="overlong line"))

    assert body.exited.wait(0.2)
    reads_at_terminal = body.read_count
    sleep(0.03)
    assert body.read_count == reads_at_terminal
    assert statuses == ["FAILED"]
    assert gateway.last_response is None


def test_model_stream_rejects_excessive_total_response_after_partial_content(monkeypatch):
    body = _TwoPhaseSseStream()
    statuses: list[str] = []
    monkeypatch.setattr(model_gateway_service, "_NETWORK_STREAM_MAX_LINE_BYTES", 128)
    monkeypatch.setattr(
        model_gateway_service,
        "_NETWORK_STREAM_MAX_RESPONSE_BYTES",
        len(_SSE_DELTA) * 2 - 1,
    )
    monkeypatch.setattr(
        model_gateway_service,
        "record_model_invocation",
        lambda *_args, **kwargs: statuses.append(str(kwargs.get("status"))),
    )
    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="",
        kimi_api_key="",
    ), transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=body)))
    replies = gateway.stream(system="system", user="excessive total response")

    try:
        assert next(replies).content == "x"
        assert body.waiting_for_release.wait(0.2)
        body.release_second.set()
        with pytest.raises(ModelUnavailable, match="became invalid after content was emitted"):
            next(replies)
    finally:
        body.release_second.set()
        replies.close()

    assert body.exited.wait(0.2)
    reads_at_terminal = body.read_count
    sleep(0.03)
    assert body.read_count == reads_at_terminal
    assert statuses == ["FAILED"]
    assert gateway.last_response is None


@pytest.mark.parametrize(
    "chunks",
    [
        (b"first\rsecond\r",),
        (b"first\nsecond\n",),
        (b"first\r\nsecond\r\n",),
        (b"first\r", b"\nsecond\r", b"\n"),
    ],
    ids=("cr", "lf", "crlf", "crlf-split-across-chunks"),
)
def test_controlled_model_stream_supports_universal_line_endings(chunks):
    body = _TrackedChunksStream(*chunks)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, stream=body)
        )
    ) as client:
        lines = list(model_gateway_service._controlled_stream_lines(
            client,
            url="https://provider.invalid/chat/completions",
            headers={},
            payload={},
            cancellation_event=None,
            timeout_seconds=1,
        ))

    assert lines == ["first", "second"]
    assert body.exited.is_set()


def test_model_real_http_midflight_cancel_has_no_success_or_late_publication(monkeypatch):
    body_started = Event()
    body_exited = Event()
    statuses: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "4096")
            self.end_headers()
            body_started.set()
            try:
                for _ in range(4096):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    sleep(0.005)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                body_exited.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server_thread = Thread(
        target=lambda: server.serve_forever(poll_interval=0.01),
        daemon=True,
    )
    server_thread.start()
    cancellation = Event()

    def cancel_midflight():
        assert body_started.wait(1)
        sleep(0.03)
        cancellation.set()

    cancel_thread = Thread(target=cancel_midflight)
    cancel_thread.start()
    monkeypatch.setattr(
        "app.model_gateway.service.record_model_invocation",
        lambda *_args, **kwargs: statuses.append(str(kwargs.get("status"))),
    )
    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        mimo_base_url=f"http://127.0.0.1:{server.server_port}/v1",
        deepseek_api_key="",
        kimi_api_key="",
    ))
    started = monotonic()
    try:
        with pytest.raises(ModelUnavailable, match="cancelled"):
            gateway.complete(
                system="system",
                user="real HTTP no-newline body",
                cancellation_event=cancellation,
            )
    finally:
        cancel_thread.join(timeout=1)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=1)

    assert monotonic() - started < 0.4
    assert body_exited.wait(0.1)
    assert statuses == ["CANCELLED"]
    assert gateway.last_response is None


def test_nl2sql_policy_prefers_deepseek():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="unit-test-only",
        kimi_api_key="unit-test-only",
    ), transport=httpx.MockTransport(handler))
    response = gateway.execute(ModelRequest(
        capability=ModelCapability.NL2SQL,
        messages=({"role": "user", "content": "return json"},),
        json_mode=True,
        complexity_score=60,
    ), _context())
    assert response.resolved_provider == "deepseek"
    assert calls == ["https://api.deepseek.com/chat/completions"]


def test_quality_premium_trigger_selects_kimi_once():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "premium"}}]})

    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="unit-test-only",
        kimi_api_key="unit-test-only",
        model_budget_mode="quality",
    ), transport=httpx.MockTransport(handler))
    reply = gateway.complete(
        system="system", user="深度分析", context=_context(budget_mode=BudgetMode.QUALITY),
        complexity_score=85, budget_mode=BudgetMode.QUALITY,
    )
    assert reply.provider == "kimi"
    assert len(calls) == 1


def test_complex_presentation_can_prefer_kimi_without_spending_output_on_reasoning():
    payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={
            "model": "kimi-k2.6",
            "choices": [{"finish_reason": "stop", "message": {"content": '{"answer":"ok"}'}}],
        })

    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="unit-test-only",
        kimi_api_key="unit-test-only",
        provider_usage_unrestricted=True,
    ), transport=httpx.MockTransport(handler))

    reply = gateway.complete(
        system="system",
        user="present verified answer",
        context=_context(),
        complexity_score=90,
        thinking=False,
        max_output_tokens=1024,
    )

    assert reply.provider == "kimi"
    assert payloads[0]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payloads[0]
    assert payloads[0]["max_completion_tokens"] == 1024


def test_kimi_health_probe_uses_a_bounded_output_budget():
    payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={
            "model": "kimi-k2.6",
            "choices": [{"finish_reason": "stop", "message": {"content": "OK"}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 1, "total_tokens": 9},
        })

    gateway = ModelGateway(Settings(
        _env_file=None, mimo_api_key="", deepseek_api_key="", kimi_api_key="unit-test-only",
    ), transport=httpx.MockTransport(handler))

    result = gateway.probe("kimi", context=_context())

    assert result == {"provider": "kimi", "model": "kimi-k2.6", "status": "PASS"}
    assert len(payloads) == 1
    assert payloads[0]["max_completion_tokens"] == 8


def test_kimi_hard_budget_never_retries_within_one_request():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "rate limited"})

    gateway = ModelGateway(Settings(
        _env_file=None, mimo_api_key="", deepseek_api_key="", kimi_api_key="unit-test-only",
        model_budget_mode="quality",
    ), transport=httpx.MockTransport(handler), sleeper=lambda _: None)
    with pytest.raises(ModelUnavailable):
        gateway.complete(
            system="system", user="deep analysis", requested_alias="kimi.premium",
            complexity_score=90, budget_mode=BudgetMode.QUALITY,
        )
    assert calls == ["https://api.moonshot.cn/v1/chat/completions"]


def test_unrestricted_provider_mode_removes_cost_routing_caps_and_allows_kimi_retry():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "rate limited"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "available"}}]})

    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="unit-test-only",
        kimi_api_key="unit-test-only",
        model_budget_mode="quality",
        provider_usage_unrestricted=True,
    ), transport=httpx.MockTransport(handler), sleeper=lambda _: None)
    request = ModelRequest(
        capability=ModelCapability.GENERAL,
        messages=({"role": "user", "content": "ordinary request"},),
        budget_mode=BudgetMode.QUALITY,
        max_output_tokens=16_384,
    )
    assert gateway.policy.provider_candidates(request)[:3] == ["mimo", "deepseek", "kimi"]
    assert gateway.policy.within_budget("kimi", request) is True
    assert gateway.policy.is_unrestricted_provider("openai-compatible") is False
    assert gateway.policy.max_output_tokens(request, provider="kimi") == 16_384
    assert gateway.policy.max_output_tokens(request, provider="openai-compatible") == 8192
    assert gateway.policy.safe_summary()["limits"]["max_model_escalations"] == 2
    assert gateway.policy.safe_summary()["limits"]["max_kimi_calls_per_request"] is None
    assert gateway.policy.safe_summary()["unrestricted_providers"] == ["deepseek", "kimi", "mimo"]

    premium_request = request.model_copy(update={"complexity_score": 90})
    assert gateway.policy.provider_candidates(premium_request)[0] == "kimi"
    unrestricted_balanced = premium_request.model_copy(update={"budget_mode": BudgetMode.BALANCED})
    assert gateway.policy.provider_candidates(unrestricted_balanced)[0] == "kimi"

    reply = gateway.complete(
        system="system",
        user="retry Kimi",
        requested_alias="kimi",
        budget_mode=BudgetMode.QUALITY,
    )
    assert reply.provider == "kimi"
    assert len(calls) == 2


def test_unrestricted_execute_reaches_each_provider_before_same_provider_retry():
    calls: list[str] = []
    provider_call_counts: dict[str, int] = {}
    reservations: list[tuple[str, int, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        provider = _provider_id(request)
        calls.append(provider)
        provider_call_counts[provider] = provider_call_counts.get(provider, 0) + 1
        if provider == "deepseek":
            return httpx.Response(200, content=b"not-json")
        if provider == "mimo" and provider_call_counts[provider] == 2:
            return httpx.Response(200, json={
                "model": "mimo-v2.5",
                "choices": [{"message": {"content": "retry succeeded"}}],
            })
        return httpx.Response(
            503,
            headers={"Retry-After": "0"},
            json={"error": "temporarily unavailable"},
        )

    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="unit-test-only",
        kimi_api_key="unit-test-only",
        provider_usage_unrestricted=True,
    ), transport=httpx.MockTransport(handler), sleeper=lambda _: None)
    original_reserve = gateway.test_cost_control.reserve_attempt

    def record_reservation(**kwargs):
        reservations.append((
            str(kwargs["provider"]),
            int(kwargs["retry_count"]),
            int(kwargs["fallback_count"]),
        ))
        return original_reserve(**kwargs)

    gateway.test_cost_control.reserve_attempt = record_reservation
    result = gateway.execute(ModelRequest(
        capability=ModelCapability.NL2SQL,
        messages=({"role": "user", "content": "fair execute"},),
    ), _context())

    assert calls == ["deepseek", "mimo", "kimi", "mimo"]
    assert reservations == [
        ("deepseek", 0, 0),
        ("mimo", 0, 1),
        ("kimi", 0, 2),
        ("mimo", 1, 1),
    ]
    assert result.resolved_provider == "mimo"
    assert result.fallback_count == 1
    assert result.retry_count == 1


def test_governed_execute_keeps_provider_major_retry_order():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        provider = _provider_id(request)
        calls.append(provider)
        if len(calls) == 1:
            return httpx.Response(
                503,
                headers={"Retry-After": "0"},
                json={"error": "temporarily unavailable"},
            )
        return httpx.Response(200, json={
            "model": "mimo-v2.5",
            "choices": [{"message": {"content": "governed retry"}}],
        })

    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="unit-test-only",
        kimi_api_key="unit-test-only",
        provider_usage_unrestricted=False,
    ), transport=httpx.MockTransport(handler), sleeper=lambda _: None)

    result = gateway.execute(ModelRequest(
        capability=ModelCapability.GENERAL,
        messages=({"role": "user", "content": "governed order"},),
    ), _context())

    assert calls == ["mimo", "mimo"]
    assert result.resolved_provider == "mimo"
    assert result.fallback_count == 0
    assert result.retry_count == 1


def test_unrestricted_stream_reaches_each_provider_before_same_provider_retry():
    calls: list[str] = []
    provider_call_counts: dict[str, int] = {}
    reservations: list[tuple[str, int, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        provider = _provider_id(request)
        calls.append(provider)
        provider_call_counts[provider] = provider_call_counts.get(provider, 0) + 1
        if provider == "mimo" and provider_call_counts[provider] == 2:
            return httpx.Response(200, content=(
                b'data: {"model":"mimo-v2.5","choices":[{"delta":{"content":"stream-ok"}}]}\n'
                b'data: [DONE]\n'
            ))
        return httpx.Response(
            503,
            headers={"Retry-After": "0"},
            json={"error": "temporarily unavailable"},
        )

    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="unit-test-only",
        kimi_api_key="unit-test-only",
        provider_usage_unrestricted=True,
    ), transport=httpx.MockTransport(handler), sleeper=lambda _: None)
    original_reserve = gateway.test_cost_control.reserve_attempt

    def record_reservation(**kwargs):
        reservations.append((
            str(kwargs["provider"]),
            int(kwargs["retry_count"]),
            int(kwargs["fallback_count"]),
        ))
        return original_reserve(**kwargs)

    gateway.test_cost_control.reserve_attempt = record_reservation
    replies = list(gateway.stream(system="system", user="fair stream", context=_context()))

    assert [reply.content for reply in replies] == ["stream-ok"]
    assert calls == ["mimo", "deepseek", "kimi", "mimo"]
    assert reservations == [
        ("mimo", 0, 0),
        ("deepseek", 0, 1),
        ("kimi", 0, 2),
        ("mimo", 1, 0),
    ]
    assert gateway.last_response is not None
    assert gateway.last_response.resolved_provider == "mimo"
    assert gateway.last_response.fallback_count == 0
    assert gateway.last_response.retry_count == 1


def test_unrestricted_success_uses_provider_local_invocation_retry_count(monkeypatch):
    calls: list[str] = []
    counts: dict[str, int] = {}
    success_invocations: list[int | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        provider = _provider_id(request)
        calls.append(provider)
        counts[provider] = counts.get(provider, 0) + 1
        if provider == "mimo" and counts[provider] == 2:
            return httpx.Response(200, json={
                "model": "mimo-v2.5",
                "choices": [{"message": {"content": "local retry"}}],
            })
        return httpx.Response(503, headers={"Retry-After": "0"})

    def capture_invocation(*_args, **kwargs):
        if kwargs.get("status") == "SUCCEEDED":
            success_invocations.append(kwargs.get("retry_count"))

    monkeypatch.setattr(model_gateway_service, "record_model_invocation", capture_invocation)
    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="unit-test-only",
        kimi_api_key="unit-test-only",
        provider_usage_unrestricted=True,
    ), transport=httpx.MockTransport(handler), sleeper=lambda _: None)

    result = gateway.execute(ModelRequest(
        capability=ModelCapability.NL2SQL,
        messages=({"role": "user", "content": "local retry count"},),
    ), _context())

    assert calls == ["deepseek", "mimo", "kimi", "deepseek", "mimo"]
    assert result.retry_count == 2
    assert success_invocations == [1]


def test_unrestricted_retry_backoff_counts_time_spent_on_other_providers():
    class Clock:
        value = 0.0

        def __call__(self) -> float:
            return self.value

    clock = Clock()
    sleeps: list[float] = []
    counts: dict[str, int] = {}

    def sleeper(delay: float) -> None:
        sleeps.append(delay)
        clock.value += delay

    def handler(request: httpx.Request) -> httpx.Response:
        provider = _provider_id(request)
        counts[provider] = counts.get(provider, 0) + 1
        if provider == "deepseek" and counts[provider] == 1:
            return httpx.Response(503, headers={"Retry-After": "2"})
        if provider == "mimo" and counts[provider] == 1:
            clock.value += 1.5
            return httpx.Response(503, headers={"Retry-After": "0"})
        if provider == "kimi":
            return httpx.Response(400)
        return httpx.Response(200, json={
            "model": "deepseek-v4-flash",
            "choices": [{"message": {"content": "backoff elapsed"}}],
        })

    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="unit-test-only",
        kimi_api_key="unit-test-only",
        provider_usage_unrestricted=True,
    ), transport=httpx.MockTransport(handler), sleeper=sleeper, clock=clock)

    result = gateway.execute(ModelRequest(
        capability=ModelCapability.NL2SQL,
        messages=({"role": "user", "content": "elapsed backoff"},),
    ), _context())

    assert result.resolved_provider == "deepseek"
    assert sleeps == [pytest.approx(0.5)]


def test_retry_backoff_wait_is_cancellable_without_starting_reserved_retry():
    calls: list[str] = []
    cancellation = Event()
    timer = Timer(0.05, cancellation.set)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(_provider_id(request))
        return httpx.Response(503, headers={"Retry-After": "2"})

    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="",
        kimi_api_key="",
    ), transport=httpx.MockTransport(handler))
    started = monotonic()
    timer.start()
    try:
        with pytest.raises(ModelUnavailable, match="cancelled"):
            gateway.execute(ModelRequest(
                capability=ModelCapability.GENERAL,
                messages=({"role": "user", "content": "cancel backoff"},),
            ), _context(), cancellation_event=cancellation)
    finally:
        timer.join(timeout=1)

    assert monotonic() - started < 0.25
    assert calls == ["mimo"]
    assert gateway.last_response is None


def test_unrestricted_execute_cancellation_wins_before_fallback_or_retry():
    calls: list[str] = []
    cancellation = Event()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(_provider_id(request))
        cancellation.set()
        return httpx.Response(503, json={"error": "cancelled"})

    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="unit-test-only",
        kimi_api_key="unit-test-only",
        provider_usage_unrestricted=True,
    ), transport=httpx.MockTransport(handler), sleeper=lambda _: None)

    with pytest.raises(ModelUnavailable, match="cancelled"):
        gateway.execute(ModelRequest(
            capability=ModelCapability.GENERAL,
            messages=({"role": "user", "content": "cancel fair schedule"},),
        ), _context(), cancellation_event=cancellation)

    assert calls == ["mimo"]
    assert gateway.last_response is None


def test_unrestricted_stream_deadline_wins_before_fallback_or_retry():
    class DeadlineSignal:
        def __init__(self) -> None:
            self.deadline = monotonic() + 0.05

        @property
        def remaining_seconds(self) -> float:
            return max(0.0, self.deadline - monotonic())

        def is_set(self) -> bool:
            return self.remaining_seconds == 0.0

    calls: list[str] = []
    body = _SlowNoNewlineStream()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(_provider_id(request))
        return httpx.Response(200, stream=body)

    gateway = ModelGateway(Settings(
        _env_file=None,
        mimo_api_key="unit-test-only",
        deepseek_api_key="unit-test-only",
        kimi_api_key="unit-test-only",
        provider_usage_unrestricted=True,
    ), transport=httpx.MockTransport(handler), sleeper=lambda _: None)
    signal = DeadlineSignal()

    with pytest.raises(ModelUnavailable, match="cancelled"):
        list(gateway.stream(
            system="system",
            user="deadline fair schedule",
            context=_context(),
            cancellation_event=signal,
        ))

    assert calls == ["mimo"]
    assert body.exited.wait(0.2)
    assert gateway.last_response is None


def test_circuit_breaker_opens_after_repeated_retryable_failures():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(503, json={"error": "unavailable"})

    gateway = ModelGateway(Settings(
        _env_file=None, mimo_api_key="unit-test-only", deepseek_api_key="", kimi_api_key="",
    ), transport=httpx.MockTransport(handler), sleeper=lambda _: None)
    with pytest.raises(ModelUnavailable):
        gateway.complete(system="system", user="first")
    with pytest.raises(ModelUnavailable):
        gateway.complete(system="system", user="second")
    assert gateway.health_snapshot()["mimo"]["state"] == "OPEN"
    before = len(calls)
    with pytest.raises(ModelUnavailable):
        gateway.complete(system="system", user="third")
    assert len(calls) == before


def test_cancelled_request_stops_before_provider_network_call():
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"choices": [{"message": {"content": "unexpected"}}]})

    gateway = ModelGateway(
        Settings(_env_file=None, mimo_api_key="unit-test-only"),
        transport=httpx.MockTransport(handler),
    )
    cancelled = Event()
    cancelled.set()
    with pytest.raises(ModelUnavailable, match="cancelled"):
        gateway.complete(system="system", user="hello", cancellation_event=cancelled)
    assert called is False


def test_sse_contract_carries_same_trace_and_request_identity():
    factory = StreamEventFactory(
        run_id="TRACE-runtime-control-001",
        request_id="client-request-001",
        conversation_id="conversation-a",
        message_id="client-request-001",
    )
    event = factory.create("run.started", status="RUNNING")
    assert event["trace_id"] == "TRACE-runtime-control-001"
    assert event["run_id"] == event["trace_id"]
    assert event["request_id"] == event["message_id"] == "client-request-001"
