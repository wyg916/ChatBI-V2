from __future__ import annotations

import asyncio
import inspect
import json
import re
import threading
import time
from dataclasses import dataclass
from importlib import import_module, metadata
from typing import Any, Callable, Mapping, Protocol


UPSTREAM_REVISION = "db580e952e544acf9f6c6c153da29dc67e9e40d7"
UPSTREAM_PACKAGE_VERSION = "0.8.1"
UPSTREAM_ARCHIVE_URL = (
    "https://github.com/eosphoros-ai/DB-GPT/archive/"
    f"{UPSTREAM_REVISION}.zip"
)
UPSTREAM_ARCHIVE_SHA256 = (
    "e225a2e222874adfb504e03f6a2d091729d8ecb2c874783fd4bcbc2c7c8ef31b"
)
_ALLOWED_ROUTES = frozenset({"HYBRID_ANALYSIS", "COMPLEX_ANALYSIS"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")


class DbgptRuntimeError(RuntimeError):
    """Base error for the fail-closed selected runtime boundary."""


class DbgptRuntimeUnavailable(DbgptRuntimeError):
    pass


class DbgptRuntimeProvenanceError(DbgptRuntimeError):
    pass


class DbgptRuntimePolicyError(DbgptRuntimeError):
    pass


class DbgptRuntimeCancelled(DbgptRuntimeError):
    pass


class DbgptRuntimeTimeout(DbgptRuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeRequest:
    question: str
    route: str
    trace_id: str
    max_steps: int = 8
    max_tool_calls: int = 12

    def safe_payload(self) -> dict[str, Any]:
        normalized_question = self.question.strip()
        if not normalized_question or len(normalized_question) > 4_000:
            raise DbgptRuntimePolicyError("question must contain 1..4000 characters")
        if self.route not in _ALLOWED_ROUTES:
            raise DbgptRuntimePolicyError("DB-GPT runtime is limited to hybrid/complex analysis")
        if not _IDENTIFIER.fullmatch(self.trace_id):
            raise DbgptRuntimePolicyError("trace_id has an unsafe shape")
        if not 1 <= self.max_steps <= 8 or not 1 <= self.max_tool_calls <= 12:
            raise DbgptRuntimePolicyError("agent budget exceeds the frozen ceiling")
        return {
            "route": self.route,
            "trace_id": self.trace_id,
            "max_steps": self.max_steps,
            "max_tool_calls": self.max_tool_calls,
        }


@dataclass(frozen=True)
class RuntimeControl:
    cancellation_event: threading.Event
    deadline_monotonic: float

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline_monotonic - time.monotonic())

    def checkpoint(self) -> None:
        if self.cancellation_event.is_set():
            raise DbgptRuntimeCancelled("DB-GPT workflow was cancelled")
        if self.remaining_seconds <= 0:
            raise DbgptRuntimeTimeout("DB-GPT workflow exceeded its deadline")


@dataclass(frozen=True)
class DbgptRuntimeResult:
    output: Any
    upstream_revision: str
    upstream_package_version: str
    upstream_install_source: str
    runtime_calls: int
    total_runtime_calls: int
    trace_stages: tuple[str, ...]
    awel_acknowledgement: Mapping[str, Any]


@dataclass(frozen=True)
class _LoadedRuntime:
    dag_type: type
    map_operator_type: type
    package_version: str
    revision: str
    install_source: str


class RuntimeLoader(Protocol):
    def __call__(self) -> _LoadedRuntime: ...


def _load_selected_runtime() -> _LoadedRuntime:
    try:
        distribution = metadata.distribution("dbgpt")
        package_version = distribution.version
    except metadata.PackageNotFoundError as exc:
        raise DbgptRuntimeUnavailable("pinned DB-GPT dependency is not installed") from exc
    if package_version != UPSTREAM_PACKAGE_VERSION:
        raise DbgptRuntimeProvenanceError(
            f"unexpected DB-GPT package version: {package_version}"
        )

    direct_url_text = distribution.read_text("direct_url.json")
    if not direct_url_text:
        raise DbgptRuntimeProvenanceError("DB-GPT direct_url provenance is unavailable")
    try:
        direct_url = json.loads(direct_url_text)
        revision, install_source = _validate_direct_url(direct_url)
    except (TypeError, ValueError) as exc:
        raise DbgptRuntimeProvenanceError("DB-GPT direct_url provenance is invalid") from exc

    try:
        awel = import_module("dbgpt.core.awel")
        dag_type = awel.DAG
        map_operator_type = awel.MapOperator
    except (ImportError, AttributeError) as exc:
        raise DbgptRuntimeUnavailable("DB-GPT AWEL import closure is unavailable") from exc
    return _LoadedRuntime(
        dag_type=dag_type,
        map_operator_type=map_operator_type,
        package_version=package_version,
        revision=revision,
        install_source=install_source,
    )


def _validate_direct_url(direct_url: Mapping[str, Any]) -> tuple[str, str]:
    vcs_info = direct_url.get("vcs_info") or {}
    if vcs_info:
        revision = str(vcs_info.get("commit_id") or "").lower()
        requested_revision = str(vcs_info.get("requested_revision") or "").lower()
        if revision != UPSTREAM_REVISION or requested_revision != UPSTREAM_REVISION:
            raise DbgptRuntimeProvenanceError(
                "DB-GPT commit does not match the selected revision"
            )
        return revision, "git"

    archive_info = direct_url.get("archive_info") or {}
    hashes = archive_info.get("hashes") or {}
    hash_value = str(
        hashes.get("sha256")
        or str(archive_info.get("hash") or "").removeprefix("sha256=")
    ).lower()
    url = str(direct_url.get("url") or "")
    subdirectory = str(direct_url.get("subdirectory") or "")
    if (
        url != UPSTREAM_ARCHIVE_URL
        or subdirectory != "packages/dbgpt-core"
        or hash_value != UPSTREAM_ARCHIVE_SHA256
    ):
        raise DbgptRuntimeProvenanceError(
            "DB-GPT archive URL, subdirectory, or SHA-256 is unselected"
        )
    return UPSTREAM_REVISION, "verified-archive"


class DbgptAwelRuntime:
    """Invoke the pinned AWEL engine while all privileged work stays in ChatBI."""

    def __init__(self, *, loader: RuntimeLoader = _load_selected_runtime) -> None:
        self._loader = loader
        self._counter_lock = threading.Lock()
        self._total_runtime_calls = 0

    @property
    def total_runtime_calls(self) -> int:
        with self._counter_lock:
            return self._total_runtime_calls

    def _record_runtime_call(self) -> int:
        with self._counter_lock:
            self._total_runtime_calls += 1
            return self._total_runtime_calls

    def run(
        self,
        request: RuntimeRequest,
        callback: Callable[[RuntimeControl], Any],
        *,
        cancellation_event: threading.Event | None = None,
        deadline_monotonic: float | None = None,
        timeout_seconds: float = 30.0,
    ) -> DbgptRuntimeResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.run_async(
                    request,
                    callback,
                    cancellation_event=cancellation_event,
                    deadline_monotonic=deadline_monotonic,
                    timeout_seconds=timeout_seconds,
                )
            )
        raise DbgptRuntimePolicyError("use run_async() from an active event loop")

    async def run_async(
        self,
        request: RuntimeRequest,
        callback: Callable[[RuntimeControl], Any],
        *,
        cancellation_event: threading.Event | None = None,
        deadline_monotonic: float | None = None,
        timeout_seconds: float = 30.0,
    ) -> DbgptRuntimeResult:
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise DbgptRuntimePolicyError("timeout must be within 0..30 seconds")
        safe_payload = request.safe_payload()
        upstream = self._loader()
        if upstream.revision != UPSTREAM_REVISION:
            raise DbgptRuntimeProvenanceError("loader returned an unselected DB-GPT revision")

        caller_cancel = cancellation_event
        workflow_cancel = threading.Event()
        effective_deadline = min(
            deadline_monotonic or float("inf"),
            time.monotonic() + timeout_seconds,
        )
        control = RuntimeControl(workflow_cancel, effective_deadline)
        callback_output: dict[str, Any] = {}
        trace_stages = ["agent.runtime.start", "agent.runtime.dbgpt.awel.build"]

        async def invoke_chatbi(payload: Mapping[str, Any]) -> dict[str, Any]:
            if dict(payload) != safe_payload:
                raise DbgptRuntimePolicyError("AWEL mutated the controlled input payload")
            control.checkpoint()
            trace_stages.append("agent.runtime.callback.start")
            if inspect.iscoroutinefunction(callback):
                output = await callback(control)
            else:
                output = await asyncio.to_thread(callback, control)
                if inspect.isawaitable(output):
                    output = await output
            control.checkpoint()
            callback_output["value"] = output
            trace_stages.append("agent.runtime.callback.completed")
            return {
                "trace_id": request.trace_id,
                "route": request.route,
                "callback_status": "COMPLETED",
            }

        dag_id = f"chatbi-controlled-{request.trace_id}"
        with upstream.dag_type(dag_id):
            terminal = upstream.map_operator_type(
                map_function=invoke_chatbi,
                task_id="chatbi_controlled_callback",
            )

        trace_stages.append("agent.runtime.dbgpt.awel.call")
        call_task = asyncio.create_task(terminal.call(safe_payload))
        call_ordinal = self._record_runtime_call()
        try:
            while not call_task.done():
                if caller_cancel is not None and caller_cancel.is_set():
                    workflow_cancel.set()
                    call_task.cancel()
                    await _await_cancelled(call_task)
                    raise DbgptRuntimeCancelled("DB-GPT workflow was cancelled")
                if time.monotonic() >= effective_deadline:
                    workflow_cancel.set()
                    call_task.cancel()
                    await _await_cancelled(call_task)
                    raise DbgptRuntimeTimeout("DB-GPT workflow exceeded its deadline")
                await asyncio.sleep(min(0.01, control.remaining_seconds))
            acknowledgement = await call_task
        except BaseException:
            workflow_cancel.set()
            if not call_task.done():
                call_task.cancel()
                await _await_cancelled(call_task)
            raise

        if "value" not in callback_output:
            raise DbgptRuntimeError("AWEL completed without invoking the ChatBI callback")
        if not isinstance(acknowledgement, Mapping) or acknowledgement.get(
            "callback_status"
        ) != "COMPLETED":
            raise DbgptRuntimeError("AWEL returned an invalid acknowledgement")
        trace_stages.append("agent.runtime.completed")
        return DbgptRuntimeResult(
            output=callback_output["value"],
            upstream_revision=upstream.revision,
            upstream_package_version=upstream.package_version,
            upstream_install_source=upstream.install_source,
            runtime_calls=1,
            total_runtime_calls=call_ordinal,
            trace_stages=tuple(trace_stages),
            awel_acknowledgement=dict(acknowledgement),
        )


async def _await_cancelled(task: asyncio.Task[Any]) -> None:
    try:
        await task
    except (asyncio.CancelledError, DbgptRuntimeCancelled, DbgptRuntimeTimeout):
        pass
