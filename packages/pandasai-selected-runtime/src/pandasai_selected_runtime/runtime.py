from __future__ import annotations

import importlib.util
import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from threading import Event
from typing import Any, Mapping, Protocol, runtime_checkable


_ROOT = Path(__file__).resolve().parent
_UPSTREAM_FILE = _ROOT / "_upstream" / "pandasai" / "sandbox" / "sandbox.py"
_PROVENANCE_FILE = _ROOT / "provenance.json"


def _verified_provenance() -> dict[str, Any]:
    provenance = json.loads(_PROVENANCE_FILE.read_text(encoding="utf-8"))
    # Git may materialize text with CRLF on Windows. The frozen provenance is
    # bound to the canonical LF bytes, while every non-newline content change
    # must still fail closed.
    source = _UPSTREAM_FILE.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(source).hexdigest() != provenance.get("sha256"):
        raise RuntimeError("PANDASAI_SELECTED_SOURCE_SHA256_MISMATCH")
    if len(source) != provenance.get("size_bytes"):
        raise RuntimeError("PANDASAI_SELECTED_SOURCE_SIZE_MISMATCH")
    if provenance.get("selected_path") != "pandasai/sandbox/sandbox.py":
        raise RuntimeError("PANDASAI_SELECTED_SOURCE_PATH_MISMATCH")
    return provenance


def _load_upstream_sandbox():
    spec = importlib.util.spec_from_file_location(
        "chatbi_pandasai_selected_upstream_sandbox", _UPSTREAM_FILE
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("PANDASAI_SELECTED_SOURCE_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Sandbox


_PROVENANCE = _verified_provenance()
UpstreamSandbox = _load_upstream_sandbox()


@dataclass(frozen=True)
class HardenedSandboxRequest:
    code: str
    environment: Mapping[str, Any]
    trace_id: str
    workspace_id: str
    timeout_ms: int = 30_000
    max_output_bytes: int = 1_048_576


@runtime_checkable
class HardenedSandboxExecutor(Protocol):
    """Late-bound contract implemented by the hardened sandbox owner."""

    def execute(
        self,
        code: str,
        datasets: Mapping[str, Any],
        *,
        cancellation_event: Event | None = None,
        deadline_monotonic: float | None = None,
    ) -> Any: ...


class SelectedRuntimeSandbox(UpstreamSandbox):
    """PandasAI's exact Sandbox.execute with execution delegated to ChatBI.

    This class intentionally does not override ``execute``. The inherited,
    hash-locked PandasAI community implementation owns the real runtime call;
    only ``_exec_code`` crosses the hardened sandbox contract.
    """

    def __init__(
        self,
        executor: HardenedSandboxExecutor,
        *,
        trace_id: str,
        workspace_id: str,
        timeout_ms: int = 30_000,
        max_output_bytes: int = 1_048_576,
        cancellation_event: Event | None = None,
        deadline_monotonic: float | None = None,
    ) -> None:
        super().__init__()
        self._executor = executor
        self._trace_id = trace_id
        self._workspace_id = workspace_id
        self._timeout_ms = timeout_ms
        self._max_output_bytes = max_output_bytes
        self._cancellation_event = cancellation_event
        self._deadline_monotonic = deadline_monotonic

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    def _exec_code(self, code: str, environment: dict) -> dict:
        request = HardenedSandboxRequest(
            code=code,
            environment=dict(environment),
            trace_id=self._trace_id,
            workspace_id=self._workspace_id,
            timeout_ms=self._timeout_ms,
            max_output_bytes=self._max_output_bytes,
        )
        response = self._executor.execute(
            request.code,
            request.environment,
            cancellation_event=self._cancellation_event,
            deadline_monotonic=self._deadline_monotonic,
        )
        if is_dataclass(response):
            return asdict(response)
        if isinstance(response, Mapping):
            return dict(response)
        raise TypeError("HARDENED_SANDBOX_RESPONSE_NOT_MAPPING_OR_DATACLASS")


def upstream_provenance() -> dict[str, Any]:
    return dict(_PROVENANCE)
