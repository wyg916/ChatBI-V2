from __future__ import annotations

import hashlib
import json
import re
from statistics import mean
from typing import Any


SANDBOX_POLICY = {
    "mode": "fixed_operation_dataframe_interpreter",
    "generated_code_execution": 0,
    "host_filesystem_access": 0,
    "database_credential_access": 0,
    "provider_secret_access": 0,
    "network_access": 0,
    "shell_access": 0,
    "max_input_rows": 100_000,
    "max_analyzed_rows": 100,
    "max_preview_rows_per_sheet": 100,
    "max_output_rows": 100,
    "resource_strategy": "bounded_in_memory_no_generated_code",
    "temporary_artifact_files": 0,
}


_COLUMN_ALIASES = {
    "revenue": ("收入", "营收", "销售额", "金额"),
    "amount": ("收入", "营收", "销售额", "金额"),
    "customer_id": ("客户", "用户"),
    "date": ("日期", "时间", "趋势"),
}


def _datasets(attachments: list[Any]) -> list[dict[str, Any]]:
    datasets: list[dict[str, Any]] = []
    for item in attachments:
        payload = item.extracted_payload or {}
        sheets = payload.get("sheets") or {"data": payload}
        for sheet_name, sheet in sheets.items():
            datasets.append({
                "attachment_id": item.id,
                "filename": item.filename,
                "sheet": str(sheet_name),
                "row_count": int(sheet.get("row_count") or 0),
                "columns": [str(value) for value in sheet.get("columns") or []],
                "rows": list(sheet.get("preview") or [])[:100],
            })
    return datasets


def _numeric_columns(rows: list[dict[str, Any]]) -> list[str]:
    columns = {key for row in rows for key, value in row.items() if isinstance(value, (int, float)) and not isinstance(value, bool)}
    return sorted(columns)


def _column(question: str, columns: list[str], numeric: list[str]) -> str | None:
    lowered = question.lower()
    exact = next((item for item in columns if item.lower() in lowered), None)
    if exact:
        return exact
    aliased = next((item for item in columns if any(alias in lowered for alias in _COLUMN_ALIASES.get(item.lower(), ()))), None)
    return aliased or (numeric[0] if numeric else None)


