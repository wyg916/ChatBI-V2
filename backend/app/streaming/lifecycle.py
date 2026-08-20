from __future__ import annotations

from dataclasses import dataclass, field
from contextlib import contextmanager
from threading import Event, Lock
from time import monotonic


class StreamCancelled(RuntimeError):
    """Raised at a public progress boundary after a client cancellation."""


@dataclass
class StreamLifecycle:
    trace_id: str
    conversation_id: str | None = None
    client_message_id: str | None = None
    cancel_event: Event = field(default_factory=Event)
    created_at: float = field(default_factory=monotonic)
    connection_open: bool = True
    task_running: bool = False

    def cancel(self) -> None:
        self.cancel_event.set()

    def checkpoint(self) -> None:
        if self.cancel_event.is_set():
            raise StreamCancelled(self.trace_id)


class StreamRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._streams: dict[str, StreamLifecycle] = {}
        self._workloads = {"agent": 0, "sandbox": 0}
        self._workload_max = {"agent": 0, "sandbox": 0}
        self._workload_total = {"agent": 0, "sandbox": 0}

    @contextmanager
    def workload(self, kind: str | None):
        if kind is None:
            yield
            return
        if kind not in self._workloads:
            raise ValueError(f"Unknown workload kind: {kind}")
        with self._lock:
            self._workloads[kind] += 1
            self._workload_total[kind] += 1
            self._workload_max[kind] = max(self._workload_max[kind], self._workloads[kind])
        try:
            yield
        finally:
            with self._lock:
                self._workloads[kind] = max(0, self._workloads[kind] - 1)

    def register(
        self,
        trace_id: str,
        *,
        conversation_id: str | None = None,
        client_message_id: str | None = None,
    ) -> StreamLifecycle:
        lifecycle = StreamLifecycle(
            trace_id=trace_id,
            conversation_id=conversation_id,
            client_message_id=client_message_id,
        )
        with self._lock:
            self._streams[trace_id] = lifecycle
        return lifecycle

    def task_started(self, trace_id: str) -> None:
        with self._lock:
            lifecycle = self._streams.get(trace_id)
            if lifecycle:
                lifecycle.task_running = True

    def task_finished(self, trace_id: str) -> None:
        with self._lock:
            lifecycle = self._streams.get(trace_id)
            if lifecycle:
                lifecycle.task_running = False
                self._prune(trace_id, lifecycle)

    def connection_closed(self, trace_id: str) -> None:
        with self._lock:
            lifecycle = self._streams.get(trace_id)
            if lifecycle:
                lifecycle.connection_open = False
                lifecycle.cancel()
                self._prune(trace_id, lifecycle)

    def cancel(self, trace_id: str) -> bool:
        with self._lock:
            lifecycle = self._streams.get(trace_id)
            if not lifecycle:
                return False
            lifecycle.cancel()
            return True

    def cancel_matching(self, *, conversation_id: str, client_message_id: str) -> bool:
        with self._lock:
            lifecycle = next((
                item for item in self._streams.values()
                if item.conversation_id == conversation_id
                and item.client_message_id == client_message_id
            ), None)
            if lifecycle is None:
                return False
            lifecycle.cancel()
            return True

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "active_connections": sum(item.connection_open for item in self._streams.values()),
                "active_tasks": sum(item.task_running for item in self._streams.values()),
                "active_agent_tasks": self._workloads["agent"],
                "active_sandbox_tasks": self._workloads["sandbox"],
                "max_agent_tasks": self._workload_max["agent"],
                "max_sandbox_tasks": self._workload_max["sandbox"],
                "total_agent_tasks": self._workload_total["agent"],
                "total_sandbox_tasks": self._workload_total["sandbox"],
                "trace_ids": sorted(self._streams),
            }

    def _prune(self, trace_id: str, lifecycle: StreamLifecycle) -> None:
        if not lifecycle.connection_open and not lifecycle.task_running:
            self._streams.pop(trace_id, None)


stream_registry = StreamRegistry()
