from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "evaluation" / "golden" / "v13-phase5-data-100.json"
ROOT_CAUSE_CLASSES = {
    "ROUTING",
    "SCHEMA_LINKING",
    "SEMANTIC",
    "TIME_RANGE",
    "FILTER",
    "AGGREGATION",
    "GROUP_BY",
    "ORDER_BY",
    "TOP_N",
    "TIE",
    "NULL",
    "SQL_GENERATION",
    "EXECUTOR",
    "ORACLE",
    "VERIFICATION",
    "GOLDEN_DEFECT",
    "OTHER",
}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load_cases(manifest_path: Path) -> dict[str, dict[str, Any]]:
    manifest = _read_json(manifest_path)
    base_path = (REPO_ROOT / str(manifest.get("base_manifest") or "")).resolve()
    if REPO_ROOT.resolve() not in base_path.parents:
        raise ValueError("Data100 base manifest must remain inside the repository")
    base = _read_json(base_path)
    base_cases = copy.deepcopy(base.get("cases") or [])
    overrides = manifest.get("base_case_question_overrides") or {}
    for case in base_cases:
        case_id = str(case.get("id") or "")
        if case_id in overrides:
            case["question"] = str(overrides[case_id])
    cases = base_cases + copy.deepcopy(manifest.get("extension_cases") or [])
    if len(cases) != 100 or len({str(case.get("id") or "") for case in cases}) != 100:
        raise ValueError("Data100 manifest must resolve to 100 unique cases")
    return {str(case["id"]): case for case in cases}


def _category_root(category: str) -> str:
    mapping = {
        "tie_topn": "TIE",
        "topn_join": "TOP_N",
        "filter_group_topn": "TOP_N",
        "extreme_value": "ORDER_BY",
        "null": "NULL",
        "empty_result": "ORACLE",
        "duplicate_grain": "GROUP_BY",
        "group": "GROUP_BY",
        "group_join": "GROUP_BY",
        "multi_dimension": "GROUP_BY",
        "multi_metric_dimension": "GROUP_BY",
        "simple_aggregate": "AGGREGATION",
        "derived_metric": "AGGREGATION",
        "metric_combination": "AGGREGATION",
        "contribution": "AGGREGATION",
        "ratio_zero_safe": "AGGREGATION",
        "category_filter": "FILTER",
        "complex_filter": "FILTER",
        "filter_join": "FILTER",
        "multi_filter": "FILTER",
        "time": "TIME_RANGE",
        "time_trend": "TIME_RANGE",
        "natural_month": "TIME_RANGE",
        "cross_month": "TIME_RANGE",
        "cross_year": "TIME_RANGE",
        "quarter_boundary": "TIME_RANGE",
        "boundary": "TIME_RANGE",
        "month_over_month": "TIME_RANGE",
        "year_over_year": "TIME_RANGE",
        "multi_dimension_time": "TIME_RANGE",
        "join": "SCHEMA_LINKING",
        "complex_join": "SCHEMA_LINKING",
        "ambiguous": "SEMANTIC",
        "nonexistent_metric": "SEMANTIC",
        "wrong_field": "SCHEMA_LINKING",
    }
    return mapping.get(category, "OTHER")


def classify_root_cause(result: dict[str, Any], case: dict[str, Any]) -> str:
    failures = {str(value) for value in result.get("failures") or []}
    category = str(case.get("category") or result.get("category") or "")
    if any(value.startswith("ASK_HTTP_") for value in failures) or "ACTUAL_ROUTE_NOT_DATA_QUERY" in failures:
        root = "ROUTING"
    elif "SEMANTIC_TIME_RANGE_MISMATCH" in failures:
        root = "TIME_RANGE"
    elif "SEMANTIC_FILTERS_MISMATCH" in failures:
        root = "FILTER"
    elif "SEMANTIC_ENTITIES_MISMATCH" in failures or "SEMANTIC_DIMENSIONS_MISMATCH" in failures:
        root = "SCHEMA_LINKING"
    elif "SEMANTIC_METRICS_MISMATCH" in failures:
        root = "SEMANTIC"
    elif "SQL_GUARD_NOT_READ_ONLY_ALLOWED" in failures:
        root = "SQL_GENERATION"
    elif "SQL_EXECUTION_OR_SIGNATURE_NOT_PROVEN" in failures:
        root = "EXECUTOR"
    elif "RESULT_SIGNATURE_NOT_INDEPENDENTLY_REPRODUCED" in failures:
        root = "VERIFICATION"
    elif "VERIFY_HTTP_422" in failures or "INTERNAL_VERIFICATION_QUERY_NOT_PASSED" in failures:
        root = "VERIFICATION"
    elif "FAIL_CLOSED_CASE_EXECUTED_SQL" in failures or "FAIL_CLOSED_STATUS_MISMATCH" in failures:
        root = _category_root(category)
        if root == "OTHER":
            root = "SEMANTIC"
    else:
        root = _category_root(category)
        if root == "OTHER" and (
            "PIPELINE_ORACLE_NOT_PASSED" in failures
            or "EXPECTED_RESULT_ORACLE_NOT_PASSED" in failures
            or "EXPECTED_ACTUAL_VALUE_MISMATCH" in failures
        ):
            root = "ORACLE"
    if root not in ROOT_CAUSE_CLASSES:
        raise AssertionError(f"Unrecognized root cause class: {root}")
    return root


