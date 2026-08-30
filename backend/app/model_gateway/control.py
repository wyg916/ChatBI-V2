from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any


_request_cancellation: ContextVar[Any | None] = ContextVar(
    "model_request_cancellation", default=None,
)


@contextmanager
def bind_model_request_control(cancellation_event: Any | None) -> Iterator[None]:
    """Propagate the current request deadline without adding it to model prompts."""

    token = _request_cancellation.set(cancellation_event)
    try:
        yield
    finally:
        _request_cancellation.reset(token)


def resolve_model_request_control(explicit: Any | None) -> Any | None:
    return explicit if explicit is not None else _request_cancellation.get()


def remaining_seconds(cancellation_event: Any | None) -> float | None:
    if cancellation_event is None:
        return None
    value = getattr(cancellation_event, "remaining_seconds", None)
    if callable(value):
        value = value()
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


__all__ = [
    "bind_model_request_control",
    "remaining_seconds",
    "resolve_model_request_control",
]
