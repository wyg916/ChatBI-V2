from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from app.core.config import Settings


_CONFIG_ROOT = Path(__file__).resolve().parents[2] / "config"


@lru_cache(maxsize=8)
def load_control_config(filename: str) -> dict[str, Any]:
    # Files use the JSON subset of YAML 1.2 so the runtime needs no extra parser.
    return json.loads((_CONFIG_ROOT / filename).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class ProviderDefinition:
    provider_id: str
    display_name: str
    base_url_field: str
    api_key_field: str
    model_name_field: str
    credential_env: str
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    max_tokens_field: str = "max_tokens"
    request_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedProvider:
    provider_id: str
    display_name: str
    base_url: str
    api_key: str = field(repr=False)
    model_name: str
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    max_tokens_field: str = "max_tokens"
    request_options: dict[str, Any] = field(default_factory=dict)


PROVIDER_DEFINITIONS = (
    ProviderDefinition(
        provider_id="mimo", display_name="Xiaomi MiMo",
        base_url_field="mimo_base_url", api_key_field="mimo_api_key",
        model_name_field="mimo_model_name", credential_env="CHATBI_MIMO_API_KEY",
        auth_header="api-key", auth_prefix="", max_tokens_field="max_completion_tokens",
    ),
    ProviderDefinition(
        provider_id="deepseek", display_name="DeepSeek",
        base_url_field="deepseek_base_url", api_key_field="deepseek_api_key",
        model_name_field="deepseek_model_name", credential_env="CHATBI_DEEPSEEK_API_KEY",
    ),
    ProviderDefinition(
        provider_id="kimi", display_name="Moonshot Kimi",
        base_url_field="kimi_base_url", api_key_field="kimi_api_key",
        model_name_field="kimi_model_name", credential_env="CHATBI_KIMI_API_KEY",
        max_tokens_field="max_completion_tokens",
    ),
    ProviderDefinition(
        provider_id="openai-compatible", display_name="OpenAI Compatible",
        base_url_field="model_base_url", api_key_field="model_api_key",
        model_name_field="model_name", credential_env="CHATBI_MODEL_API_KEY",
        request_options={"temperature": 0},
    ),
)


def secret_value(value: str | SecretStr) -> str:
    return value.get_secret_value() if isinstance(value, SecretStr) else value


def resolve_provider(settings: Settings, definition: ProviderDefinition) -> ResolvedProvider:
    return ResolvedProvider(
        provider_id=definition.provider_id,
        display_name=definition.display_name,
        base_url=str(getattr(settings, definition.base_url_field)).rstrip("/"),
        api_key=secret_value(getattr(settings, definition.api_key_field)),
        model_name=str(getattr(settings, definition.model_name_field)).strip(),
        auth_header=definition.auth_header,
        auth_prefix=definition.auth_prefix,
        max_tokens_field=definition.max_tokens_field,
        request_options=dict(definition.request_options),
    )


def configured_providers(settings: Settings) -> dict[str, ResolvedProvider]:
    result: dict[str, ResolvedProvider] = {}
    for definition in PROVIDER_DEFINITIONS:
        provider = resolve_provider(settings, definition)
        if provider.base_url and provider.api_key and provider.model_name:
            result[provider.provider_id] = provider
    return result
