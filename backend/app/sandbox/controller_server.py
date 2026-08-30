from __future__ import annotations

import hashlib
import json
import re
import signal
import threading
import time
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping
from uuid import uuid4

from .contracts import SandboxLimits, SandboxResult, SandboxStatus
from .docker_executor import DockerSandboxExecutor
from .worker_spec import DockerWorkerSpec


PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 1024 * 1024
MAX_JOBS = 16
MAX_CONCURRENT_JOBS = 2
COMPLETED_TTL_SECONDS = 60.0
CANCEL_TOMBSTONE_TTL_SECONDS = 60.0
MAX_CANCEL_TOMBSTONES = 1024
_JOB_PATH = re.compile(r"^/v1/jobs/([0-9a-f]{32})$")


@dataclass
class _Job:
    job_id: str
    request_sha256: str
    cancellation: threading.Event
    created_monotonic: float
    thread: threading.Thread | None = None
    result: SandboxResult | None = None


class JobRegistry:
    def __init__(
        self,
        executor_factory: Callable[[SandboxLimits], DockerSandboxExecutor] | None = None,
    ) -> None:
        self._executor_factory = executor_factory or (
            lambda limits: DockerSandboxExecutor(
                limits=limits,
                worker_spec=DockerWorkerSpec(),
                controller_url="",
            )
        )
        self._jobs: dict[str, _Job] = {}
        self._cancel_tombstones: dict[str, float] = {}
        self._cancel_admission_until = 0.0
        self._lock = threading.Lock()
        self._capacity = threading.BoundedSemaphore(MAX_CONCURRENT_JOBS)

    def submit(self, payload: Mapping[str, Any], *, job_id: str | None = None) -> str:
        code, datasets, timeout_ms = _validate_job_payload(payload)
        request_sha256 = hashlib.sha256(json.dumps(
            {
                "code": code,
                "datasets": datasets,
                "timeout_ms": timeout_ms,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")).hexdigest()
        if job_id is not None and not re.fullmatch(r"[0-9a-f]{32}", job_id):
            raise ControllerRequestError(400, "SANDBOX_JOB_ID_INVALID")
        with self._lock:
            self._reap_locked()
            if job_id is not None and job_id in self._cancel_tombstones:
                raise ControllerRequestError(409, "SANDBOX_JOB_ID_CANCELLED")
            if self._cancel_admission_until > time.monotonic():
                # A saturated tombstone set means at least one cancelled ID
                # could not be represented individually.  Reject every new
                # submission until that late-arrival window expires; otherwise
                # an acknowledgement-lost PUT could start after its DELETE.
                raise ControllerRequestError(409, "SANDBOX_JOB_ID_CANCELLED")
            if job_id is not None and job_id in self._jobs:
                existing = self._jobs[job_id]
                if existing.request_sha256 != request_sha256:
                    raise ControllerRequestError(409, "SANDBOX_JOB_ID_CONFLICT")
                return job_id
            if len(self._jobs) >= MAX_JOBS or not self._capacity.acquire(blocking=False):
                raise ControllerRequestError(429, "SANDBOX_CONTROLLER_CAPACITY")
            job_id = job_id or uuid4().hex
            job = _Job(
                job_id,
                request_sha256,
                threading.Event(),
                time.monotonic(),
            )
            self._jobs[job_id] = job

        def run() -> None:
            try:
                limits = SandboxLimits(timeout_seconds=timeout_ms / 1000)
                result = self._executor_factory(limits).execute(
                    code,
                    datasets,
                    cancellation_event=job.cancellation,
                )
            except Exception:
                result = SandboxResult(
                    status=SandboxStatus.FAILED,
                    error_code="SANDBOX_CONTROLLER_EXECUTOR_FAILED",
                    trace_stages=("python.controller.executor.failed",),
                )
            finally:
                self._capacity.release()
            with self._lock:
                job.result = result

        job.thread = threading.Thread(
            target=run, name=f"sandbox-controller-{job_id}", daemon=True
        )
        job.thread.start()
        return job_id

    def get(self, job_id: str) -> Mapping[str, Any]:
        with self._lock:
            self._reap_locked()
            job = self._jobs.get(job_id)
            if job is None:
                raise ControllerRequestError(404, "SANDBOX_JOB_NOT_FOUND")
            if job.result is None:
                return _job_response(job_id, "RUNNING")
            return _job_response(job_id, "COMPLETED", asdict(job.result))

    def cancel(self, job_id: str) -> Mapping[str, Any]:
        with self._lock:
            self._reap_locked()
            job = self._jobs.get(job_id)
            if job is None:
                self._remember_cancel_locked(job_id)
                return _job_response(job_id, "ABSENT")
            self._remember_cancel_locked(job_id)
            if job.result is not None:
                result = asdict(job.result)
                self._jobs.pop(job_id, None)
                return _job_response(job_id, "COMPLETED", result)
            job.cancellation.set()
            return _job_response(job_id, "RUNNING")

    def shutdown(self, timeout: float = 20.0) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
            for job in jobs:
                job.cancellation.set()
        deadline = time.monotonic() + timeout
        for job in jobs:
            if job.thread is not None:
                job.thread.join(max(0.0, deadline - time.monotonic()))

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            self._reap_locked()
            running = sum(job.result is None for job in self._jobs.values())
            return {
                "registered_jobs": len(self._jobs),
                "running_jobs": running,
                "completed_jobs": len(self._jobs) - running,
            }

    def _reap_locked(self) -> None:
        now = time.monotonic()
        self._cancel_tombstones = {
            job_id: expires
            for job_id, expires in self._cancel_tombstones.items()
            if expires > now
        }
        if self._cancel_admission_until <= now:
            self._cancel_admission_until = 0.0
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.result is not None
            and now - job.created_monotonic >= COMPLETED_TTL_SECONDS
        ]
        for job_id in expired:
            self._jobs.pop(job_id, None)

    def _remember_cancel_locked(self, job_id: str) -> None:
        """Make every DELETE reject a delayed submission without unbounded state."""

        expires = time.monotonic() + CANCEL_TOMBSTONE_TTL_SECONDS
        if job_id in self._cancel_tombstones:
            self._cancel_tombstones[job_id] = expires
            return
        if len(self._cancel_tombstones) < MAX_CANCEL_TOMBSTONES:
            self._cancel_tombstones[job_id] = expires
            return
        # Capacity exhaustion must reduce availability, never cancellation
        # safety.  This global gate also protects the exact ID that could not
        # be stored and is extended by every subsequent DELETE.
        self._cancel_admission_until = max(self._cancel_admission_until, expires)


class ControllerRequestError(RuntimeError):
    def __init__(self, status: int, error_code: str) -> None:
        super().__init__(error_code)
        self.status = status
        self.error_code = error_code


class SandboxControllerHandler(BaseHTTPRequestHandler):
    registry: JobRegistry
    server_version = "ChatBISandboxController/1"

    def do_GET(self) -> None:
        if self.path == "/healthz":
            try:
                _verify_docker_runtime()
            except Exception:
                self._write(503, {"status": "UNAVAILABLE"})
            else:
                self._write(
                    200,
                    {"status": "OK", "protocol_version": PROTOCOL_VERSION},
                )
            return
        if self.path == "/diagnostics":
            try:
                worker_containers = _worker_container_count()
            except Exception:
                self._write(503, {"status": "UNAVAILABLE"})
            else:
                self._write(200, {
                    "status": "OK",
                    **self.registry.snapshot(),
                    "worker_containers": worker_containers,
                })
            return
        match = _JOB_PATH.fullmatch(self.path)
        if match:
            self._dispatch(lambda: self.registry.get(match.group(1)))
            return
        self._write(404, {"error_code": "SANDBOX_ENDPOINT_NOT_FOUND"})

    def do_POST(self) -> None:
        if self.path != "/v1/jobs":
            self._write(404, {"error_code": "SANDBOX_ENDPOINT_NOT_FOUND"})
            return
        try:
            payload = self._read_payload()
            job_id = self.registry.submit(payload)
        except ControllerRequestError as exc:
            self._write(exc.status, {"error_code": exc.error_code})
            return
        self._write(202, _job_response(job_id, "RUNNING"))

    def do_PUT(self) -> None:
        match = _JOB_PATH.fullmatch(self.path)
        if not match:
            self._write(404, {"error_code": "SANDBOX_ENDPOINT_NOT_FOUND"})
            return
        try:
            payload = self._read_payload()
            job_id = self.registry.submit(payload, job_id=match.group(1))
            response = self.registry.get(job_id)
        except ControllerRequestError as exc:
            self._write(exc.status, {"error_code": exc.error_code})
            return
        self._write(202, response)

    def do_DELETE(self) -> None:
        match = _JOB_PATH.fullmatch(self.path)
        if match:
            self._dispatch(lambda: self.registry.cancel(match.group(1)))
            return
        self._write(404, {"error_code": "SANDBOX_ENDPOINT_NOT_FOUND"})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_payload(self) -> Mapping[str, Any]:
        if self.headers.get("X-ChatBI-Sandbox-Protocol") != str(PROTOCOL_VERSION):
            raise ControllerRequestError(400, "SANDBOX_PROTOCOL_MISMATCH")
        if self.headers.get_content_type() != "application/json":
            raise ControllerRequestError(415, "SANDBOX_CONTENT_TYPE_REQUIRED")
        if self.headers.get("Transfer-Encoding"):
            raise ControllerRequestError(400, "SANDBOX_CHUNKED_REQUEST_DENIED")
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError as exc:
            raise ControllerRequestError(400, "SANDBOX_CONTENT_LENGTH_REQUIRED") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ControllerRequestError(413, "SANDBOX_CONTROLLER_REQUEST_LIMIT")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ControllerRequestError(400, "SANDBOX_INVALID_JSON") from exc
        if not isinstance(payload, Mapping):
            raise ControllerRequestError(400, "SANDBOX_INVALID_REQUEST")
        return payload

    def _dispatch(self, operation: Callable[[], Mapping[str, Any]]) -> None:
        try:
            payload = operation()
        except ControllerRequestError as exc:
            self._write(exc.status, {"error_code": exc.error_code})
        else:
            self._write(200, payload)

    def _write(self, status: int, payload: Mapping[str, Any]) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)


def _validate_job_payload(payload: Mapping[str, Any]) -> tuple[str, dict[str, Any], int]:
    if set(payload) != {"protocol_version", "code", "datasets", "timeout_ms"}:
        raise ControllerRequestError(400, "SANDBOX_REQUEST_FIELDS_DENIED")
    if payload.get("protocol_version") != PROTOCOL_VERSION:
        raise ControllerRequestError(400, "SANDBOX_PROTOCOL_MISMATCH")
    code = payload.get("code")
    datasets = payload.get("datasets")
    timeout_ms = payload.get("timeout_ms")
    if not isinstance(code, str) or not isinstance(datasets, dict):
        raise ControllerRequestError(400, "SANDBOX_INVALID_REQUEST")
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int):
        raise ControllerRequestError(400, "SANDBOX_INVALID_TIMEOUT")
    if not 1 <= timeout_ms <= 15_000:
        raise ControllerRequestError(400, "SANDBOX_INVALID_TIMEOUT")
    return code, datasets, timeout_ms