def cluster_failures(result_path: Path, manifest_path: Path) -> dict[str, Any]:
    source = _read_json(result_path)
    data100 = source.get("core_data100") if isinstance(source.get("core_data100"), dict) else source
    results = data100.get("cases") if isinstance(data100.get("cases"), list) else []
    if data100.get("total") != 100 or len(results) != 100:
        raise ValueError("Data100 result must contain exactly 100 executed cases")
    manifest_cases = _load_cases(manifest_path)
    failures: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, dict) or result.get("status") == "PASS":
            continue
        case_id = str(result.get("id") or "")
        case = manifest_cases.get(case_id)
        if case is None:
            raise ValueError(f"Unknown Data100 case in result: {case_id}")
        failures.append({
            "CASE_ID": case_id,
            "QUESTION": case.get("question"),
            "ROUTE": result.get("actual_route"),
            "EXPECTED_SQL": case.get("expected_sql"),
            "ACTUAL_SQL": result.get("normalized_sql") or result.get("generated_sql"),
            "EXPECTED_ROWS": case.get("expected_result"),
            "ACTUAL_ROWS": result.get("actual_rows"),
            "ROOT_CAUSE_CLASS": classify_root_cause(result, case),
            "CATEGORY": case.get("category"),
            "PIPELINE_STATUS": result.get("pipeline_status"),
            "ERROR_CODE": result.get("error_code"),
            "FAILURE_CODES": list(result.get("failures") or []),
        })
    distribution = Counter(str(item["ROOT_CAUSE_CLASS"]) for item in failures)
    return {
        "schema_version": "chatbi-v1.3-phase5-data100-failure-cluster-v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_result": result_path.name,
        "source_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        "tested_sha": source.get("tested_sha"),
        "source_status": data100.get("status"),
        "source_total": data100.get("total"),
        "source_passed": data100.get("passed"),
        "source_failed": data100.get("failed"),
        "failure_count": len(failures),
        "root_cause_distribution": dict(sorted(distribution.items())),
        "cases": failures,
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Data100 Level0 Failure Cluster",
        "",
        f"- Tested SHA: `{payload.get('tested_sha')}`",
        f"- Historical result: {payload.get('source_passed')}/{payload.get('source_total')} PASS",
        f"- Clustered failures: {payload.get('failure_count')}",
        "- This report preserves the original result and does not change Golden or Oracle thresholds.",
        "",
        "## Root-cause distribution",
        "",
        "| Class | Cases |",
        "| --- | ---: |",
    ]
    for root, count in (payload.get("root_cause_distribution") or {}).items():
        lines.append(f"| {root} | {count} |")
    lines.extend(["", "## Cases", "", "| Case | Category | Root cause | Route | Failure codes |", "| --- | --- | --- | --- | --- |"])
    for case in payload.get("cases") or []:
        codes = ", ".join(case.get("FAILURE_CODES") or []).replace("|", "\\|")
        lines.append(
            f"| {case.get('CASE_ID')} | {case.get('CATEGORY')} | {case.get('ROOT_CAUSE_CLASS')} | "
            f"{case.get('ROUTE')} | {codes} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Cluster preserved ChatBI Phase5 Data100 failures")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    payload = cluster_failures(args.input.resolve(), args.manifest.resolve())
    _atomic_text(args.output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _atomic_text(args.summary, _markdown(payload))
    print(json.dumps({
        "status": "PASS",
        "source_passed": payload["source_passed"],
        "source_failed": payload["source_failed"],
        "failure_count": payload["failure_count"],
        "root_cause_distribution": payload["root_cause_distribution"],
        "output": str(args.output.resolve()),
        "summary": str(args.summary.resolve()),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
