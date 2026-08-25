from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.model_gateway.contracts import ModelUsage


class ProviderResponseNormalizationError(ValueError):
    """Fail-closed error for an unknown Chat Completions response shape."""


@dataclass(frozen=True)
class CanonicalChatCompletion:
    content: str
    tool_calls: tuple[dict[str, Any], ...]
    finish_reason: str | None
    resolved_model: str | None
    usage: ModelUsage
    reasoning_observed: bool


def _integer(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise ProviderResponseNormalizationError(f"PROVIDER_USAGE_INVALID:{field}")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ProviderResponseNormalizationError(f"PROVIDER_USAGE_INVALID:{field}") from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise ProviderResponseNormalizationError(f"PROVIDER_USAGE_INVALID:{field}")
    return max(0, int(number))


def normalize_usage(payload: Any) -> ModelUsage:
    if payload in (None, {}):
        return ModelUsage()
    if not isinstance(payload, Mapping):
        raise ProviderResponseNormalizationError("PROVIDER_USAGE_OBJECT_REQUIRED")
    prompt_value = payload.get("prompt_tokens", payload.get("input_tokens"))
    output_value = payload.get("completion_tokens", payload.get("output_tokens"))
    total_value = payload.get("total_tokens")
    if prompt_value is None or output_value is None:
        return ModelUsage()
    prompt = _integer(prompt_value, field="input_tokens")
    output = _integer(output_value, field="output_tokens")
    details = payload.get("prompt_tokens_details", payload.get("input_tokens_details", {})) or {}
    if not isinstance(details, Mapping):
        raise ProviderResponseNormalizationError("PROVIDER_USAGE_DETAILS_OBJECT_REQUIRED")
    cached_value = details.get("cached_tokens", payload.get("cached_tokens", 0))
    cached = _integer(cached_value, field="cached_input_tokens")
    total = prompt + output if total_value is None else max(
        prompt + output,
        _integer(total_value, field="total_tokens"),
    )
    return ModelUsage(
        input_tokens=prompt,
        cached_input_tokens=min(cached, prompt),
        output_tokens=output,
        total_tokens=total,
        exact=True,
    )


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        chunks: list[str] = []
        for item in value:
            if not isinstance(item, Mapping):
                raise ProviderResponseNormalizationError("PROVIDER_CONTENT_PART_OBJECT_REQUIRED")
            part_type = str(item.get("type") or "text").strip().lower()
            if part_type not in {"text", "output_text"}:
                raise ProviderResponseNormalizationError(
                    f"PROVIDER_CONTENT_PART_TYPE_UNSUPPORTED:{part_type or 'missing'}"
                )
            text = item.get("text", item.get("content"))
            if not isinstance(text, str):
                raise ProviderResponseNormalizationError("PROVIDER_CONTENT_PART_TEXT_REQUIRED")
            chunks.append(text)
        return "".join(chunks).strip()
    raise ProviderResponseNormalizationError("PROVIDER_CONTENT_TYPE_UNSUPPORTED")


def normalize_chat_completion(payload: Any) -> CanonicalChatCompletion:
    if not isinstance(payload, Mapping):
        raise ProviderResponseNormalizationError("PROVIDER_RESPONSE_OBJECT_REQUIRED")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise ProviderResponseNormalizationError("PROVIDER_CHOICES_REQUIRED")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise ProviderResponseNormalizationError("PROVIDER_MESSAGE_REQUIRED")
    content = _content_text(message.get("content"))
    raw_tool_calls = message.get("tool_calls") or ()
    if not isinstance(raw_tool_calls, (list, tuple)) or any(
        not isinstance(item, Mapping) for item in raw_tool_calls
    ):
        raise ProviderResponseNormalizationError("PROVIDER_TOOL_CALLS_INVALID")
    tool_calls = tuple(dict(item) for item in raw_tool_calls)
    if not content and not tool_calls:
        raise ProviderResponseNormalizationError("PROVIDER_EMPTY_CONTENT")
    finish_reason = choice.get("finish_reason")
    if finish_reason is not None and not isinstance(finish_reason, str):
        raise ProviderResponseNormalizationError("PROVIDER_FINISH_REASON_INVALID")
    model = payload.get("model")
    if model is not None and not isinstance(model, (str, int, float)):
        raise ProviderResponseNormalizationError("PROVIDER_MODEL_ID_INVALID")
    return CanonicalChatCompletion(
        content=content,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        resolved_model=str(model) if model is not None else None,
        usage=normalize_usage(payload.get("usage")),
        reasoning_observed=bool(message.get("reasoning_content")),
    )