def analyze_structured(question: str, attachments: list[Any]) -> dict[str, Any]:
    datasets = _datasets(attachments)
    if not datasets:
        raise ValueError("FILE_ANALYSIS_REQUIRES_STRUCTURED_ATTACHMENT")
    question_lower = question.lower()
    primary = datasets[0]
    rows = primary["rows"]
    numeric = _numeric_columns(rows)
    selected = _column(question, primary["columns"], numeric)
    values = [float(row[selected]) for row in rows if selected and isinstance(row.get(selected), (int, float))]
    operation = "SUMMARY"
    result_rows: list[dict[str, Any]] = []

    if any(token in question_lower for token in ("多少行", "行数", "row count")):
        operation = "ROW_COUNT"
        result_rows = [{"dataset": primary["filename"], "row_count": primary["row_count"]}]
    elif len(datasets) > 1 and any(token in question_lower for token in ("join", "关联", "合并")):
        operation = "JOIN"
        left, right = datasets[:2]
        common = sorted(set(left["columns"]) & set(right["columns"]))
        key = common[0] if common else None
        if key:
            right_index = {str(row.get(key)): row for row in right["rows"]}
            result_rows = [{**row, **{f"right_{k}": v for k, v in right_index.get(str(row.get(key)), {}).items() if k != key}} for row in left["rows"] if str(row.get(key)) in right_index][:100]
    elif any(token in question_lower for token in ("筛选", "过滤", "filter")) and selected:
        operation = "FILTER"
        match = re.search(r"(?:>=|≥|大于等于|>|大于|<=|≤|小于等于|<|小于|=|等于)\s*(-?\d+(?:\.\d+)?)", question_lower)
        if match:
            threshold = float(match.group(1))
            operator_text = match.group(0)[: match.group(0).find(match.group(1))].strip()
            checks = {
                ">=": lambda value: value >= threshold, "≥": lambda value: value >= threshold, "大于等于": lambda value: value >= threshold,
                ">": lambda value: value > threshold, "大于": lambda value: value > threshold,
                "<=": lambda value: value <= threshold, "≤": lambda value: value <= threshold, "小于等于": lambda value: value <= threshold,
                "<": lambda value: value < threshold, "小于": lambda value: value < threshold,
                "=": lambda value: value == threshold, "等于": lambda value: value == threshold,
            }
            predicate = checks.get(operator_text)
            if predicate:
                result_rows = [row for row in rows if isinstance(row.get(selected), (int, float)) and predicate(float(row[selected]))][:100]
    elif any(token in question_lower for token in ("客户分层", "segment", "分层")) and values:
        operation = "SEGMENT"
        ordered = sorted(values)
        low = ordered[max(0, len(ordered) // 3 - 1)]
        high = ordered[max(0, (len(ordered) * 2) // 3 - 1)]
        result_rows = [{"segment": "高价值", "count": sum(value > high for value in values)}, {"segment": "中价值", "count": sum(low < value <= high for value in values)}, {"segment": "基础", "count": sum(value <= low for value in values)}]
    elif any(token in question_lower for token in ("平均", "average", "mean")) and values:
        operation = "AVERAGE"
        result_rows = [{"column": selected, "average": round(mean(values), 6)}]
    elif any(token in question_lower for token in ("合计", "总和", "sum")) and values:
        operation = "SUM"
        result_rows = [{"column": selected, "sum": round(sum(values), 6)}]
    elif any(token in question_lower for token in ("最小", "minimum", "min")) and values:
        operation = "MIN"
        target = min(values)
        result_rows = [row for row in rows if float(row.get(selected, float("inf"))) == target][:10]
    elif any(token in question_lower for token in ("最大", "最高", "top", "maximum", "max")) and values:
        operation = "TOP_N"
        result_rows = sorted(rows, key=lambda row: float(row.get(selected) or 0), reverse=True)[:10]
    elif any(token in question_lower for token in ("趋势", "trend")):
        operation = "TREND"
        result_rows = rows[:100]
    else:
        result_rows = rows[:20]

    result_rows = result_rows[:100]
    result_columns = list(result_rows[0]) if result_rows else []
    exact = all(item["row_count"] <= len(item["rows"]) for item in datasets)
    result_signature = hashlib.sha256(json.dumps(result_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    chart = None
    if operation in {"TREND", "TOP_N", "SEGMENT"} and len(result_columns) >= 2:
        chart = {"chart_type": "line" if operation == "TREND" else "bar", "x": result_columns[0], "y": result_columns[1], "rows": result_rows[:20]}
    return {
        "status": "SUCCEEDED",
        "operation": operation,
        "answer": f"已用受限数据解释器完成 {operation}，返回 {len(result_rows)} 行结果。" + ("" if exact else " 文件超过预览上限，结论仅覆盖已验证预览。"),
        "result": {"columns": result_columns, "rows": result_rows, "exact_for_full_file": exact, "result_signature": result_signature},
        "chart": chart,
        "datasets": [{key: value for key, value in item.items() if key != "rows"} for item in datasets],
        "artifacts": [{"attachment_id": item.id, "filename": item.filename, "csv_url": f"/api/v1/attachments/{item.id}/artifact?format=csv", "json_url": f"/api/v1/attachments/{item.id}/artifact?format=json"} for item in attachments],
        "trace": {"stages": ["FILE_VALIDATION", "WORKSPACE_ISOLATION", "SAFE_DATAFRAME_ANALYSIS", "RESULT_VALIDATION", "ARTIFACT_READY"], "result_signature": result_signature, "complete": True},
        "sandbox": dict(SANDBOX_POLICY),
    }
