from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .contracts import SandboxLimits


@dataclass(frozen=True)
class DockerWorkerSpec:
    image: str = "chatbi-sandbox-runtime:phase3"
    user: str = "65532:65532"

    def create_kwargs(
        self, *, job_id: str, limits: SandboxLimits, command: list[str]
    ) -> dict[str, Any]:
        return {
            "image": self.image,
            "name": f"chatbi_sandbox_{job_id}",
            "command": command,
            "detach": True,
            "use_config_proxy": False,
            "network_disabled": True,
            "network_mode": "none",
            "read_only": True,
            "user": self.user,
            "working_dir": "/workspace",
            "environment": {
                "LANG": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "PYTHONUNBUFFERED": "1",
            },
            "tmpfs": {
                "/tmp": "rw,noexec,nosuid,nodev,size=8m,mode=1777",
                "/workspace": (
                    "rw,noexec,nosuid,nodev,"
                    f"size={limits.workspace_bytes},mode=700,uid=65532,gid=65532"
                ),
            },
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "pids_limit": limits.pids_limit,
            "mem_limit": limits.memory_bytes,
            "memswap_limit": limits.memory_bytes,
            "nano_cpus": limits.nano_cpus,
            "auto_remove": False,
            "labels": {
                "com.chatbi.sandbox": "true",
                "com.chatbi.sandbox.job_id": job_id,
            },
        }

    @staticmethod
    def assert_hardened(kwargs: dict[str, Any]) -> None:
        forbidden = {"volumes", "mounts", "ports", "devices", "privileged"}
        if forbidden & set(kwargs):
            raise ValueError("worker spec contains a forbidden host capability")
        if (
            kwargs.get("use_config_proxy") is not False
            or not kwargs.get("network_disabled")
            or kwargs.get("network_mode") != "none"
            or not kwargs.get("read_only")
        ):
            raise ValueError("worker network/root filesystem is not isolated")
        if kwargs.get("user") in {None, "", "0", "root", "0:0"}:
            raise ValueError("worker must run as a non-root user")
        if kwargs.get("cap_drop") != ["ALL"]:
            raise ValueError("worker capabilities are not fully dropped")
        if "no-new-privileges:true" not in kwargs.get("security_opt", []):
            raise ValueError("worker no-new-privileges is missing")
        required_limits = ("pids_limit", "mem_limit", "memswap_limit", "nano_cpus")
        if any(not kwargs.get(item) for item in required_limits):
            raise ValueError("worker resource limit is missing")
        if set((kwargs.get("tmpfs") or {})) != {"/tmp", "/workspace"}:
            raise ValueError("worker temporary filesystems are not bounded")
        if any(
            token in key.upper()
            for key in (kwargs.get("environment") or {})
            for token in ("KEY", "SECRET", "TOKEN", "PASSWORD", "DATABASE", "CHATBI")
        ):
            raise ValueError("worker environment contains secret-shaped configuration")
