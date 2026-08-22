from __future__ import annotations

import importlib
from dataclasses import dataclass
from threading import Event
from typing import Any, Mapping


class PandasAISelectedRuntimeUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class PandasAIExecutionRequest:
    code: str
    environment: Mapping[str, Any]
    trace_id: str
    workspace_id: str
    timeout_ms: int = 30_000
    max_output_bytes: int = 1_048_576
    cancellation_event: Event | None = None
    deadline_monotonic: float | None = None


@dataclass(frozen=True)
class PandasAIExecutionResponse:
    output: Mapping[str, Any]
    upstream_runtime_calls: int
    upstream_commit: str
    upstream_blob: str
    upstream_sha256: str


def execute_selected_pandasai_runtime(
    request: PandasAIExecutionRequest,
    hardened_executor: Any,
) -> PandasAIExecutionResponse:
    """Execute through the hash-locked upstream ``Sandbox.execute`` method."""
    try:
        selected = importlib.import_module("pandasai_selected_runtime")
    except ImportError as exc:
        raise PandasAISelectedRuntimeUnavailable(
            "Install packages/pandasai-selected-runtime before enabling complex file analysis"
        ) from exc
    provenance = selected.upstream_provenance()
    sandbox = selected.SelectedRuntimeSandbox(
        hardened_executor,
        trace_id=request.trace_id,
        workspace_id=request.workspace_id,
        timeout_ms=request.timeout_ms,
        max_output_bytes=request.max_output_bytes,
        cancellation_event=request.cancellation_event,
        deadline_monotonic=request.deadline_monotonic,
    )
    try:
        output = sandbox.execute(request.code, dict(request.environment))
    finally:
        sandbox.stop()
    return PandasAIExecutionResponse(
        output=dict(output),
        upstream_runtime_calls=1,
        upstream_commit=provenance["commit"],
        upstream_blob=provenance["git_blob"],
        upstream_sha256=provenance["sha256"],
    )
