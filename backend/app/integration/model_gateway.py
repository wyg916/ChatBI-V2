from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.query.nl2sql import PROVIDER_DEFINITIONS, _provider_values


class ModelUnavailable(RuntimeError):
    pass


class VisionModelUnavailable(ModelUnavailable):
    pass


@dataclass(frozen=True)
class ModelReply:
    content: str
    provider: str
    model: str


def _definitions(settings: Settings, requested: str, *, vision: bool = False):
    selected = requested.strip().lower()
    if selected == "auto":
        active = settings.model_provider.strip().lower()
        preferred = [active] if active not in {"", "auto", "deterministic"} else []
        preferred.extend([item.provider_id for item in PROVIDER_DEFINITIONS])
    else:
        preferred = [selected]
    configured = []
    for provider_id in dict.fromkeys(preferred):
        definition = next((item for item in PROVIDER_DEFINITIONS if item.provider_id == provider_id), None)
        if definition and all(_provider_values(settings, definition)):
            configured.append(definition)
    if configured:
        return configured
    error = VisionModelUnavailable if vision else ModelUnavailable
    raise error("No configured external model provider is available")


class ModelGateway:
    def __init__(self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None):
        self.settings = settings or get_settings()
        self.transport = transport

    def complete(
        self,
        *,
        system: str,
        user: str,
        history: list[dict[str, str]] | None = None,
        image_data_urls: list[str] | None = None,
        json_mode: bool = False,
        vision: bool = False,
    ) -> ModelReply:
        requested = self.settings.vision_model_provider if vision else self.settings.general_model_provider
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        messages.extend(history or [])
        if image_data_urls:
            content: list[dict[str, Any]] = [{"type": "text", "text": user}]
            content.extend({"type": "image_url", "image_url": {"url": value}} for value in image_data_urls)
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": user})
        failures: list[str] = []
        for definition in _definitions(self.settings, requested, vision=vision):
            base_url, api_key, configured_model = _provider_values(self.settings, definition)
            model = self.settings.vision_model_name.strip() if vision and self.settings.vision_model_name.strip() else configured_model
            payload: dict[str, Any] = {"model": model, "stream": False, "messages": messages}
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            payload.update(definition.request_options or {})
            try:
                with httpx.Client(timeout=45, transport=self.transport) as client:
                    response = client.post(
                        f"{base_url}/chat/completions",
                        headers={definition.auth_header: f"{definition.auth_prefix}{api_key}"},
                        json=payload,
                    )
                    response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("model returned empty content")
                return ModelReply(content=content.strip(), provider=definition.provider_id, model=model)
            except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                failures.append(f"{definition.provider_id}:{type(exc).__name__}")
        error = VisionModelUnavailable if vision else ModelUnavailable
        raise error("All configured model providers failed: " + ", ".join(failures))

    def classify(self, question: str, *, history_summary: str = "") -> str:
        reply = self.complete(
            system=(
                "Classify the request for an enterprise ChatBI router. Return JSON only with key route. "
                "Allowed: DATA_QUERY, KNOWLEDGE_QUERY, HYBRID_ANALYSIS, COMPLEX_ANALYSIS, GENERAL_CHAT, "
                "CLARIFICATION, UNSUPPORTED. DATA_QUERY is any request requiring database facts. "
                "KNOWLEDGE_QUERY requires internal governed knowledge. HYBRID combines both. COMPLEX needs bounded multi-step analysis. "
                "CLARIFICATION means essential business details are missing. UNSUPPORTED includes writes, destructive actions, or disallowed access."
            ),
            user=json.dumps({"question": question, "conversation_summary": history_summary}, ensure_ascii=False),
            json_mode=True,
        )
        try:
            return str(json.loads(reply.content)["route"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ModelUnavailable("Model router returned invalid JSON") from exc
