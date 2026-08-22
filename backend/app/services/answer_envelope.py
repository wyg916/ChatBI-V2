from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.schemas.answer_envelope import (
    AgentStepItem,
    AnswerArtifact,
    AnswerCitation,
    AnswerCost,
    AnswerEnvelope,
    AnswerError,
    AnswerKpi,
    AnswerLatency,
    AnswerResultSemantic,
    AnswerRoute,
    AnswerTable,
    AnswerVerification,
    AnswerWarning,
    FileEvidenceItem,
    VerificationCheck,
    VisualClaimItem,
    VisualEvidenceItem,
)


_SUCCESS = {"SUCCEEDED", "PARTIAL"}
_CHART_TYPES = {"KPI", "LINE", "BAR", "GROUPED_BAR", "STACKED_BAR", "DONUT", "TABLE"}
_SERIES_TYPES = {"line", "bar", "pie", "kpi", "table"}
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [_record(item) for item in value if isinstance(item, Mapping)]


def _text(value: Any, *, limit: int = 2_000) -> str:
    if value is None:
        return ""
    cleaned = _CONTROL_CHARS.sub(" ", str(value)).strip()
    return cleaned[:limit]


def _filename(value: Any) -> str:
    candidate = re.split(r"[\\/]", _text(value, limit=512))[-1]
    candidate = " ".join(candidate.split())
    return candidate or "artifact"


def _integer(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0) -> float:
    if isinstance(value, bool):
        return default
    try:
        return max(0, float(value))
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if 0 <= parsed <= 1 else None


def _safe_api_url(value: Any) -> str | None:
    candidate = _text(value, limit=2_048)
    if not candidate.startswith("/api/v1/"):
        return None
    if "\\" in candidate or ".." in candidate or any(char.isspace() for char in candidate):
        return None
    return candidate


def _safe_citation_href(value: Any) -> str | None:
    candidate = _text(value, limit=2_048)
    if _safe_api_url(candidate):
        return candidate
    if re.match(r"^https?://", candidate, flags=re.IGNORECASE):
        return candidate
    return None


def _route(value: Any) -> AnswerRoute:
    normalized = _text(getattr(value, "value", value), limit=64).upper()
    if normalized == "MULTIMODAL_QUERY":
        normalized = "VISION_QUERY"
    try:
        return AnswerRoute(normalized)
    except ValueError:
        return AnswerRoute.UNSUPPORTED


def _semantic(value: Any, status: str) -> AnswerResultSemantic:
    normalized = _text(getattr(value, "value", value), limit=32).upper()
    if not normalized:
        normalized = "VALUE" if status in _SUCCESS else "FAILED"
    try:
        return AnswerResultSemantic(normalized)
    except ValueError:
        return AnswerResultSemantic.FAILED if status not in _SUCCESS else AnswerResultSemantic.VALUE


def _find_query_payload(value: Any, *, depth: int = 0) -> dict[str, Any] | None:
    if depth > 6 or not isinstance(value, Mapping):
        return None
    current = _record(value)
    if isinstance(current.get("execution"), Mapping):
        return current
    for key in ("data", "data_evidence", "primary", "analysis", "query"):
        found = _find_query_payload(current.get(key), depth=depth + 1)
        if found is not None:
            return found
    return None


def _analysis_primary(response_payload: Mapping[str, Any]) -> dict[str, Any]:
    analysis = _record(response_payload.get("analysis"))
    return _record(analysis.get("primary"))


