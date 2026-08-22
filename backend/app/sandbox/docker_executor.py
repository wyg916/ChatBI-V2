from __future__ import annotations

import base64
import json
import os
import queue
import threading
import time
from dataclasses import asdict
from typing import Any, Callable, Mapping
from uuid import uuid4

from .contracts import (
    SandboxArtifact,
    SandboxLimits,
    SandboxResult,
    SandboxStatus,
)
from .guard import PythonCodeGuard, SandboxPolicyViolation
from .worker_spec import DockerWorkerSpec


class DockerSandboxExecutor:
    """Run guarded Python in a disposable, mountless Docker worker."""

    def __init__(
        self,
        *,
        limits: SandboxLimits | None = None,
        worker_spec: DockerWorkerSpec | None = None,
        client_factory: Callable[[], Any] | None = None,
        controller_url: str | None = None,
        controller_transport: Callable[..., Any] | None = None,
        poll_interval: float = 0.02,
    ) -> None:
        self.limits = limits or SandboxLimits()
        self.worker_spec = worker_spec or DockerWorkerSpec()
        self.guard = PythonCodeGuard(self.limits)
        self._client_factory = client_factory or _docker_client
        self._poll_interval = max(0.005, min(poll_interval, 0.1))
        self._controller_url = (
            controller_url
            if controller_url is not None
            else (
                os.getenv("CHATBI_SANDBOX_CONTROLLER_URL", "").strip()
                if client_factory is None
                else ""
            )
        )
        self._controller_transport = controller_transport

    def execute(
        self,
        code: str,
        datasets: Mapping[str, Any],
        *,
        cancellation_event: threading.Event | None = None,
        deadline_monotonic: float | None = None,
    ) -> SandboxResult:
        if self._controller_url:
            from .controller_client import SandboxControllerClient

            try:
                remote = SandboxControllerClient(
                    self._controller_url,
                    limits=self.limits,
                    transport=self._controller_transport,
                    poll_interval=self._poll_interval,
                )
            except ValueError:
                return SandboxResult(
                    status=SandboxStatus.UNAVAILABLE,
                    error_code="SANDBOX_CONTROLLER_URL_DENIED",
                    trace_stages=("python.controller.url_denied",),
                    security={"controller_protocol": 1},
                )
            return remote.execute(
                code,
                datasets,
                cancellation_event=cancellation_event,
                deadline_monotonic=deadline_monotonic,
            )
        started = time.monotonic()
        trace = ["python.guard.start"]
        try:
            guard = self.guard.validate(code, datasets)
        except SandboxPolicyViolation as exc:
            return self._result(
                SandboxStatus.REFUSED,
                started,
                trace + ["python.guard.refused"],
                error_code=exc.code,
            )
        trace.append("python.guard.passed")
        if cancellation_event is not None and cancellation_event.is_set():
            return self._result(
                SandboxStatus.CANCELLED,
                started,
                trace + ["python.cancelled"],
                error_code="SANDBOX_CANCELLED",
            )

        effective_deadline = min(
            deadline_monotonic or float("inf"),
            started + self.limits.timeout_seconds,
        )
        job_id = uuid4().hex
        command = ["tail", "-f", "/dev/null"]
        kwargs = self.worker_spec.create_kwargs(
            job_id=job_id, limits=self.limits, command=command
        )
        client = None
        try:
            self.worker_spec.assert_hardened(kwargs)
            client = self._client_factory()
            client.ping()
        except Exception:
            _close_client(client)
            return self._result(
                SandboxStatus.UNAVAILABLE,
                started,
                trace + ["python.runtime.unavailable"],
                error_code="SANDBOX_DOCKER_UNAVAILABLE",
            )

        container = None
        container_id = None
        result: SandboxResult | None = None
        destroy_error = False
        try:
            trace.append("python.container.create")
            container = client.containers.create(**kwargs)
            container_id = str(container.id)
            trace.append("python.container.created")
            container.start()
            trace.append("python.container.started")
            payload = {
                "code": code,
                "datasets": datasets,
                "limits": {
                    "max_output_bytes": self.limits.max_output_bytes,
                    "max_file_bytes": self.limits.max_file_bytes,
                    "max_files": self.limits.max_files,
                },
                "guard": asdict(guard),
            }
            encoded_request = base64.b64encode(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).decode("ascii")
            if len(encoded_request) > 1024 * 1024:
                raise ValueError("encoded sandbox request exceeds environment limit")
            trace.append("python.execute")
            output_queue: queue.Queue[Any] = queue.Queue(maxsize=1)

            def execute_worker() -> None:
                try:
                    output_queue.put(
                        container.exec_run(
                            [
                                "python",
                                "/opt/chatbi/sandbox_runner.py",
                            ],
                            demux=False,
                            environment=[f"SANDBOX_REQUEST_B64={encoded_request}"],
                        )
                    )
                except BaseException as exc:
                    output_queue.put(exc)

            worker = threading.Thread(
                target=execute_worker,
                name=f"chatbi-sandbox-{job_id}",
                daemon=True,
            )
            worker.start()
            while worker.is_alive():
                if cancellation_event is not None and cancellation_event.is_set():
                    _kill(container)
                    result = self._result(
                        SandboxStatus.CANCELLED,
                        started,
                        trace + ["python.cancelled"],
                        error_code="SANDBOX_CANCELLED",
                        container_id=container_id,
                    )
                    break
                if time.monotonic() >= effective_deadline:
                    _kill(container)
                    result = self._result(
                        SandboxStatus.TIMEOUT,
                        started,
                        trace + ["python.timeout"],
                        error_code="SANDBOX_TIMEOUT",
                        container_id=container_id,
                    )
                    break
                worker.join(timeout=self._poll_interval)
            if result is None:
                execution = output_queue.get_nowait()
                if isinstance(execution, BaseException):
                    raise execution
                exit_code = int(execution.exit_code)
                raw_output = bytes(execution.output or b"")
                if len(raw_output) > self.limits.max_output_bytes:
                    result = self._result(
                        SandboxStatus.FAILED,
                        started,
                        trace + ["python.output.rejected"],
                        error_code="SANDBOX_OUTPUT_LIMIT",
                        container_id=container_id,
                    )
                else:
                    result = self._decode_result(
                        raw_output,
                        exit_code=exit_code,
                        started=started,
                        trace=trace,
                        container_id=container_id,
                    )
        except Exception as exc:
            result = self._result(
                SandboxStatus.FAILED,
                started,
                trace + [f"python.runtime.failed.{type(exc).__name__}"],
                error_code="SANDBOX_RUNTIME_FAILED",
                container_id=container_id,
            )
        finally:
            if container is not None:
                destroy_error = not _destroy_synchronously(client, container)
            _close_client(client)

        if result is None:
            result = self._result(
                SandboxStatus.FAILED,
                started,
                trace + ["python.runtime.failed"],
                error_code="SANDBOX_RUNTIME_FAILED",
                container_id=container_id,
            )
        if destroy_error:
            return self._result(
                SandboxStatus.FAILED,
                started,
                list(result.trace_stages) + ["python.container.destroy_failed"],
                error_code="SANDBOX_DESTROY_FAILED",
                container_id=container_id,
                container_destroyed=False,
            )
        return SandboxResult(
            **{
                **asdict(result),
                "status": result.status,
                "artifacts": result.artifacts,
                "trace_stages": tuple(result.trace_stages) + ("python.container.destroyed",),
                "container_destroyed": container is not None,
                "runtime_verified": result.status is SandboxStatus.SUCCEEDED,
            }
        )

    def _decode_result(
        self,
        raw_output: bytes,
        *,
        exit_code: int,
        started: float,
        trace: list[str],
        container_id: str,
    ) -> SandboxResult:
        try:
            payload = json.loads(raw_output.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return self._result(
                SandboxStatus.FAILED,
                started,
                trace + ["python.output.invalid"],
                error_code="SANDBOX_INVALID_OUTPUT",
                container_id=container_id,
            )
        if exit_code != 0 or payload.get("status") != "SUCCEEDED":
            return self._result(
                SandboxStatus.FAILED,
                started,
                trace + ["python.execute.failed"],
                error_code=str(payload.get("error_code") or "SANDBOX_CODE_FAILED"),
                stdout=str(payload.get("stdout") or ""),
                stderr=str(payload.get("stderr") or ""),
                stdout_truncated=bool(payload.get("stdout_truncated")),
                stderr_truncated=bool(payload.get("stderr_truncated")),
                container_id=container_id,
            )
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
        if len(artifacts) > self.limits.max_files or any(
            item.size_bytes > self.limits.max_file_bytes for item in artifacts
        ):
            return self._result(
                SandboxStatus.FAILED,
                started,
                trace + ["python.file.rejected"],
                error_code="SANDBOX_FILE_LIMIT",
                container_id=container_id,
            )
        return self._result(
            SandboxStatus.SUCCEEDED,
            started,
            trace + ["python.execute.completed"],
            output=payload.get("output"),
            stdout=str(payload.get("stdout") or ""),
            stderr=str(payload.get("stderr") or ""),
            stdout_truncated=bool(payload.get("stdout_truncated")),
            stderr_truncated=bool(payload.get("stderr_truncated")),
            artifacts=artifacts,
            container_id=container_id,
        )

    def _result(
        self,
        status: SandboxStatus,
        started: float,
        trace: list[str],
        *,
        output: Any = None,
        stdout: str = "",
        stderr: str = "",
        stdout_truncated: bool = False,
        stderr_truncated: bool = False,
        artifacts: tuple[SandboxArtifact, ...] = (),
        error_code: str | None = None,
        container_id: str | None = None,
        container_destroyed: bool = False,
    ) -> SandboxResult:
        return SandboxResult(
            status=status,
            output=output,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            artifacts=artifacts,
            error_code=error_code,
            duration_ms=max(0, round((time.monotonic() - started) * 1000)),
            container_id=container_id,
            container_destroyed=container_destroyed,
            runtime_verified=False,
            trace_stages=tuple(trace),
            security={
                "network_disabled": True,
                "host_mounts": 0,
                "secrets_injected": 0,
                "non_root": True,
                "read_only_rootfs": True,
                "capabilities_dropped": "ALL",
                "no_new_privileges": True,
                "pids_limit": self.limits.pids_limit,
                "memory_bytes": self.limits.memory_bytes,
                "nano_cpus": self.limits.nano_cpus,
            },
        )


def _docker_client() -> Any:
    try:
        import docker
    except ImportError as exc:
        raise RuntimeError("Docker SDK is not installed") from exc
    return docker.from_env()


def _kill(container: Any) -> None:
    try:
        container.kill()
    except Exception:
        pass


def _close_client(client: Any) -> None:
    if client is None:
        return
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _destroy_synchronously(client: Any, container: Any) -> bool:
    container_id = str(container.id)
    try:
        container.remove(force=True)
        try:
            client.containers.get(container_id)
        except Exception as exc:
            return type(exc).__name__ == "NotFound" and getattr(
                exc, "status_code", 404
            ) == 404
        return False
    except Exception:
        return False
