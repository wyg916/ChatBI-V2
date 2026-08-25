from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from app.query.contracts import SQLPlan


class Nl2SqlResponseNormalizationError(ValueError):
    """Unknown model output remains rejected before SQL Guard or execution."""


_FENCE = re.compile(r"\A```(?:json)?\s*(.*?)\s*```\Z", re.IGNORECASE | re.DOTALL)
_WRAPPER_KEYS = ("sql_plan", "plan", "result", "data")
_MAX_RESPONSE_CHARS = 200_000


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


def canonical_nl2sql_payload(value: Any) -> dict[str, Any]:
    decoded = _decode_text(value) if isinstance(value, str) else value
    if not isinstance(decoded, Mapping):
        raise Nl2SqlResponseNormalizationError("NL2SQL_RESPONSE_OBJECT_REQUIRED")
    payload = dict(decoded)
    matching_wrappers = [key for key in _WRAPPER_KEYS if key in payload]
    if matching_wrappers and not {"generated_sql", "intent"}.issubset(payload):
        if len(matching_wrappers) != 1 or len(payload) != 1:
            raise Nl2SqlResponseNormalizationError("NL2SQL_RESPONSE_WRAPPER_AMBIGUOUS")
        wrapped = payload[matching_wrappers[0]]
        if isinstance(wrapped, str):
            wrapped = _decode_text(wrapped)
        if not isinstance(wrapped, Mapping):
            raise Nl2SqlResponseNormalizationError("NL2SQL_RESPONSE_WRAPPED_OBJECT_REQUIRED")
        payload = dict(wrapped)
    return payload


def normalize_nl2sql_response(value: Any) -> SQLPlan:
    """Normalize syntax only; SQLPlan validation and SQL Guard remain mandatory."""

    try:
        return SQLPlan.model_validate(canonical_nl2sql_payload(value))
    except Nl2SqlResponseNormalizationError:
        raise
    except ValueError as exc:
        raise Nl2SqlResponseNormalizationError("NL2SQL_RESPONSE_SCHEMA_INVALID") from exc
