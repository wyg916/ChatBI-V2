from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import replace
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .contracts import SandboxArtifact, SandboxLimits, SandboxResult, SandboxStatus
from .guard import PythonCodeGuard, SandboxPolicyViolation


PROTOCOL_VERSION = 1
MAX_HTTP_BODY_BYTES = 1024 * 1024
MAX_HTTP_RESPONSE_BYTES = 512 * 1024
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")


class SandboxControllerError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


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
        self._transport = transport or self._http_json
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

        effective_deadline = min(
            deadline_monotonic or float("inf"),
            started + self.limits.timeout_seconds,
        )
        remaining = effective_deadline - time.monotonic()
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
        job_id: str | None = None
        try:
            submitted = self._transport(
                "POST", "/v1/jobs", payload, min(2.0, remaining)
            )
            job_id = str(submitted.get("job_id") or "")
            if (
                submitted.get("protocol_version") != PROTOCOL_VERSION
                or not _JOB_ID.fullmatch(job_id)
                or submitted.get("state") != "RUNNING"
            ):
                raise SandboxControllerError("SANDBOX_CONTROLLER_INVALID_RESPONSE")

            cancel_reason: SandboxStatus | None = None
            cleanup_deadline = float("inf")
            cancellation_sent = False
            while True:
                now = time.monotonic()
                if cancel_reason is None:
                    if cancellation_event is not None and cancellation_event.is_set():
                        cancel_reason = SandboxStatus.CANCELLED
                    elif now >= effective_deadline:
                        cancel_reason = SandboxStatus.TIMEOUT
                    if cancel_reason is not None:
                        cleanup_deadline = now + 5.0
                if cancel_reason is not None and not cancellation_sent:
                    self._transport("DELETE", f"/v1/jobs/{job_id}", None, 1.0)
                    cancellation_sent = True
                if now >= cleanup_deadline:
                    return _client_result(
                        SandboxStatus.FAILED,
                        started,
                        ("python.controller.cancel_unconfirmed",),
                        error_code="SANDBOX_CONTROLLER_CANCEL_UNCONFIRMED",
                    )

                response = self._transport(
                    "GET",
                    f"/v1/jobs/{job_id}",
                    None,
                    min(1.0, max(0.1, effective_deadline - now))
                    if cancel_reason is None
                    else 1.0,
                )
                if response.get("state") == "COMPLETED":
                    result = _decode_controller_result(response)
                    try:
                        self._transport("DELETE", f"/v1/jobs/{job_id}", None, 1.0)
                    except Exception:
                        pass
                    if cancel_reason is SandboxStatus.TIMEOUT and result.status is SandboxStatus.CANCELLED:
                        result = replace(
                            result,
                            status=SandboxStatus.TIMEOUT,
                            error_code="SANDBOX_TIMEOUT",
                        )
                    return replace(
                        result,
                        trace_stages=("python.controller.call",) + result.trace_stages,
                        security={**result.security, "controller_protocol": PROTOCOL_VERSION},
                    )
                if response.get("state") != "RUNNING":
                    raise SandboxControllerError("SANDBOX_CONTROLLER_INVALID_RESPONSE")
                time.sleep(self._poll_interval)
        except Exception as exc:
            if job_id:
                try:
                    self._transport("DELETE", f"/v1/jobs/{job_id}", None, 1.0)
                except Exception:
                    pass
            error_code = getattr(exc, "error_code", "SANDBOX_CONTROLLER_UNAVAILABLE")
            return _client_result(
                SandboxStatus.UNAVAILABLE,
                started,
                ("python.controller.unavailable",),
                error_code=error_code,
            )

    def _http_json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None,
        timeout: float,
    ) -> Mapping[str, Any]:
        body = None
        if payload is not None:
            body = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
            if len(body) > MAX_HTTP_BODY_BYTES:
                raise SandboxControllerError("SANDBOX_CONTROLLER_REQUEST_LIMIT")
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Content-Type": "application/json",
                "X-ChatBI-Sandbox-Protocol": str(PROTOCOL_VERSION),
            },
        )
        try:
            with urlopen(request, timeout=max(0.1, timeout)) as response:
                raw = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read(4096).decode("utf-8"))
                error_code = str(detail.get("error_code") or "")
            except Exception:
                error_code = ""
            raise SandboxControllerError(
                error_code or "SANDBOX_CONTROLLER_HTTP_ERROR"
            ) from exc
        except URLError as exc:
            raise SandboxControllerError("SANDBOX_CONTROLLER_UNAVAILABLE") from exc
        if len(raw) > MAX_HTTP_RESPONSE_BYTES:
            raise SandboxControllerError("SANDBOX_CONTROLLER_RESPONSE_LIMIT")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise SandboxControllerError("SANDBOX_CONTROLLER_INVALID_RESPONSE") from exc
        if not isinstance(decoded, Mapping):
            raise SandboxControllerError("SANDBOX_CONTROLLER_INVALID_RESPONSE")
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
