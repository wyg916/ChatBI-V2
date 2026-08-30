from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import replace
from typing import Any, Callable, Mapping
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from .contracts import SandboxArtifact, SandboxLimits, SandboxResult, SandboxStatus
from .guard import PythonCodeGuard, SandboxPolicyViolation


PROTOCOL_VERSION = 1
MAX_HTTP_BODY_BYTES = 1024 * 1024
MAX_HTTP_RESPONSE_BYTES = 512 * 1024
CANCEL_CONFIRMATION_TIMEOUT_SECONDS = 10.0
NETWORK_CONTROL_POLL_SECONDS = 0.01
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")


def _cleanup_budget(remaining_seconds: float) -> float:
    """Reserve cancel confirmation time without starving short executions."""

    return min(CANCEL_CONFIRMATION_TIMEOUT_SECONDS, remaining_seconds / 4.0)


def _cleanup_deadline(hard_deadline: float, now: float | None = None) -> float:
    return min(
        hard_deadline,
        (time.monotonic() if now is None else now)
        + CANCEL_CONFIRMATION_TIMEOUT_SECONDS,
    )


def _cancel_unconfirmed_result(started: float) -> SandboxResult:
    return _client_result(
        SandboxStatus.FAILED,
        started,
        ("python.controller.cancel_unconfirmed",),
        error_code="SANDBOX_CONTROLLER_CANCEL_UNCONFIRMED",
    )


class SandboxControllerError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class _ControllerCallCancelled(SandboxControllerError):
    pass


class _ControllerCallTimeout(SandboxControllerError):
    pass


ControllerTransport = Callable[
    [str, str, Mapping[str, Any] | None, float], Mapping[str, Any]
]


