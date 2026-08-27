from __future__ import annotations

import json
from threading import Event

import httpx
import pytest

from app.core.config import Settings
from app.integration.question_router import QuestionRouter
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
