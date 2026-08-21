from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


REQUIRED_EVENTS = (
    "run.started",
    "phase.started",
    "phase.completed",
    "answer.delta",
    "artifact.ready",
    "citations.ready",
    "run.completed",
    "run.failed",
    "run.cancelled",
)

TERMINAL_EVENTS = frozenset({"run.completed", "run.failed", "run.cancelled"})

PHASE_LABELS = {
    "understanding": "正在理解问题……",
    "semantic_mapping": "正在识别指标和维度……",
    "querying_data": "正在查询数据……",
    "retrieving_knowledge": "正在检索业务规则……",
    "verifying": "正在校验结果……",
    "composing_answer": "正在整理回答……",
}

STAGE_PHASES = {
    "UNDERSTANDING": "understanding",
    "CATALOG_RETRIEVING": "understanding",
    "SCHEMA_LINKED": "semantic_mapping",
    "SEMANTIC_PARSING": "semantic_mapping",
    "SEMANTIC_COMPILING": "semantic_mapping",
    "SQL_VALIDATING": "semantic_mapping",
    "QUERYING_DATA": "querying_data",
    "SQL_RUNNING": "querying_data",
    "PYTHON_RUNNING": "querying_data",
    "RETRIEVING_KNOWLEDGE": "retrieving_knowledge",
    "AGENT_RUNNING": "understanding",
    "VERIFYING": "verifying",
    "RESULT_VALIDATING": "verifying",
    "GENERATING_INSIGHT": "composing_answer",
    "CHART_READY": "composing_answer",
}


def phase_for_stage(stage: str) -> str | None:
    """Map private runtime progress to one of the six public business phases."""
    return STAGE_PHASES.get(stage.upper())


def event_for_stage(stage: str) -> str | None:
    """Compatibility name retained for callers; values are now public phases."""
    return phase_for_stage(stage)


@dataclass
class StreamEventFactory:
    run_id: str
    conversation_id: str
    message_id: str
    request_id: str | None = None
    sequence: int = 0
    _started: bool = field(default=False, init=False)
    _terminal: str | None = field(default=None, init=False)

    def create(self, event_type: str, **payload: Any) -> dict[str, Any]:
        if event_type not in REQUIRED_EVENTS:
            raise ValueError(f"Unsupported stream event: {event_type}")
        if self._terminal is not None:
            raise RuntimeError(f"Cannot emit {event_type} after terminal event {self._terminal}")
        if not self._started and event_type != "run.started":
            raise RuntimeError("run.started must be the first stream event")
        if self._started and event_type == "run.started":
            raise RuntimeError("run.started may only be emitted once")
        if event_type == "answer.delta" and not str(payload.get("delta") or ""):
            raise ValueError("answer.delta requires a non-empty delta")
        if event_type in {"phase.started", "phase.completed"}:
            phase = str(payload.get("phase") or "")
            if phase not in PHASE_LABELS:
                raise ValueError(f"Unsupported public phase: {phase}")
            payload.setdefault("label", PHASE_LABELS[phase])

        self.sequence += 1
        event = {
            "seq": self.sequence,
            "run_id": self.run_id,
            "trace_id": self.run_id,
            "request_id": self.request_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "event_type": event_type,
            **payload,
        }
        if event_type == "run.started":
            self._started = True
        if event_type in TERMINAL_EVENTS:
            self._terminal = event_type
        return event


def format_sse(event: str, payload: dict[str, Any]) -> str:
    if payload.get("event_type") != event:
        raise ValueError("SSE event name must equal payload.event_type")
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
