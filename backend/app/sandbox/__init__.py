from typing import TYPE_CHECKING

from .contracts import (
    PythonSandbox,
    SandboxArtifact,
    SandboxLimits,
    SandboxResult,
    SandboxStatus,
)
from .docker_executor import DockerSandboxExecutor
from .guard import PythonCodeGuard, SandboxPolicyViolation
from .worker_spec import DockerWorkerSpec

if TYPE_CHECKING:
    from .controller_client import SandboxControllerClient


def __getattr__(name: str):
    # The isolated controller image imports this package before launching
    # ``controller_server`` but intentionally does not install Backend-only
    # HTTP client dependencies.  Keep the client available to Backend callers
    # without eagerly importing it in the controller process.
    if name == "SandboxControllerClient":
        from .controller_client import SandboxControllerClient

        return SandboxControllerClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "DockerSandboxExecutor",
    "SandboxControllerClient",
    "DockerWorkerSpec",
    "PythonCodeGuard",
    "PythonSandbox",
    "SandboxArtifact",
    "SandboxLimits",
    "SandboxPolicyViolation",
    "SandboxResult",
    "SandboxStatus",
]
