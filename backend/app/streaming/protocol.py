from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any


REQUIRED_EVENTS = (
    "accepted",
    "catalog_retrieving",
    "schema_linked",
    "semantic_parsing",
    "semantic_compiling",
    "sql_validating",
    "sql_running",
    "result_validating",
    "knowledge_retrieving",
    "agent_running",
    "python_running",
    "answer_delta",
    "chart_ready",
    "completed",
    "error",
    "cancelled",
    "heartbeat",
)


STAGE_EVENTS = {
    "UNDERSTANDING": "catalog_retrieving",
    "CATALOG_RETRIEVING": "catalog_retrieving",
    "SCHEMA_LINKED": "schema_linked",
    "SEMANTIC_PARSING": "semantic_parsing",
    "SEMANTIC_COMPILING": "semantic_compiling",
    "SQL_VALIDATING": "sql_validating",
    "QUERYING_DATA": "sql_running",
    "SQL_RUNNING": "sql_running",
    "RESULT_VALIDATING": "result_validating",
    "RETRIEVING_KNOWLEDGE": "knowledge_retrieving",
    "AGENT_RUNNING": "agent_running",
    "VERIFYING": "result_validating",
    "GENERATING_INSIGHT": "answer_delta",
    "PYTHON_RUNNING": "python_running",
    "CHART_READY": "chart_ready",
}


EVENT_MESSAGES = {
    "accepted": "已接收请求",
    "catalog_retrieving": "正在检索业务目录",
    "schema_linked": "已识别候选表与字段",
    "semantic_parsing": "正在解析指标、维度、时间与过滤条件",
    "semantic_compiling": "正在编译语义查询",
    "sql_validating": "正在执行只读 SQL 与权限校验",
    "sql_running": "正在执行只读查询",
    "result_validating": "正在校验结果值与业务口径",
    "knowledge_retrieving": "正在检索授权知识依据",
    "agent_running": "正在执行受控分析步骤",
    "python_running": "正在受控沙箱中分析文件",
    "answer_delta": "正在生成可验证回答",
    "chart_ready": "图表已准备",
    "completed": "请求已完成",
    "error": "请求执行失败",
    "cancelled": "请求已取消",
    "heartbeat": "请求仍在处理中",
}


def event_for_stage(stage: str) -> str | None:
    return STAGE_EVENTS.get(stage.upper())


@dataclass
class StreamEventFactory:
    trace_id: str
    started: float = field(default_factory=perf_counter)
    sequence: int = 0

    def create(
        self,
        event: str,
        *,
        capability: str = "chatbi",
        message: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if event not in REQUIRED_EVENTS:
            raise ValueError(f"Unsupported stream event: {event}")
        self.sequence += 1
        return {
            "trace_id": self.trace_id,
            "sequence": self.sequence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_ms": round((perf_counter() - self.started) * 1000),
            "event": event,
            "capability": capability,
            "message": message or EVENT_MESSAGES[event],
            "data": data or {},
        }


def format_sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
