from __future__ import annotations

import re
from statistics import mean

from .contracts import FileAnalysisResult, ParsedAttachment, TableData, canonical_sha256


_PANDASAI_MARKERS = (
    "相关系数", "correlation", "回归", "regression", "滚动", "rolling",
    "透视", "pivot", "聚类", "cluster", "异常检测", "forecast",
)


def requires_pandasai_runtime(question: str) -> bool:
    lowered = question.lower()
    return any(marker in lowered for marker in _PANDASAI_MARKERS)


def _all_tables(files: list[ParsedAttachment]) -> list[TableData]:
    return [table for item in files for table in item.tables]


def _numeric_columns(table: TableData) -> list[str]:
    return [
        column for column in table.columns
        if any(isinstance(row.get(column), (int, float)) and not isinstance(row.get(column), bool) for row in table.rows)
    ]


def _selected_column(question: str, table: TableData) -> str | None:
    lowered = question.lower()
    numeric = _numeric_columns(table)
    return next((column for column in numeric if column.lower() in lowered), numeric[0] if numeric else None)


def _question_scoped_rows(question: str, table: TableData) -> list[dict]:
    """Apply explicit categorical values from the question before aggregation."""
    rows = list(table.rows)
    lowered = question.lower()
    for column in table.columns:
        values = {
            str(row.get(column)).strip()
            for row in rows
            if row.get(column) is not None
            and not isinstance(row.get(column), (int, float, bool))
        }
        mentioned = sorted(
            (value for value in values if value and value.lower() in lowered),
            key=len,
            reverse=True,
        )
        if mentioned:
            allowed = set(mentioned)
            rows = [row for row in rows if str(row.get(column)).strip() in allowed]
    return rows


def analyze_structured_files(question: str, files: list[ParsedAttachment]) -> FileAnalysisResult:
    tables = _all_tables(files)
    if not tables:
        raise ValueError("FILE_ANALYSIS_REQUIRES_STRUCTURED_ATTACHMENT")
    if requires_pandasai_runtime(question):
        raise ValueError("PANDASAI_RUNTIME_REQUIRED")
    table = tables[0]
    selected = _selected_column(question, table)
    lowered = question.lower()
    rows = _question_scoped_rows(question, table)
    values = [float(row[selected]) for row in rows if selected and isinstance(row.get(selected), (int, float))]
    operation = "SUMMARY"
    result_rows: list[dict] = []

    if any(token in lowered for token in ("多少行", "行数", "row count")):
        operation = "ROW_COUNT"
        result_rows = [{"dataset": table.name, "row_count": table.row_count}]
    elif len(tables) > 1 and any(token in lowered for token in ("join", "关联", "合并")):
        operation = "JOIN"
        left, right = tables[:2]
        key = next((column for column in left.columns if column in right.columns), None)
        if key is None:
            raise ValueError("FILE_JOIN_KEY_NOT_FOUND")
        right_index: dict[str, list[dict]] = {}
        for right_row in right.rows:
            right_index.setdefault(str(right_row.get(key)), []).append(dict(right_row))
        estimated_rows = sum(len(right_index.get(str(row.get(key)), ())) for row in left.rows)
        if estimated_rows > 100_000:
            raise ValueError("FILE_JOIN_RESULT_LIMIT_EXCEEDED")
        result_rows = [
            {
                **row,
                **{f"right_{name}": value for name, value in right_row.items() if name != key},
            }
            for row in left.rows
            for right_row in right_index.get(str(row.get(key)), ())
        ]
    elif any(token in lowered for token in ("筛选", "过滤", "filter")) and selected:
        operation = "FILTER"
        match = re.search(r"(>=|≥|大于等于|>|大于|<=|≤|小于等于|<|小于|=|等于)\s*(-?\d+(?:\.\d+)?)", lowered)
        if not match:
            raise ValueError("FILE_FILTER_THRESHOLD_REQUIRED")
        operator, raw_threshold = match.groups()
        threshold = float(raw_threshold)
        checks = {
            ">=": lambda value: value >= threshold, "≥": lambda value: value >= threshold, "大于等于": lambda value: value >= threshold,
            ">": lambda value: value > threshold, "大于": lambda value: value > threshold,
            "<=": lambda value: value <= threshold, "≤": lambda value: value <= threshold, "小于等于": lambda value: value <= threshold,
            "<": lambda value: value < threshold, "小于": lambda value: value < threshold,
            "=": lambda value: value == threshold, "等于": lambda value: value == threshold,
        }
        result_rows = [row for row in rows if isinstance(row.get(selected), (int, float)) and checks[operator](float(row[selected]))]
    elif any(token in lowered for token in ("按", "group by", "每个")) and selected:
        operation = "GROUP_SUM"
        group = next((column for column in table.columns if column != selected and column.lower() in lowered), None)
        if group is None:
            aliases = {"region": ("地区", "区域"), "date": ("日期", "时间")}
            group = next((column for column in table.columns if any(alias in lowered for alias in aliases.get(column.lower(), ()))), None)
        if group is None:
            raise ValueError("FILE_GROUP_COLUMN_REQUIRED")
        grouped: dict[str, float] = {}
        for row in rows:
            if isinstance(row.get(selected), (int, float)):
                key = str(row.get(group))
                grouped[key] = grouped.get(key, 0.0) + float(row[selected])
        result_rows = [{group: key, f"{selected}_sum": round(value, 6)} for key, value in sorted(grouped.items())]
    elif any(token in lowered for token in ("平均", "average", "mean")) and values:
        operation = "AVERAGE"
        result_rows = [{"column": selected, "average": round(mean(values), 6)}]
    elif any(token in lowered for token in ("合计", "总和", "sum")) and values:
        operation = "SUM"
        result_rows = [{"column": selected, "sum": round(sum(values), 6)}]
    elif any(token in lowered for token in ("最大", "最高", "top", "maximum", "max")) and values:
        operation = "TOP_N"
        result_rows = sorted(rows, key=lambda row: float(row.get(selected) or 0), reverse=True)[:10]
    else:
        result_rows = rows

    signature = canonical_sha256(result_rows)
    answer = f"已对完整文件执行 {operation}，返回 {len(result_rows)} 行。"
    if operation == "SUM":
        answer = f"{selected} 合计为 {result_rows[0]['sum']:g}。"
    elif operation == "AVERAGE":
        answer = f"{selected} 平均值为 {result_rows[0]['average']:g}。"
    return FileAnalysisResult(
        operation=operation,
        rows=tuple(result_rows),
        answer=answer,
        exact_for_full_file=True,
        result_signature=signature,
        source_signatures=tuple(item.result_signature for item in files),
    )
