from __future__ import annotations

import ctypes
import os
import platform
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


CATEGORIES = (
    "backend", "postgres", "sandbox", "docker_vm",
    "load_generator", "browser", "other",
)


def configure_load_generator_affinity(cpu_count: int) -> dict[str, Any]:
    if cpu_count <= 0:
        raise ValueError("load generator cpu count must be positive")
    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetProcessAffinityMask.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel32.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        process = kernel32.GetCurrentProcess()
        process_mask = ctypes.c_size_t()
        system_mask = ctypes.c_size_t()
        if not kernel32.GetProcessAffinityMask(
            process, ctypes.byref(process_mask), ctypes.byref(system_mask),
        ):
            raise RuntimeError("LOAD_GENERATOR_AFFINITY_QUERY_FAILED")
        available = [bit for bit in range(ctypes.sizeof(ctypes.c_size_t) * 8) if process_mask.value & (1 << bit)]
        selected = available[:cpu_count]
        if not selected:
            raise RuntimeError("LOAD_GENERATOR_AFFINITY_EMPTY")
        selected_mask = sum(1 << bit for bit in selected)
        if not kernel32.SetProcessAffinityMask(process, ctypes.c_size_t(selected_mask)):
            raise RuntimeError("LOAD_GENERATOR_AFFINITY_SET_FAILED")
        return {
            "status": "APPLIED",
            "mode": "SAME_HOST_CPU_AFFINITY_PARTITION",
            "cpu_count": len(selected),
            "cpu_indexes": selected,
            "load_generator_pid": os.getpid(),
        }
    if platform.system() == "Linux" and hasattr(os, "sched_getaffinity"):
        available = sorted(os.sched_getaffinity(0))
        selected = available[:cpu_count]
        os.sched_setaffinity(0, selected)
        return {
            "status": "APPLIED",
            "mode": "SAME_HOST_CPU_AFFINITY_PARTITION",
            "cpu_count": len(selected),
            "cpu_indexes": selected,
            "load_generator_pid": os.getpid(),
        }
    return {
        "status": "UNAVAILABLE",
        "mode": "PROCESS_LEVEL_ATTRIBUTION_ONLY",
        "cpu_count": 0,
        "cpu_indexes": [],
        "load_generator_pid": os.getpid(),
    }