class SandboxControllerClient:
    """Fixed, fail-closed Backend client for the isolated Docker controller."""

    def __init__(
        self,
        base_url: str,
        *,
        limits: SandboxLimits | None = None,
        transport: ControllerTransport | None = None,
        poll_interval: float = 0.02,
    ) -> None:
        self.base_url = _validate_controller_url(base_url)
        self.limits = limits or SandboxLimits()
        self.guard = PythonCodeGuard(self.limits)
        self._transport = transport
        self._poll_interval = max(0.01, min(poll_interval, 0.1))

    def execute(
        self,
        code: str,
        datasets: Mapping[str, Any],
        *,
        cancellation_event: threading.Event | None = None,
        deadline_monotonic: float | None = None,
    ) -> SandboxResult:
        started = time.monotonic()
        try:
            self.guard.validate(code, datasets)
        except SandboxPolicyViolation as exc:
            return _client_result(
                SandboxStatus.REFUSED,
                started,
                ("python.controller.guard.refused",),
                error_code=exc.code,
            )
        if cancellation_event is not None and cancellation_event.is_set():
            return _client_result(
                SandboxStatus.CANCELLED,
                started,
                ("python.controller.cancelled",),
                error_code="SANDBOX_CANCELLED",
            )

        hard_deadline = min(
            deadline_monotonic or float("inf"),
            started + self.limits.timeout_seconds,
        )
        remaining = hard_deadline - time.monotonic()
        if remaining <= 0:
            return _client_result(
                SandboxStatus.TIMEOUT,
                started,
                ("python.controller.timeout",),
                error_code="SANDBOX_TIMEOUT",
            )
        # Reserve a portion of the end-to-end deadline before a job can be
        # admitted.  The normal cleanup window is ten seconds, but sandbox
        # calls are often much shorter, so scale the reservation instead of
        # making a short timeout unable to submit any useful work.
        execution_deadline = hard_deadline - _cleanup_budget(remaining)
        remaining = execution_deadline - time.monotonic()
        if remaining <= 0:
            return _client_result(
                SandboxStatus.TIMEOUT,
                started,
                ("python.controller.timeout",),
                error_code="SANDBOX_TIMEOUT",
            )
        payload = {
            "protocol_version": PROTOCOL_VERSION,
            "code": code,
            "datasets": datasets,
            "timeout_ms": max(1, min(15_000, int(remaining * 1000))),
        }
        # The client owns the fixed 32-hex identity before submission.  A lost
        # acknowledgement can therefore still be cancelled idempotently.
        job_id = uuid4().hex
        try:
            cancel_reason: SandboxStatus | None = None
            cleanup_deadline = float("inf")
            cancellation_sent = False
            try:
                submission_remaining = execution_deadline - time.monotonic()
                if submission_remaining <= 0:
                    return _client_result(
                        SandboxStatus.TIMEOUT,
                        started,
                        ("python.controller.timeout",),
                        error_code="SANDBOX_TIMEOUT",
                    )
                payload["timeout_ms"] = max(
                    1, min(15_000, int(submission_remaining * 1000))
                )
                submitted = self._call_transport(
                    "PUT",
                    f"/v1/jobs/{job_id}",
                    payload,
                    min(2.0, submission_remaining),
                    cancellation_event=cancellation_event,
                    deadline_monotonic=execution_deadline,
                )
            except _ControllerCallCancelled:
                submitted = None
                cancel_reason = SandboxStatus.CANCELLED
                cleanup_deadline = _cleanup_deadline(hard_deadline)
            except _ControllerCallTimeout:
                submitted = None
                cancel_reason = SandboxStatus.TIMEOUT
                cleanup_deadline = _cleanup_deadline(hard_deadline)
            if submitted is not None and (
                submitted.get("protocol_version") != PROTOCOL_VERSION
                or submitted.get("job_id") != job_id
                or submitted.get("state") not in {"RUNNING", "COMPLETED"}
            ):
                raise SandboxControllerError("SANDBOX_CONTROLLER_INVALID_RESPONSE")

            while True:
                now = time.monotonic()
                if cancel_reason is None:
                    if cancellation_event is not None and cancellation_event.is_set():
                        cancel_reason = SandboxStatus.CANCELLED
                    elif now >= execution_deadline:
                        cancel_reason = SandboxStatus.TIMEOUT
                    if cancel_reason is not None:
                        # Docker Desktop can report container deletion before
                        # the controller thread has finished its final inspect
                        # and result publication.  Keep this bounded, but give
                        # the fixed controller enough time to return signed
                        # destruction proof instead of producing a timing-only
                        # cancel_unconfirmed failure.
                        cleanup_deadline = _cleanup_deadline(hard_deadline, now)
                if cancel_reason is not None and not cancellation_sent:
                    try:
                        cancelled_job = self._call_transport(
                            "DELETE",
                            f"/v1/jobs/{job_id}",
                            None,
                            1.0,
                            cancellation_event=None,
                            deadline_monotonic=cleanup_deadline,
                        )
                    except SandboxControllerError as exc:
                        if exc.error_code == "SANDBOX_JOB_NOT_FOUND":
                            return _client_result(
                                cancel_reason,
                                started,
                                ("python.controller.job_absent",),
                                error_code=(
                                    "SANDBOX_CANCELLED"
                                    if cancel_reason is SandboxStatus.CANCELLED
                                    else "SANDBOX_TIMEOUT"
                                ),
                            )
                        if isinstance(exc, _ControllerCallTimeout):
                            return _cancel_unconfirmed_result(started)
                        raise
                    cancellation_sent = True
                    if cancelled_job.get("state") == "ABSENT":
                        return _client_result(
                            cancel_reason,
                            started,
                            ("python.controller.job_absent",),
                            error_code=(
                                "SANDBOX_CANCELLED"
                                if cancel_reason is SandboxStatus.CANCELLED
                                else "SANDBOX_TIMEOUT"
                            ),
                        )
                    if cancelled_job.get("state") == "COMPLETED":
                        result = _decode_controller_result(cancelled_job)
                        result = _apply_cancel_terminal(result, cancel_reason)
                        return replace(
                            result,
                            trace_stages=("python.controller.call",) + result.trace_stages,
                            security={**result.security, "controller_protocol": PROTOCOL_VERSION},
                        )
                if now >= cleanup_deadline:
                    return _cancel_unconfirmed_result(started)

                try:
                    response = self._call_transport(
                        "GET",
                        f"/v1/jobs/{job_id}",
                        None,
                        min(1.0, max(0.001, execution_deadline - now))
                        if cancel_reason is None
                        else 1.0,
                        cancellation_event=(
                            cancellation_event if cancel_reason is None else None
                        ),
                        deadline_monotonic=(
                            execution_deadline
                            if cancel_reason is None
                            else cleanup_deadline
                        ),
                    )
                except _ControllerCallCancelled:
                    cancel_reason = SandboxStatus.CANCELLED
                    cleanup_deadline = _cleanup_deadline(hard_deadline)
                    continue
                except _ControllerCallTimeout:
                    if cancel_reason is not None:
                        return _cancel_unconfirmed_result(started)
                    cancel_reason = SandboxStatus.TIMEOUT
                    cleanup_deadline = _cleanup_deadline(hard_deadline)
                    continue
                if response.get("state") == "COMPLETED":
                    result = _decode_controller_result(response)
                    try:
                        self._call_transport(
                            "DELETE",
                            f"/v1/jobs/{job_id}",
                            None,
                            1.0,
                            cancellation_event=None,
                            deadline_monotonic=min(
                                hard_deadline, time.monotonic() + 1.0
                            ),
                        )
                    except Exception:
                        pass
                    # Decoding and best-effort completion cleanup can both
                    # cross the execution boundary.  Terminal state is
                    # selected last, with caller cancellation taking priority.
                    if cancellation_event is not None and cancellation_event.is_set():
                        cancel_reason = SandboxStatus.CANCELLED
                    elif time.monotonic() >= execution_deadline:
                        cancel_reason = SandboxStatus.TIMEOUT
                    if cancel_reason is not None:
                        result = _apply_cancel_terminal(result, cancel_reason)
                    return replace(
                        result,
                        trace_stages=("python.controller.call",) + result.trace_stages,
                        security={**result.security, "controller_protocol": PROTOCOL_VERSION},
                    )
                if response.get("state") != "RUNNING":
                    raise SandboxControllerError("SANDBOX_CONTROLLER_INVALID_RESPONSE")
                next_deadline = (
                    cleanup_deadline
                    if cancel_reason is not None
                    else execution_deadline
                )
                time.sleep(
                    min(self._poll_interval, max(0.0, next_deadline - time.monotonic()))
                )
        except Exception as exc:
            if job_id:
                try:
                    self._call_transport(
                        "DELETE",
                        f"/v1/jobs/{job_id}",
                        None,
                        1.0,
                        cancellation_event=None,
                        deadline_monotonic=min(hard_deadline, time.monotonic() + 1.0),
                    )
                except Exception:
                    pass
            error_code = getattr(exc, "error_code", "SANDBOX_CONTROLLER_UNAVAILABLE")
            return _client_result(
                SandboxStatus.UNAVAILABLE,
                started,
                ("python.controller.unavailable",),
                error_code=error_code,
            )

    def _call_transport(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None,
        timeout: float,
        *,
        cancellation_event: threading.Event | None,
        deadline_monotonic: float,
    ) -> Mapping[str, Any]:
        if cancellation_event is not None and cancellation_event.is_set():
            raise _ControllerCallCancelled("SANDBOX_CONTROLLER_CALL_CANCELLED")
        if time.monotonic() >= deadline_monotonic:
            raise _ControllerCallTimeout("SANDBOX_CONTROLLER_CALL_TIMEOUT")
        if self._transport is None:
            return self._http_json(
                method,
                path,
                payload,
                timeout,
                cancellation_event=cancellation_event,
                deadline_monotonic=deadline_monotonic,
            )
        if not getattr(self._transport, "_chatbi_deadline_aware", False):
            raise SandboxControllerError(
                "SANDBOX_CONTROLLER_TRANSPORT_NOT_DEADLINE_AWARE"
            )
        response = self._transport(method, path, payload, timeout)
        if cancellation_event is not None and cancellation_event.is_set():
            raise _ControllerCallCancelled("SANDBOX_CONTROLLER_CALL_CANCELLED")
        if time.monotonic() >= deadline_monotonic:
            raise _ControllerCallTimeout("SANDBOX_CONTROLLER_CALL_TIMEOUT")
        return response

    def _http_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None,
        timeout: float,
        *,
        cancellation_event: threading.Event | None,
        deadline_monotonic: float,
    ) -> Mapping[str, Any]:
        body = None
        if payload is not None:
            body = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
            if len(body) > MAX_HTTP_BODY_BYTES:
                raise SandboxControllerError("SANDBOX_CONTROLLER_REQUEST_LIMIT")
        effective_deadline = min(
            deadline_monotonic,
            time.monotonic() + max(0.001, timeout),
        )
        stop_event = threading.Event()
        done = threading.Event()
        outcome: dict[str, Any] = {}
        client = httpx.Client(
            timeout=max(0.1, timeout),
            follow_redirects=False,
            trust_env=False,
        )

        def checkpoint() -> None:
            if stop_event.is_set() or (
                cancellation_event is not None and cancellation_event.is_set()
            ):
                raise _ControllerCallCancelled("SANDBOX_CONTROLLER_CALL_CANCELLED")
            if time.monotonic() >= effective_deadline:
                raise _ControllerCallTimeout("SANDBOX_CONTROLLER_CALL_TIMEOUT")

        def request_worker() -> None:
            try:
                checkpoint()
                with client.stream(
                    method,
                    f"{self.base_url}{path}",
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-ChatBI-Sandbox-Protocol": str(PROTOCOL_VERSION),
                    },
                ) as response:
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        checkpoint()
                        raw.extend(chunk)
                        if len(raw) > MAX_HTTP_RESPONSE_BYTES:
                            raise SandboxControllerError(
                                "SANDBOX_CONTROLLER_RESPONSE_LIMIT"
                            )
                    checkpoint()
                    outcome["status_code"] = response.status_code
                    outcome["raw"] = bytes(raw)
            except BaseException as exc:
                outcome["error"] = exc
            finally:
                done.set()

        worker = threading.Thread(
            target=request_worker,
            name="chatbi-sandbox-controller-http",
            daemon=True,
        )
        worker.start()
        cancelled = False
        timed_out = False
        while not done.is_set():
            if cancellation_event is not None and cancellation_event.is_set():
                cancelled = True
                break
            now = time.monotonic()
            if now >= effective_deadline:
                timed_out = True
                break
            done.wait(min(NETWORK_CONTROL_POLL_SECONDS, effective_deadline - now))
        if not cancelled and cancellation_event is not None and cancellation_event.is_set():
            cancelled = True
        if not cancelled and time.monotonic() >= effective_deadline:
            timed_out = True
        if cancelled or timed_out:
            stop_event.set()
            threading.Thread(
                target=client.close,
                name="chatbi-sandbox-controller-http-close",
                daemon=True,
            ).start()
            if cancelled:
                raise _ControllerCallCancelled("SANDBOX_CONTROLLER_CALL_CANCELLED")
            raise _ControllerCallTimeout("SANDBOX_CONTROLLER_CALL_TIMEOUT")
        worker.join()
        client.close()
        error = outcome.get("error")
        if error is not None:
            if isinstance(error, SandboxControllerError):
                raise error
            if isinstance(error, httpx.HTTPError):
                raise SandboxControllerError(
                    "SANDBOX_CONTROLLER_UNAVAILABLE"
                ) from error
            raise error
        raw = bytes(outcome.get("raw") or b"")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise SandboxControllerError("SANDBOX_CONTROLLER_INVALID_RESPONSE") from exc
        if cancellation_event is not None and cancellation_event.is_set():
            raise _ControllerCallCancelled("SANDBOX_CONTROLLER_CALL_CANCELLED")
        if time.monotonic() >= effective_deadline:
            raise _ControllerCallTimeout("SANDBOX_CONTROLLER_CALL_TIMEOUT")
        if not isinstance(decoded, Mapping):
            raise SandboxControllerError("SANDBOX_CONTROLLER_INVALID_RESPONSE")
        if int(outcome.get("status_code") or 0) >= 400:
            raise SandboxControllerError(
                str(decoded.get("error_code") or "SANDBOX_CONTROLLER_HTTP_ERROR")
            )
        return decoded


