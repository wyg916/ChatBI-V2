from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.query.contracts import QueryFilter, QueryTimeRange, SQLPlan


class Nl2SqlResponseNormalizationError(ValueError):
    """Unknown model output remains rejected before SQL Guard or execution."""


_FENCE = re.compile(r"\A```(?:json)?\s*(.*?)\s*```\Z", re.IGNORECASE | re.DOTALL)
_WRAPPER_KEYS = ("sql_plan", "plan", "result", "data")
_MAX_RESPONSE_CHARS = 200_000
SERVER_OWNED_FIELDS = frozenset({"model_trace"})
STRIP_SERVER_OWNED_MODEL_TRACE = "STRIP_SERVER_OWNED_MODEL_TRACE"


class ProviderSQLPlanPayload(BaseModel):
    """Strict Provider-facing DTO; runtime metadata is deliberately absent."""

    model_config = ConfigDict(extra="forbid")

    question: str
    intent: str
    dialect: Literal["postgresql", "mysql"]
    provider: str
    semantic_model_id: str
    semantic_model_version: int
    selected_entities: list[str]
    selected_tables: list[str]
    selected_columns: list[str]
    metrics: list[str]
    dimensions: list[str]
    joins: list[dict[str, Any]]
    filters: list[QueryFilter]
    time_range: QueryTimeRange | None = None
    group_by: list[str] = Field(default_factory=list)
    order_by: list[str] = Field(default_factory=list)
    limit: int = Field(ge=1, le=5000)
    generated_sql: str
    confidence: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)
    repair_count: int = Field(default=0, ge=0, le=2)


@dataclass(frozen=True)
class NormalizedNl2SqlResponse:
    plan: SQLPlan
    normalization_actions: tuple[str, ...]


def _decode_text(value: str, *, allow_nested_string: bool = True) -> Any:
    stripped = value.strip()
    if not stripped or len(stripped) > _MAX_RESPONSE_CHARS:
        raise Nl2SqlResponseNormalizationError("NL2SQL_RESPONSE_EMPTY_OR_TOO_LARGE")
    fenced = _FENCE.fullmatch(stripped)
    if fenced:
        stripped = fenced.group(1).strip()
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise Nl2SqlResponseNormalizationError("NL2SQL_RESPONSE_JSON_INVALID") from exc
    if isinstance(decoded, str) and allow_nested_string:
        return _decode_text(decoded, allow_nested_string=False)
    return decoded


def _strip_server_owned_fields(payload: dict[str, Any], actions: list[str]) -> dict[str, Any]:
    for field in SERVER_OWNED_FIELDS.intersection(payload):
        payload.pop(field)
        if field == "model_trace":
            actions.append(STRIP_SERVER_OWNED_MODEL_TRACE)
    return payload


def _canonical_nl2sql_payload(value: Any) -> tuple[dict[str, Any], tuple[str, ...]]:
    decoded = _decode_text(value) if isinstance(value, str) else value
    if not isinstance(decoded, Mapping):
        raise Nl2SqlResponseNormalizationError("NL2SQL_RESPONSE_OBJECT_REQUIRED")
    actions: list[str] = []
    payload = _strip_server_owned_fields(dict(decoded), actions)
    matching_wrappers = [key for key in _WRAPPER_KEYS if key in payload]
    if matching_wrappers and not {"generated_sql", "intent"}.issubset(payload):
        if len(matching_wrappers) != 1 or len(payload) != 1:
            raise Nl2SqlResponseNormalizationError("NL2SQL_RESPONSE_WRAPPER_AMBIGUOUS")
        wrapped = payload[matching_wrappers[0]]
        if isinstance(wrapped, str):
            wrapped = _decode_text(wrapped)
        if not isinstance(wrapped, Mapping):
            raise Nl2SqlResponseNormalizationError("NL2SQL_RESPONSE_WRAPPED_OBJECT_REQUIRED")
        payload = _strip_server_owned_fields(dict(wrapped), actions)
    return payload, tuple(dict.fromkeys(actions))


def canonical_nl2sql_payload(value: Any) -> dict[str, Any]:
    payload, _actions = _canonical_nl2sql_payload(value)
    return payload


def normalize_nl2sql_response_with_metadata(value: Any) -> NormalizedNl2SqlResponse:
    """Validate a strict Provider DTO, then create the internal SQLPlan."""

    try:
        payload, actions = _canonical_nl2sql_payload(value)
        provider_payload = ProviderSQLPlanPayload.model_validate(payload)
        plan = SQLPlan.model_validate(provider_payload.model_dump(mode="python"))
        return NormalizedNl2SqlResponse(plan=plan, normalization_actions=actions)
    except Nl2SqlResponseNormalizationError:
        raise
    except ValueError as exc:
        raise Nl2SqlResponseNormalizationError("NL2SQL_RESPONSE_SCHEMA_INVALID") from exc


def normalize_nl2sql_response(value: Any) -> SQLPlan:
    """Normalize a strict Provider DTO; SQL Guard remains mandatory."""

    return normalize_nl2sql_response_with_metadata(value).plan