def _job_response(
    job_id: str, state: str, result: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "job_id": job_id,
        "state": state,
    }
    if result is not None:
        response["result"] = result
    return response


def _verify_docker_runtime() -> None:
    import docker

    client = docker.from_env()
    try:
        client.ping()
        client.images.get(DockerWorkerSpec().image)
    finally:
        client.close()


def _worker_container_count() -> int:
    import docker

    client = docker.from_env()
    try:
        return len(client.containers.list(
            all=True, filters={"label": "com.chatbi.sandbox=true"}
        ))
    finally:
        client.close()


def _remove_orphaned_workers() -> None:
    import docker

    client = docker.from_env()
    try:
        failures = []
        for container in client.containers.list(
            all=True, filters={"label": "com.chatbi.sandbox=true"}
        ):
            try:
                container.remove(force=True)
            except Exception:
                failures.append(str(container.id))
        if failures:
            raise RuntimeError("sandbox orphan cleanup failed")
    finally:
        client.close()


def main() -> None:
    _remove_orphaned_workers()
    _verify_docker_runtime()
    registry = JobRegistry()
    SandboxControllerHandler.registry = registry
    server = ThreadingHTTPServer(("0.0.0.0", 8765), SandboxControllerHandler)

    def stop_server(signum: int, frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        registry.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
