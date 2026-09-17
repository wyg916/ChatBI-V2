from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.model_gateway import ModelGateway, VisionModelUnavailable


def _gateway(handler):
    return ModelGateway(
        Settings(
            _env_file=None,
            mimo_api_key="unit-test-mimo",
            kimi_api_key="unit-test-kimi",
            deepseek_api_key="unit-test-deepseek",
            vision_model_provider="auto",
            model_budget_mode="balanced",
        ),
        transport=httpx.MockTransport(handler),
        sleeper=lambda _seconds: None,
    )


def test_ordinary_image_is_mimo_only_and_never_uses_kimi_as_fallback():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "rate limited"})

    with pytest.raises(VisionModelUnavailable):
        _gateway(handler).complete(
            system="system",
            user="read this image",
            image_data_urls=["data:image/png;base64,iVBORw0KGgo="],
            vision=True,
        )
    assert calls
    assert all("xiaomimimo" in url for url in calls)


def test_observable_vision_trigger_escalates_to_kimi_exactly_once():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "verified"}}]})

    reply = _gateway(handler).complete(
        system="system",
        user="small text",
        image_data_urls=["data:image/png;base64,iVBORw0KGgo="],
        vision=True,
        premium_triggers=frozenset({"low_quality_document"}),
    )
    assert reply.provider == "kimi"
    assert calls == ["https://api.moonshot.cn/v1/chat/completions"]


def test_explicit_kimi_without_trigger_fails_before_network():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "unexpected"}}]})

    with pytest.raises(VisionModelUnavailable):
        _gateway(handler).complete(
            system="system",
            user="ordinary image",
            image_data_urls=["data:image/png;base64,iVBORw0KGgo="],
            vision=True,
            requested_alias="kimi",
        )
    assert calls == []