def _parts(message_parts: Iterable[Mapping[str, Any]] | None, response_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    source = list(message_parts or [])
    if not source:
        source = _records(response_payload.get("message_parts"))
    return [_record(part) for part in source if _text(part.get("type"), limit=64)]


def _first_part(parts: Sequence[Mapping[str, Any]], part_type: str) -> dict[str, Any]:
    return next((_record(part) for part in parts if part.get("type") == part_type), {})


def _summary(content: str, parts: Sequence[Mapping[str, Any]], response_payload: Mapping[str, Any]) -> str:
    conclusion = next(
        (
            _text(part.get("text"), limit=20_000)
            for part in parts
            if part.get("type") == "text" and part.get("role") in {None, "conclusion"} and _text(part.get("text"))
        ),
        "",
    )
    return conclusion or _text(response_payload.get("summary"), limit=20_000) or _text(content, limit=20_000)


def _kpis(parts: Sequence[Mapping[str, Any]], query: Mapping[str, Any] | None) -> list[AnswerKpi]:
    candidates: list[dict[str, Any]] = []
    for part in parts:
        if part.get("type") == "kpi":
            candidates.extend(_records(part.get("items")))
    if not candidates and query is not None:
        candidates.extend(_records(query.get("kpis")))
    result: list[AnswerKpi] = []
    seen: set[str] = set()
    for item in candidates:
        label = _text(item.get("label"), limit=160)
        if not label or label in seen:
            continue
        seen.add(label)
        result.append(AnswerKpi(label=label, value=item.get("value"), unit=_text(item.get("unit"), limit=40)))
    return result[:100]


def _insights(parts: Sequence[Mapping[str, Any]], query: Mapping[str, Any] | None) -> list[str]:
    values: list[str] = []
    for part in parts:
        if part.get("type") == "text" and part.get("role") == "insights":
            values.extend(str(part.get("text") or "").splitlines())
    if query is not None:
        narrative = _record(query.get("narrative"))
        source = narrative.get("insights")
        if isinstance(source, Sequence) and not isinstance(source, (str, bytes, bytearray)):
            values.extend(str(item) for item in source)
    return list(dict.fromkeys(filter(None, (_text(item, limit=2_000) for item in values))))[:100]


def _table(
    parts: Sequence[Mapping[str, Any]],
    response_payload: Mapping[str, Any],
    query: Mapping[str, Any] | None,
) -> AnswerTable | None:
    source = _first_part(parts, "table")
    if not source:
        file_analysis = _record(response_payload.get("file_analysis"))
        source = _record(file_analysis.get("result"))
    if not source and query is not None:
        source = _record(query.get("execution"))
    rows = _records(source.get("rows"))
    columns_value = source.get("columns")
    columns = (
        [_text(item, limit=256) for item in columns_value]
        if isinstance(columns_value, Sequence) and not isinstance(columns_value, (str, bytes, bytearray))
        else list(rows[0]) if rows else []
    )
    columns = list(dict.fromkeys(filter(None, columns)))[:200]
    if not columns and not rows:
        return None
    public_rows = [{column: row.get(column) for column in columns} for row in rows[:500]]
    row_count = _integer(source.get("row_count"), len(public_rows))
    return AnswerTable(
        columns=columns,
        rows=public_rows,
        row_count=max(row_count, len(public_rows)),
        result_signature=_text(source.get("result_signature"), limit=256) or None,
        truncated=bool(source.get("truncated")) or row_count > len(public_rows),
    )


def _string_map(value: Any) -> dict[str, str]:
    return {
        _text(key, limit=256): _text(item, limit=256)
        for key, item in _record(value).items()
        if _text(key, limit=256) and _text(item, limit=256)
    }


def _chart(
    parts: Sequence[Mapping[str, Any]],
    query: Mapping[str, Any] | None,
    response_payload: Mapping[str, Any],
    table: AnswerTable | None,
) -> dict[str, Any] | None:
    part = _first_part(parts, "chart")
    source = _record(part.get("chart_spec"))
    if not source and query is not None:
        source = _record(query.get("chart_spec"))
    if not source:
        source = _record(_record(response_payload.get("file_analysis")).get("chart"))
    if not source:
        return None

    chart_type = _text(source.get("chart_type"), limit=32).upper()
    aliases = {"PIE": "DONUT", "GROUPEDBAR": "GROUPED_BAR", "STACKEDBAR": "STACKED_BAR"}
    chart_type = aliases.get(chart_type, chart_type)
    if chart_type not in _CHART_TYPES:
        return None
    x_field = _text(source.get("x_field") or source.get("x"), limit=256) or None
    y_value = source.get("y_fields")
    y_fields = (
        [_text(item, limit=256) for item in y_value]
        if isinstance(y_value, Sequence) and not isinstance(y_value, (str, bytes, bytearray))
        else [_text(source.get("y"), limit=256)]
    )
    y_fields = list(dict.fromkeys(filter(None, y_fields)))[:20]
    if not y_fields and chart_type not in {"TABLE"}:
        return None

    series: list[dict[str, Any]] = []
    for item in _records(source.get("series")):
        field = _text(item.get("field"), limit=256)
        series_type = _text(item.get("type"), limit=32).lower()
        if not field or series_type not in _SERIES_TYPES:
            continue
        series.append({
            "name": _text(item.get("name") or field, limit=256),
            "field": field,
            "type": series_type,
            **({"stack": _text(item.get("stack"), limit=128)} if _text(item.get("stack"), limit=128) else {}),
        })
    if not series:
        fallback_type = "line" if chart_type == "LINE" else "pie" if chart_type == "DONUT" else "bar"
        series = [{"name": field, "field": field, "type": fallback_type} for field in y_fields]

    columns = table.columns if table else []
    bound_row_count = table.row_count if table else _integer(source.get("bound_row_count"))
    result_signature = (
        _text(part.get("result_signature"), limit=256)
        or _text(source.get("result_signature"), limit=256)
        or (table.result_signature if table else None)
    )
    limit = min(max(1, _integer(source.get("limit"), min(20, max(bound_row_count, 1)))), 500)
    warning_values = source.get("warnings")
    warnings = (
        [_text(item, limit=2_000) for item in warning_values]
        if isinstance(warning_values, Sequence) and not isinstance(warning_values, (str, bytes, bytearray))
        else []
    )
    legend = _record(source.get("legend"))
    return {
        "version": _text(source.get("version"), limit=64) or "answer-envelope-v1",
        "chart_type": chart_type,
        "title": _text(source.get("title"), limit=512) or "分析图表",
        "x_field": x_field,
        "y_fields": y_fields,
        "series": series[:20],
        "aggregation": _string_map(source.get("aggregation")),
        "unit": _string_map(source.get("unit")),
        "sort": [
            _text(item, limit=256)
            for item in source.get("sort", [])
            if _text(item, limit=256)
        ][:20] if isinstance(source.get("sort"), list) else [],
        "limit": limit,
        "legend": {"show": legend.get("show") is not False},
        "axis": {},
        "tooltip": {},
        "data_source_query_id": _text(source.get("data_source_query_id"), limit=256) or "answer-envelope",
        "result_signature": result_signature,
        "bound_columns": [
            _text(item, limit=256)
            for item in source.get("bound_columns", columns)
            if _text(item, limit=256)
        ][:200],
        "bound_row_count": bound_row_count,
        "null_policy": _text(source.get("null_policy"), limit=64) or "PRESERVE",
        "warnings": list(dict.fromkeys(filter(None, warnings)))[:100],
    }


def _citation_candidates(parts: Sequence[Mapping[str, Any]], response_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for part in parts:
        if part.get("type") == "citations":
            result.extend(_records(part.get("items")))
    result.extend(_records(response_payload.get("citations")))
    primary = _analysis_primary(response_payload)
    for candidate in (
        _record(primary.get("knowledge")),
        _record(primary.get("knowledge_evidence")),
        primary,
    ):
        result.extend(_records(candidate.get("citations")))
    return result


def _citations(parts: Sequence[Mapping[str, Any]], response_payload: Mapping[str, Any]) -> list[AnswerCitation]:
    result: list[AnswerCitation] = []
    seen: set[str] = set()
    for item in _citation_candidates(parts, response_payload):
        resource_id = _text(
            item.get("resource_id") or item.get("document_id") or item.get("attachment_id"),
            limit=256,
        )
        title = _filename(item.get("title") or item.get("filename") or "业务资料")
        version = _text(item.get("version") or item.get("document_version_id") or item.get("attachment_id"), limit=256)
        locator = _text(item.get("locator") or item.get("chunk_id") or resource_id, limit=512)
        if not all((resource_id, title, version, locator)):
            continue
        key = "\0".join((resource_id, version, locator))
        if key in seen:
            continue
        seen.add(key)
        citation_id = _text(item.get("id") or item.get("citation_id"), limit=256)
        if not citation_id:
            citation_id = f"citation-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:20]}"
        result.append(AnswerCitation(
            id=citation_id,
            title=title,
            version=version,
            locator=locator,
            resource_id=resource_id,
            href=_safe_citation_href(item.get("href") or item.get("url")),
        ))
    return result[:200]


def _artifacts(parts: Sequence[Mapping[str, Any]], response_payload: Mapping[str, Any]) -> list[AnswerArtifact]:
    candidates = [_record(part) for part in parts if part.get("type") == "artifact"]
    file_analysis = _record(response_payload.get("file_analysis"))
    candidates.extend(_records(file_analysis.get("artifacts")))
    result: list[AnswerArtifact] = []
    seen: set[str] = set()
    for item in candidates:
        attachment_id = _text(item.get("attachment_id") or item.get("id"), limit=256)
        filename = _filename(item.get("filename") or item.get("name") or attachment_id)
        explicit_url = item.get("download_url") or item.get("url")
        urls: list[tuple[str, str, str | None]] = []
        if explicit_url:
            urls.append((_text(item.get("kind"), limit=64) or "FILE", str(explicit_url), _text(item.get("media_type"), limit=128) or None))
        if item.get("csv_url"):
            urls.append(("CSV", str(item["csv_url"]), "text/csv"))
        if item.get("json_url"):
            urls.append(("JSON", str(item["json_url"]), "application/json"))
        for kind, raw_url, media_type in urls:
            url = _safe_api_url(raw_url)
            if not url:
                continue
            key = f"{attachment_id}\0{kind}\0{url}"
            if key in seen:
                continue
            seen.add(key)
            suffix = kind.lower()
            result.append(AnswerArtifact(
                id=f"{attachment_id or 'artifact'}:{suffix}",
                name=f"{filename} ({kind})",
                kind=kind,
                media_type=media_type,
                download_url=url,
                size_bytes=_integer(item.get("size_bytes")) if item.get("size_bytes") is not None else None,
            ))
    return result[:100]


def _file_evidence(response_payload: Mapping[str, Any]) -> list[FileEvidenceItem]:
    result: list[FileEvidenceItem] = []
    seen: set[str] = set()
    for item in _records(response_payload.get("citations")):
        attachment_id = _text(item.get("attachment_id"), limit=256)
        if not attachment_id or attachment_id in seen:
            continue
        seen.add(attachment_id)
        result.append(FileEvidenceItem(
            attachment_id=attachment_id,
            filename=_filename(item.get("filename") or attachment_id),
            kind=_text(item.get("kind"), limit=64) or "FILE",
            locator=_text(item.get("locator"), limit=512) or None,
            result_signature=_text(item.get("result_signature"), limit=256) or None,
        ))
    return result[:100]


def _locator(value: Any) -> str | None:
    if isinstance(value, str):
        return _text(value, limit=512) or None
    item = _record(value)
    labels = {
        "locator_type": "type", "page": "page", "paragraph": "paragraph",
        "table": "table", "row": "row", "column": "column", "tile": "tile",
    }
    parts = [
        f"{label}:{_text(item.get(key), limit=128)}"
        for key, label in labels.items()
        if item.get(key) is not None and _text(item.get(key), limit=128)
    ]
    return " · ".join(parts)[:512] or None


def _visual_evidence(response_payload: Mapping[str, Any], attachment_ids: Sequence[str]) -> list[VisualEvidenceItem]:
    result: list[VisualEvidenceItem] = []
    for index, item in enumerate(_records(response_payload.get("visual_evidence"))):
        claims: list[VisualClaimItem] = []
        for claim in _records(item.get("claims")):
            name = _text(claim.get("claim") or claim.get("metric"), limit=512)
            if not name:
                continue
            claims.append(VisualClaimItem(
                claim=name,
                value=claim.get("value"),
                locator=_locator(claim.get("locator")),
                confidence=_optional_float(claim.get("confidence")),
                time_range=_text(claim.get("time_range"), limit=256) or None,
                dimension=_text(claim.get("dimension"), limit=256) or None,
            ))
        result.append(VisualEvidenceItem(
            attachment_id=_text(attachment_ids[index], limit=256) if index < len(attachment_ids) else None,
            provider=_text(item.get("provider"), limit=128) or None,
            model=_text(item.get("model"), limit=256) or None,
            claims=claims[:100],
            sanitized_text=_text(item.get("sanitized_text"), limit=40_000),
            sensitive_classification=_text(item.get("sensitive_classification"), limit=32) or "NONE",
            injection_detected=bool(item.get("injection_detected")),
            signature=_text(item.get("signature") or item.get("visual_evidence_signature"), limit=256) or None,
        ))
    return result[:50]


def _agent_steps(response_payload: Mapping[str, Any]) -> list[AgentStepItem]:
    primary = _analysis_primary(response_payload)
    result: list[AgentStepItem] = []
    for index, item in enumerate(_records(primary.get("steps"))):
        detail = _record(item.get("detail"))
        code = _text(item.get("code"), limit=128)
        role = _text(item.get("agent_role"), limit=128)
        status = _text(item.get("status"), limit=64)
        if not all((code, role, status)):
            continue
        result.append(AgentStepItem(
            ordinal=max(1, _integer(item.get("ordinal"), index + 1)),
            code=code,
            agent_role=role,
            tool_name=_text(item.get("tool_name"), limit=128) or None,
            status=status,
            duration_ms=_integer(item.get("duration_ms")),
            result_signature=_text(detail.get("result_signature"), limit=256) or None,
            error_code=_text(item.get("error_code") or detail.get("error_code"), limit=128) or None,
        ))
    return result[:100]


def _followups(parts: Sequence[Mapping[str, Any]], query: Mapping[str, Any] | None) -> list[str]:
    result: list[str] = []
    for part in parts:
        if part.get("type") == "text" and part.get("role") == "followups":
            result.extend(str(part.get("text") or "").splitlines())
    if query is not None:
        values = query.get("recommended_questions")
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
            result.extend(str(item) for item in values)
        narrative = _record(query.get("narrative"))
        values = narrative.get("recommended_questions")
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
            result.extend(str(item) for item in values)
    return list(dict.fromkeys(filter(None, (_text(item, limit=1_000) for item in result))))[:20]


def _warnings(
    status: str,
    parts: Sequence[Mapping[str, Any]],
    query: Mapping[str, Any] | None,
    trace_payload: Mapping[str, Any],
) -> list[AnswerWarning]:
    candidates: list[tuple[str, str, str]] = []
    for part in parts:
        if part.get("type") == "warning":
            candidates.append((
                _text(part.get("code"), limit=128) or "ANSWER_WARNING",
                _text(part.get("message"), limit=2_000),
                _text(part.get("severity"), limit=32) or "WARNING",
            ))
    if query is not None:
        plan = _record(query.get("plan"))
        for item in plan.get("warnings") or []:
            candidates.append(("QUERY_PLAN_WARNING", _text(item, limit=2_000), "WARNING"))
        chart = _record(query.get("chart_spec"))
        for item in chart.get("warnings") or []:
            candidates.append(("CHART_WARNING", _text(item, limit=2_000), "WARNING"))
        execution = _record(query.get("execution"))
        if execution.get("truncated"):
            candidates.append(("RESULT_TRUNCATED", "结果已达到返回行数上限。", "INFO"))
    if status == "PARTIAL":
        candidates.append(("PARTIAL_ANSWER", "部分证据或步骤未完成，当前回答为受控部分结果。", "WARNING"))
    if trace_payload.get("fallback_reason"):
        candidates.append(("CONTROLLED_FALLBACK", "本次回答使用了受控回退路径。", "INFO"))
    result: list[AnswerWarning] = []
    seen: set[tuple[str, str]] = set()
    for code, message, severity in candidates:
        if not message or (code, message) in seen:
            continue
        seen.add((code, message))
        result.append(AnswerWarning(code=code, message=message, severity=severity))
    return result[:100]


def _errors(status: str, content: str, error_code: str | None, parts: Sequence[Mapping[str, Any]]) -> list[AnswerError]:
    candidates: list[tuple[str, str, bool]] = []
    for part in parts:
        if part.get("type") == "error":
            candidates.append((
                _text(part.get("code"), limit=128) or "CHAT_RUN_FAILED",
                _text(part.get("message"), limit=2_000) or "回答未完成。",
                bool(part.get("retryable")),
            ))
    if status not in _SUCCESS and not candidates:
        candidates.append((_text(error_code, limit=128) or status or "CHAT_RUN_FAILED", _text(content, limit=2_000) or "回答未完成。", False))
    result: list[AnswerError] = []
    seen: set[tuple[str, str]] = set()
    for code, message, retryable in candidates:
        if (code, message) in seen:
            continue
        seen.add((code, message))
        result.append(AnswerError(code=code, message=message, retryable=retryable))
    return result[:100]


def _cost_and_latency(trace_payload: Mapping[str, Any]) -> tuple[AnswerCost, AnswerLatency, str | None, str | None]:
    model_call = _record(trace_payload.get("model_call"))
    usage = _record(model_call.get("usage"))
    cost = AnswerCost(
        input_tokens=_integer(usage.get("input_tokens")),
        cached_input_tokens=_integer(usage.get("cached_input_tokens")),
        output_tokens=_integer(usage.get("output_tokens")),
        total_tokens=_integer(usage.get("total_tokens")),
        amount_cny=_float(model_call.get("cost_cny")),
        exact=bool(usage.get("exact")),
        pricing_version=_text(model_call.get("pricing_version"), limit=128) or None,
    )
    latency = AnswerLatency(
        total_ms=_integer(trace_payload.get("elapsed_ms")),
        model_ms=_integer(model_call.get("latency_ms")) if model_call.get("latency_ms") is not None else None,
        time_to_first_token_ms=(
            _integer(model_call.get("time_to_first_token_ms"))
            if model_call.get("time_to_first_token_ms") is not None else None
        ),
    )
    provider = _text(trace_payload.get("model_provider") or model_call.get("resolved_provider"), limit=128) or None
    model = _text(trace_payload.get("model_name") or model_call.get("resolved_model"), limit=256) or None
    return cost, latency, provider, model


def _verification(
    query: Mapping[str, Any] | None,
    response_payload: Mapping[str, Any],
    visual_evidence: Sequence[VisualEvidenceItem],
    table: AnswerTable | None,
) -> AnswerVerification:
    checks: list[VerificationCheck] = []
    result_signature = table.result_signature if table else None
    if query is not None:
        guard = _record(query.get("guard"))
        if "allowed" in guard:
            checks.append(VerificationCheck(code="SQL_GUARD", passed=bool(guard.get("allowed")), detail="只读 SQL 安全校验"))
        oracle = _record(query.get("oracle"))
        oracle_status = _text(oracle.get("status"), limit=64).upper()
        if oracle_status:
            checks.append(VerificationCheck(code="RESULT_ORACLE", passed=oracle_status == "PASSED", detail=oracle_status))
        execution = _record(query.get("execution"))
        result_signature = _text(execution.get("result_signature"), limit=256) or result_signature
    grounded = _record(response_payload.get("grounded_answer_guard"))
    if "passed" in grounded:
        checks.append(VerificationCheck(
            code="CITATION_ANSWER_GUARD",
            passed=bool(grounded.get("passed")),
            detail=_text(grounded.get("reason"), limit=1_000) or "引用与回答绑定校验",
        ))
    primary = _analysis_primary(response_payload)
    for code, passed in _record(primary.get("verification")).items():
        if isinstance(passed, bool):
            checks.append(VerificationCheck(code=_text(code, limit=128) or "AGENT_VERIFICATION", passed=passed))
    for item in visual_evidence:
        checks.append(VerificationCheck(
            code="VISUAL_EVIDENCE_SAFETY",
            passed=not item.injection_detected,
            detail=item.signature or "签名视觉证据",
        ))
    if not checks:
        status = "NOT_RUN"
    elif any(check.passed is False for check in checks):
        status = "FAILED"
    elif all(check.passed is True for check in checks):
        status = "VERIFIED"
    else:
        status = "PARTIAL"
    return AnswerVerification(status=status, checks=checks[:100], result_signature=result_signature)


class AnswerEnvelopeAdapter:
    """Additive Phase4 adapter over Phase3 response/message payloads.

    The adapter is deliberately side-effect free: it never calls a router, model,
    connector, database, trace writer or SSE publisher. It also copies only named
    public fields, so provider reasoning and private runtime payloads have no path
    into the product renderer.
    """

    @staticmethod
    def build(
        *,
        answer_id: str,
        conversation_id: str,
        message_id: str,
        trace_id: str,
        route: Any,
        status: str,
        content: str,
        response_payload: Mapping[str, Any] | None = None,
        trace_payload: Mapping[str, Any] | None = None,
        message_parts: Iterable[Mapping[str, Any]] | None = None,
        result_semantic: Any = None,
        error_code: str | None = None,
        attachment_ids: Sequence[str] = (),
    ) -> AnswerEnvelope:
        response = _record(response_payload)
        trace = _record(trace_payload)
        public_parts = _parts(message_parts, response)
        query = _find_query_payload(response)
        table = _table(public_parts, response, query)
        chart = _chart(public_parts, query, response, table)
        visual = _visual_evidence(response, attachment_ids)
        cost, latency, provider, model = _cost_and_latency(trace)
        normalized_status = _text(status, limit=64) or "FAILED"
        markdown = _text(response.get("markdown"), limit=100_000) or _text(content, limit=100_000)
        evidence_sql = _text(_first_part(public_parts, "evidence").get("sql"), limit=100_000)
        if not evidence_sql and query is not None:
            guard = _record(query.get("guard"))
            plan = _record(query.get("plan"))
            evidence_sql = _text(guard.get("normalized_sql") or plan.get("normalized_sql"), limit=100_000)
        return AnswerEnvelope(
            answer_id=_text(answer_id, limit=256),
            conversation_id=_text(conversation_id, limit=256),
            message_id=_text(message_id, limit=256),
            trace_id=_text(trace_id or trace.get("trace_id"), limit=256),
            route=_route(route),
            status=normalized_status,
            result_semantic=_semantic(result_semantic or response.get("result_semantic"), normalized_status),
            summary=_summary(content, public_parts, response),
            markdown=markdown,
            kpis=_kpis(public_parts, query),
            insights=_insights(public_parts, query),
            sql=evidence_sql or None,
            table=table,
            chart=chart,
            citations=_citations(public_parts, response),
            artifacts=_artifacts(public_parts, response),
            file_evidence=_file_evidence(response),
            visual_evidence=visual,
            agent_steps=_agent_steps(response),
            warnings=_warnings(normalized_status, public_parts, query, trace),
            errors=_errors(normalized_status, content, error_code, public_parts),
            cost=cost,
            latency=latency,
            provider=provider,
            model=model,
            verification=_verification(query, response, visual, table),
            follow_up_suggestions=_followups(public_parts, query),
        )


def build_answer_envelope(**kwargs: Any) -> AnswerEnvelope:
    return AnswerEnvelopeAdapter.build(**kwargs)


__all__ = ["AnswerEnvelopeAdapter", "build_answer_envelope"]