def _validate_controller_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query:
        raise ValueError("sandbox controller URL is not allowed")
    if parsed.path not in {"", "/"} or parsed.fragment:
        raise ValueError("sandbox controller URL must not contain a path")
    if parsed.hostname == "sandbox-controller":
        if parsed.port not in {None, 8765}:
            raise ValueError("sandbox controller service port is fixed")
    elif parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("sandbox controller host is not allowlisted")
    if parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port is None:
        raise ValueError("loopback sandbox controller requires an explicit port")
    return value.strip().rstrip("/")


def _decode_controller_result(response: Mapping[str, Any]) -> SandboxResult:
    if response.get("protocol_version") != PROTOCOL_VERSION:
        raise SandboxControllerError("SANDBOX_CONTROLLER_INVALID_RESPONSE")
    payload = response.get("result")
    if not isinstance(payload, Mapping):
        raise SandboxControllerError("SANDBOX_CONTROLLER_INVALID_RESPONSE")
    try:
        artifacts = tuple(
            SandboxArtifact(
                name=str(item["name"]),
                media_type=str(item["media_type"]),
                size_bytes=int(item["size_bytes"]),
                sha256=str(item["sha256"]),
                content_base64=str(item["content_base64"]),
            )
            for item in payload.get("artifacts") or []
        )
        result = SandboxResult(
            status=SandboxStatus(str(payload["status"])),
            output=payload.get("output"),
            stdout=str(payload.get("stdout") or ""),
            stderr=str(payload.get("stderr") or ""),
            stdout_truncated=bool(payload.get("stdout_truncated")),
            stderr_truncated=bool(payload.get("stderr_truncated")),
            artifacts=artifacts,
            error_code=(str(payload["error_code"]) if payload.get("error_code") else None),
            duration_ms=int(payload.get("duration_ms") or 0),
            container_id=(str(payload["container_id"]) if payload.get("container_id") else None),
            container_destroyed=bool(payload.get("container_destroyed")),
            runtime_verified=bool(payload.get("runtime_verified")),
            trace_stages=tuple(str(item) for item in payload.get("trace_stages") or []),
            security=dict(payload.get("security") or {}),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SandboxControllerError("SANDBOX_CONTROLLER_INVALID_RESPONSE") from exc
    if result.status is SandboxStatus.SUCCEEDED and (
        not result.runtime_verified or not result.container_destroyed
    ):
        raise SandboxControllerError("SANDBOX_CONTROLLER_INVALID_RESPONSE")
    return result


def _apply_cancel_terminal(
    result: SandboxResult,
    cancel_reason: SandboxStatus,
) -> SandboxResult:
    """Publish no worker body once the caller has selected cancel or timeout."""

    if cancel_reason not in {SandboxStatus.CANCELLED, SandboxStatus.TIMEOUT}:
        raise SandboxControllerError("SANDBOX_CONTROLLER_INVALID_RESPONSE")
    if not result.container_destroyed:
        return replace(
            result,
            status=SandboxStatus.FAILED,
            output=None,
            stdout="",
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            artifacts=(),
            error_code="SANDBOX_CONTROLLER_CANCEL_UNCONFIRMED",
            runtime_verified=False,
        )
    return replace(
        result,
        status=cancel_reason,
        output=None,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        artifacts=(),
        error_code=(
            "SANDBOX_CANCELLED"
            if cancel_reason is SandboxStatus.CANCELLED
            else "SANDBOX_TIMEOUT"
        ),
        runtime_verified=False,
    )


def _client_result(
    status: SandboxStatus,
    started: float,
    trace: tuple[str, ...],
    *,
    error_code: str,
) -> SandboxResult:
    return SandboxResult(
        status=status,
        error_code=error_code,
        duration_ms=max(0, round((time.monotonic() - started) * 1000)),
        runtime_verified=False,
        trace_stages=trace,
        security={"controller_protocol": PROTOCOL_VERSION},
    )
