from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from threading import Event
from typing import Any, Mapping, Protocol


class SandboxStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    REFUSED = "REFUSED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class SandboxLimits:
    timeout_seconds: float = 15.0
    max_code_bytes: int = 64 * 1024
    max_dataset_bytes: int = 512 * 1024
    max_output_bytes: int = 256 * 1024
    max_file_bytes: int = 64 * 1024
    max_files: int = 4
    max_ast_nodes: int = 2_000
    memory_bytes: int = 512 * 1024 * 1024
    nano_cpus: int = 1_000_000_000
    pids_limit: int = 32
    workspace_bytes: int = 16 * 1024 * 1024


@dataclass(frozen=True)
class SandboxArtifact:
    name: str
    media_type: str
    size_bytes: int
    sha256: str
    content_base64: str


@dataclass(frozen=True)
class SandboxResult:
    status: SandboxStatus
    output: Any = None
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    artifacts: tuple[SandboxArtifact, ...] = ()
    error_code: str | None = None
    duration_ms: int = 0
    container_id: str | None = None
    container_destroyed: bool = False
    runtime_verified: bool = False
    trace_stages: tuple[str, ...] = field(default_factory=tuple)
    security: Mapping[str, Any] = field(default_factory=dict)


class PythonSandbox(Protocol):
    def execute(
        self,
        code: str,
        datasets: Mapping[str, Any],
        *,
        cancellation_event: Event | None = None,
        deadline_monotonic: float | None = None,
    ) -> SandboxResult: ...