class ProcessAttributionProbe:
    def __init__(self, *, backend_pid: int, load_generator_pid: int | None = None) -> None:
        if backend_pid <= 0:
            raise ValueError("backend pid must be positive")
        self.backend_pid = backend_pid
        self.load_generator_pid = load_generator_pid or os.getpid()
        self._process_state: dict[int, int] = {}
        self._system_state: int | None = None

    def sample(self) -> dict[str, Any]:
        if os.name == "nt":
            return self._sample_windows()
        if platform.system() == "Linux":
            return self._sample_linux()
        return {
            "categories": {category: None for category in CATEGORIES},
            "top_processes": [],
            "process_count": 0,
        }

    def _category(self, pid: int, name: str) -> str:
        lowered = name.casefold()
        if pid == self.backend_pid:
            return "backend"
        if pid == self.load_generator_pid:
            return "load_generator"
        if lowered.startswith("postgres"):
            return "postgres"
        if "sandbox" in lowered:
            return "sandbox"
        if any(token in lowered for token in ("docker", "vmmem", "wslhost")):
            return "docker_vm"
        if any(token in lowered for token in ("chrome", "chromium", "msedge", "firefox")):
            return "browser"
        return "other"

    @staticmethod
    def _filetime(value: Any) -> int:
        return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)

    def _sample_windows(self) -> dict[str, Any]:
        class FileTime(ctypes.Structure):
            _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

        class ProcessEntry(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32),
                ("th32ProcessID", ctypes.c_uint32), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", ctypes.c_uint32), ("cntThreads", ctypes.c_uint32),
                ("th32ParentProcessID", ctypes.c_uint32), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_uint32), ("szExeFile", ctypes.c_wchar * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProcessEntry)]
        kernel32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProcessEntry)]
        idle, kernel_system, user_system = FileTime(), FileTime(), FileTime()
        if not kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel_system), ctypes.byref(user_system),
        ):
            raise RuntimeError("SYSTEM_TIMES_UNAVAILABLE")
        system_value = self._filetime(kernel_system) + self._filetime(user_system)
        system_delta = system_value - self._system_state if self._system_state is not None else 0

        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        if snapshot in (0, ctypes.c_void_p(-1).value):
            raise RuntimeError("PROCESS_SNAPSHOT_UNAVAILABLE")
        current: dict[int, int] = {}
        names: dict[int, str] = {}
        try:
            entry = ProcessEntry()
            entry.dwSize = ctypes.sizeof(ProcessEntry)
            has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while has_entry:
                pid = int(entry.th32ProcessID)
                name = str(entry.szExeFile) or "unknown"
                handle = kernel32.OpenProcess(0x1000, False, pid)
                if handle:
                    try:
                        created, exited, kernel, user = FileTime(), FileTime(), FileTime(), FileTime()
                        if kernel32.GetProcessTimes(
                            handle, ctypes.byref(created), ctypes.byref(exited),
                            ctypes.byref(kernel), ctypes.byref(user),
                        ):
                            current[pid] = self._filetime(kernel) + self._filetime(user)
                            names[pid] = name
                    finally:
                        kernel32.CloseHandle(handle)
                has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        result = self._aggregate(current, names, system_delta)
        self._process_state = current
        self._system_state = system_value
        return result

    def _sample_linux(self) -> dict[str, Any]:
        fields = [int(item) for item in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        system_value = sum(fields)
        system_delta = system_value - self._system_state if self._system_state is not None else 0
        current: dict[int, int] = {}
        names: dict[int, str] = {}
        for path in Path("/proc").iterdir():
            if not path.name.isdigit():
                continue
            try:
                stat = (path / "stat").read_text(encoding="utf-8")
                name, values = stat.rsplit(") ", 1)
                fields = values.split()
                pid = int(path.name)
                current[pid] = int(fields[11]) + int(fields[12])
                names[pid] = name.split("(", 1)[1]
            except (FileNotFoundError, PermissionError, ValueError, IndexError):
                continue
        result = self._aggregate(current, names, system_delta)
        self._process_state = current
        self._system_state = system_value
        return result

    def _aggregate(self, current: dict[int, int], names: dict[int, str], system_delta: int) -> dict[str, Any]:
        categories = {category: 0.0 for category in CATEGORIES}
        processes: list[dict[str, Any]] = []
        if system_delta > 0:
            for pid, value in current.items():
                previous = self._process_state.get(pid)
                if previous is None or value < previous:
                    continue
                cpu = max(0.0, min(100.0, (value - previous) * 100.0 / system_delta))
                category = self._category(pid, names.get(pid, "unknown"))
                categories[category] += cpu
                if cpu > 0:
                    processes.append({
                        "pid": pid,
                        "name": names.get(pid, "unknown"),
                        "category": category,
                        "cpu_percent": round(cpu, 6),
                    })
        return {
            "categories": {key: round(min(100.0, value), 6) for key, value in categories.items()},
            "top_processes": sorted(processes, key=lambda item: item["cpu_percent"], reverse=True)[:10],
            "process_count": len(current),
        }


def collect_idle_baseline(
    *, duration_seconds: int, host_probe: Any, attribution_probe: ProcessAttributionProbe,
    sample_interval_seconds: float = 1.0,
) -> dict[str, Any]:
    if duration_seconds < 0:
        raise ValueError("idle baseline duration cannot be negative")
    host_cpu: list[float] = []
    host_ram: list[float] = []
    attribution: list[dict[str, Any]] = []
    started = time.perf_counter()
    deadline = started + duration_seconds
    while time.perf_counter() < deadline:
        cpu, ram = host_probe.sample()
        if cpu is not None:
            host_cpu.append(float(cpu))
        if ram is not None:
            host_ram.append(float(ram))
        attribution.append(attribution_probe.sample())
        remaining = deadline - time.perf_counter()
        if remaining > 0:
            time.sleep(min(sample_interval_seconds, remaining))
    return {
        "requested_seconds": duration_seconds,
        "actual_seconds": round(time.perf_counter() - started, 6),
        "host_cpu_values": host_cpu,
        "host_ram_values": host_ram,
        "process_samples": attribution,
    }


def summarize_attribution(samples: list[dict[str, Any]], distribution_fn: Any) -> dict[str, Any]:
    categories = {
        category: distribution_fn([
            float(sample["categories"][category])
            for sample in samples
            if sample.get("categories", {}).get(category) is not None
        ])
        for category in CATEGORIES
    }
    process_values: dict[tuple[str, str], list[float]] = defaultdict(list)
    for sample in samples:
        for process in sample.get("top_processes", []):
            process_values[(str(process["name"]), str(process["category"]))].append(float(process["cpu_percent"]))
    top = [{
        "name": name,
        "category": category,
        "cpu_percent": distribution_fn(values),
    } for (name, category), values in process_values.items()]
    top.sort(key=lambda item: float(item["cpu_percent"].get("p99") or 0.0), reverse=True)
    return {
        "categories": categories,
        "top_processes": top[:15],
        "sample_count": len(samples),
        "sandbox_attribution": "IN_PROCESS_BACKEND_OR_NAMED_SANDBOX_PROCESS",
        "secrets_exposed": False,
    }
