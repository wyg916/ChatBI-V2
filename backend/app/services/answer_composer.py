from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from numbers import Number
from typing import Any, Iterable

from app.schemas.chat import ResultSemantic
from app.streaming.protocol import PHASE_LABELS


SUCCESS_STATUSES = {"SUCCEEDED", "PARTIAL"}


def _find_query_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if isinstance(value.get("execution"), dict):
        return value
    for key in ("data", "data_evidence", "primary", "analysis"):
        found = _find_query_payload(value.get(key))
        if found is not None:
            return found
    return None


def _find_file_result(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    file_analysis = value.get("file_analysis")
    if isinstance(file_analysis, dict) and isinstance(file_analysis.get("result"), dict):
        return file_analysis
    return None


def _primary_value(result: dict[str, Any], rows: list[dict[str, Any]]) -> Any:
    if not rows:
        return None
    plan = result.get("plan") if isinstance(result.get("plan"), dict) else {}
    metrics = list(plan.get("metrics") or [])
    for metric in metrics:
        if metric in rows[0]:
            return rows[0].get(metric)
    for kpi in result.get("kpis") or []:
        if isinstance(kpi, dict) and "value" in kpi:
            return kpi.get("value")
    for value in rows[0].values():
        if value is None or isinstance(value, (Number, Decimal)) and not isinstance(value, bool):
            return value
    return next(iter(rows[0].values()), None)


def classify_result_semantic(status: str, response_payload: dict[str, Any]) -> ResultSemantic:
    if status not in SUCCESS_STATUSES:
        return ResultSemantic.FAILED
    query = _find_query_payload(response_payload)
    file_analysis = _find_file_result(response_payload)
    if query is not None:
        if str(query.get("status") or status) != "SUCCEEDED":
            return ResultSemantic.FAILED
        execution = query.get("execution") or {}
        if execution.get("status") not in (None, "SUCCEEDED"):
            return ResultSemantic.FAILED
        rows = list(execution.get("rows") or [])
        row_count = int(execution.get("row_count", len(rows)) or 0)
        result = query
    elif file_analysis is not None:
        if str(file_analysis.get("status") or "SUCCEEDED") != "SUCCEEDED":
            return ResultSemantic.FAILED
        result_data = file_analysis.get("result") or {}
        rows = list(result_data.get("rows") or [])
        row_count = len(rows)
        result = {"execution": result_data, "plan": {}}
    else:
        return ResultSemantic.VALUE

    if row_count == 0 or not rows:
        return ResultSemantic.NO_ROWS
    value = _primary_value(result, rows)
    if value is None:
        return ResultSemantic.NULL_VALUE
    if isinstance(value, (Number, Decimal)) and not isinstance(value, bool) and value == 0:
        return ResultSemantic.ZERO
    return ResultSemantic.VALUE


def _public_citations(response_payload: dict[str, Any]) -> list[dict[str, Any]]:
    analysis = response_payload.get("analysis") if isinstance(response_payload.get("analysis"), dict) else {}
    primary = analysis.get("primary") if isinstance(analysis.get("primary"), dict) else {}
    knowledge = primary.get("knowledge") if isinstance(primary.get("knowledge"), dict) else primary
    citations = knowledge.get("citations") if isinstance(knowledge, dict) else None
    if citations is None:
        citations = response_payload.get("citations") or []
    public: list[dict[str, Any]] = []
    for item in citations or []:
        if not isinstance(item, dict):
            continue
        resource_id = item.get("document_id") or item.get("attachment_id") or item.get("resource_id")
        title = str(item.get("title") or item.get("filename") or item.get("source") or "").strip()
        version = str(
            item.get("version")
            or item.get("document_version_id")
            or (item.get("attachment_id") if item.get("attachment_id") else "")
        ).strip()
        locator = str(item.get("locator") or item.get("chunk_id") or resource_id or "").strip()
        resource_id = str(resource_id or "").strip()
        if not all((title, version, locator, resource_id)):
            continue
        public.append({
            "title": title,
            "version": version,
            "locator": locator,
            "resource_id": resource_id,
        })
    return public


def _semantic_text(semantic: ResultSemantic, answer: str) -> str:
    if semantic is ResultSemantic.ZERO:
        return "当前条件下结果为 0。"
    if semantic is ResultSemantic.NO_ROWS:
        return "当前条件下没有匹配记录，并不代表指标为 0。"
    if semantic is ResultSemantic.NULL_VALUE:
        return "查询到记录，但指标字段为空。"
    if semantic is ResultSemantic.FAILED:
        return answer or "查询未完成，请检查权限、语义范围或数据源状态后重试。"
    return answer


def _text_chunks(text: str, *, target_size: int = 80) -> Iterable[str]:
    """Yield stable, lossless business fragments without timers or fake typing."""
    if not text:
        return
    chunks: list[str] = []
    for sentence in filter(None, re.split(r"(?<=[。！？!?；;\n])", text)):
        start = 0
        while len(sentence) - start > target_size:
            boundary = max(sentence.rfind(mark, start, start + target_size + 1) for mark in ("，", ",", "、", " "))
            end = boundary + 1 if boundary >= start else start + target_size
            chunks.append(sentence[start:end])
            start = end
        if start < len(sentence):
            chunks.append(sentence[start:])
    # Keep a canonical stream observably incremental even when a deterministic
    # or direct-SQL answer is shorter than the normal chunk size.
    if len(chunks) == 1 and len(chunks[0]) > 1:
        midpoint = max(1, len(chunks[0]) // 2)
        chunks = [chunks[0][:midpoint], chunks[0][midpoint:]]
    yield from chunks


@dataclass(frozen=True)
class ComposedAnswer:
    content: str
    message_parts: list[dict[str, Any]]
    result_semantic: ResultSemantic
    citations: list[dict[str, Any]]

    def deltas(self) -> Iterable[str]:
        return _text_chunks(self.content)


class AnswerComposer:
    def compose(
        self,
        *,
        answer: str,
        status: str,
        response_payload: dict[str, Any],
        error_code: str | None = None,
        phases: list[str] | None = None,
    ) -> ComposedAnswer:
        semantic = classify_result_semantic(status, response_payload)
        content = _semantic_text(semantic, answer)
        phases = list(dict.fromkeys(phases or []))
        phase_records = [
            {"phase": phase, "label": PHASE_LABELS[phase]}
            for phase in phases
            if phase in PHASE_LABELS
        ]
        query = _find_query_payload(response_payload)
        file_analysis = _find_file_result(response_payload)
        citations = _public_citations(response_payload)

        if semantic is ResultSemantic.FAILED:
            parts: list[dict[str, Any]] = [{
                "type": "error",
                "code": error_code or "CHAT_RUN_FAILED",
                "message": content,
                "retryable": (error_code or "") not in {"UNSUPPORTED", "PERMISSION_DENIED"},
            }]
            return ComposedAnswer(content=content, message_parts=parts, result_semantic=semantic, citations=[])

        parts = [{"type": "text", "text": content, "role": "conclusion"}]
        rows: list[dict[str, Any]] = []
        source_row_count = 0
        columns: list[str] = []
        result_signature: str | None = None
        chart_spec: dict[str, Any] = {}
        kpis: list[dict[str, Any]] = []
        recommended: list[str] = []
        insights: list[str] = []
        evidence: dict[str, Any] | None = None

        if query is not None:
            execution = query.get("execution") or {}
            rows = list(execution.get("rows") or [])
            execution_row_count = execution.get("row_count")
            source_row_count = int(execution_row_count) if execution_row_count is not None else len(rows)
            columns = list(execution.get("columns") or (list(rows[0]) if rows else []))
            result_signature = execution.get("result_signature")
            chart_spec = query.get("chart_spec") or {}
            kpis = list(query.get("kpis") or [])
            narrative = query.get("narrative") or {}
            insights = list(narrative.get("insights") or [])
            recommended = list(query.get("recommended_questions") or narrative.get("recommended_questions") or [])
            guard = query.get("guard") or {}
            evidence = {
                "type": "evidence",
                "sql": guard.get("normalized_sql"),
                "guard": guard,
                "oracle": query.get("oracle") or {},
                "semantic": query.get("plan") or {},
                "phases": phase_records,
            }
        elif file_analysis is not None:
            result = file_analysis.get("result") or {}
            rows = list(result.get("rows") or [])
            source_row_count = len(rows)
            columns = list(result.get("columns") or (list(rows[0]) if rows else []))
            result_signature = result.get("result_signature")

        if semantic in {ResultSemantic.VALUE, ResultSemantic.ZERO} and kpis:
            parts.append({
                "type": "kpi",
                "items": [
                    {
                        "label": str(item.get("label") or ""),
                        "value": item.get("value"),
                        "unit": str(item.get("unit") or ""),
                    }
                    for item in kpis
                    if isinstance(item, dict) and item.get("label")
                ],
            })
        if semantic in {ResultSemantic.VALUE, ResultSemantic.ZERO} and chart_spec and result_signature:
            parts.append({"type": "chart", "chart_spec": chart_spec, "result_signature": result_signature})
        if semantic in {ResultSemantic.VALUE, ResultSemantic.ZERO} and insights:
            parts.append({"type": "text", "text": "\n".join(insights), "role": "insights"})
        if rows and result_signature:
            parts.append({
                "type": "table",
                "columns": columns,
                "rows": rows[:20],
                "row_count": source_row_count,
                "result_signature": result_signature,
            })
        if recommended:
            parts.append({"type": "text", "text": "\n".join(recommended), "role": "followups"})
        if citations:
            parts.append({"type": "citations", "items": citations})
        if evidence is not None:
            parts.append(evidence)
        return ComposedAnswer(content=content, message_parts=parts, result_semantic=semantic, citations=citations)


__all__ = ["AnswerComposer", "ComposedAnswer", "classify_result_semantic"]
