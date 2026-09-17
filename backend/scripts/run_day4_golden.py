from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ORIGINAL_SHA256 = "741da55b7dd41046a6f8411522a3cf92afb45ca1ac38b90b202b49c87f8eef0e"
RUNTIME_MODEL_NAMES = {
    "postgresql": "新能源经营分析",
    "mysql": "新能源经营分析（MySQL兼容）",
}


def api(base_url: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {detail}") from exc


def manifest_hash(manifest: dict[str, Any]) -> str:
    value = copy.deepcopy(manifest)
    value["manifest_sha256"] = None
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def select_runtime(base_url: str, dialect: str) -> tuple[str, str]:
    sources = api(base_url, "GET", "/api/v1/datasources")
    models = api(base_url, "GET", "/api/v1/semantic-models")
    datasource = next(item for item in sources if item["type"] == dialect)
    model = next(
        item for item in models
        if item["datasource_id"] == datasource["id"]
        and item["name"] == RUNTIME_MODEL_NAMES[dialect]
        and item["status"] == "PUBLISHED"
    )
    return datasource["id"], model["id"]


def ask(base_url: str, question: str, datasource_id: str, semantic_model_id: str) -> dict[str, Any]:
    return api(base_url, "POST", "/api/v1/ask", {
        "question": question,
        "datasource_id": datasource_id,
        "semantic_model_id": semantic_model_id,
        "row_limit": 500,
    })


def verify(base_url: str, actual: dict[str, Any], case: dict[str, Any], prefix: str = "") -> bool:
    result_key = f"{prefix}expected_result"
    signature_key = f"{prefix}expected_signature"
    expected_rows = case.get(result_key) or []
    response = api(base_url, "POST", f"/api/v1/queries/{actual['id']}/verify", {
        "expected": {
            "columns": list(expected_rows[0]) if expected_rows else list(actual.get("execution", {}).get("columns") or []),
            "rows": expected_rows,
            "tolerance": 0.0001,
            "order_independent": True,
            "metric_names": case["expected_metrics"] if not prefix else [],
            "dimension_names": case["expected_dimensions"] if not prefix else [],
            "expected_signature": case.get(signature_key),
        }
    })
    return response.get("oracle", {}).get("status") == "PASSED"


def freeze(base_url: str, manifest: dict[str, Any], original: dict[str, Any]) -> None:
    if manifest.get("cases", [])[:20] != original.get("cases", []):
        raise RuntimeError("Original Golden 20 cases changed; refusing to freeze")
    pg_source, pg_model = select_runtime(base_url, "postgresql")
    mysql_source, mysql_model = select_runtime(base_url, "mysql")
    for index, item in enumerate(manifest["cases"]):
        if index >= 20:
            expected = ask(base_url, item["expected_sql"], pg_source, pg_model)
            if expected.get("execution", {}).get("status") != "SUCCEEDED":
                raise RuntimeError(f"{item['id']} PostgreSQL expected SQL failed: {expected.get('error_code')} {expected.get('error_message')}")
            item["expected_result"] = expected["execution"]["rows"]
            item["expected_signature"] = expected["execution"]["result_signature"]
        if item.get("mysql_expected_sql") and not item.get("mysql_expected_signature"):
            expected = ask(base_url, item["mysql_expected_sql"], mysql_source, mysql_model)
            if expected.get("execution", {}).get("status") != "SUCCEEDED":
                raise RuntimeError(f"{item['id']} MySQL expected SQL failed: {expected.get('error_code')} {expected.get('error_message')}")
            item["mysql_expected_result"] = expected["execution"]["rows"]
            item["mysql_expected_signature"] = expected["execution"]["result_signature"]
    manifest["frozen"] = True
    manifest["frozen_at"] = datetime.now(timezone.utc).isoformat()
    manifest["manifest_sha256"] = manifest_hash(manifest)


def semantic_match(case: dict[str, Any], actual: dict[str, Any]) -> tuple[bool, list[str]]:
    plan = actual.get("plan") or {}
    reasons: list[str] = []
    for key, expected_key in (("metrics", "expected_metrics"), ("dimensions", "expected_dimensions")):
        if plan.get(key, []) != case.get(expected_key, []):
            reasons.append(f"{key}: {plan.get(key, [])} != {case.get(expected_key, [])}")
    if not set(case.get("expected_entities", [])).issubset(set(plan.get("selected_entities", []))):
        reasons.append("selected_entities missing expected values")
    actual_filters = {(item["field"], str(item.get("value"))) for item in plan.get("filters", [])}
    expected_filters = {(item["field"], str(item.get("value"))) for item in case.get("expected_filters", [])}
    if not expected_filters.issubset(actual_filters):
        reasons.append("filters missing expected values")
    expected_time = case.get("expected_time_range")
    if expected_time:
        actual_time = plan.get("time_range") or {}
        if actual_time.get("start") != expected_time["start"] or actual_time.get("end_exclusive") != expected_time["end_exclusive"]:
            reasons.append("time_range mismatch")
    return not reasons, reasons


def evaluate(base_url: str, manifest: dict[str, Any], original: dict[str, Any]) -> dict[str, Any]:
    if not manifest.get("frozen") or manifest_hash(manifest) != manifest.get("manifest_sha256"):
        raise RuntimeError("Golden 50 manifest is not frozen or its SHA-256 is invalid")
    if len(manifest.get("cases") or []) != 50 or manifest["cases"][:20] != original["cases"]:
        raise RuntimeError("Golden 50 traceability check failed")
    pg_source, pg_model = select_runtime(base_url, "postgresql")
    mysql_source, mysql_model = select_runtime(base_url, "mysql")
    postgres_results: list[dict[str, Any]] = []
    for item in manifest["cases"]:
        actual = ask(base_url, item["question"], pg_source, pg_model)
        execution_ok = actual.get("execution", {}).get("status") == "SUCCEEDED"
        result_ok = verify(base_url, actual, item) if execution_ok else False
        semantic_ok, semantic_reasons = semantic_match(item, actual)
        postgres_results.append({
            "id": item["id"], "execution_ok": execution_ok, "result_ok": result_ok,
            "semantic_ok": semantic_ok, "semantic_reasons": semantic_reasons,
            "query_id": actual.get("id"), "error_code": actual.get("error_code"),
            "actual_signature": actual.get("execution", {}).get("result_signature"),
        })
    mysql_results: list[dict[str, Any]] = []
    for item in [case for case in manifest["cases"] if case.get("mysql_expected_sql")]:
        actual = ask(base_url, item["question"], mysql_source, mysql_model)
        execution_ok = actual.get("execution", {}).get("status") == "SUCCEEDED"
        result_ok = verify(base_url, actual, item, prefix="mysql_") if execution_ok else False
        mysql_results.append({
            "id": item["id"], "execution_ok": execution_ok, "result_ok": result_ok,
            "query_id": actual.get("id"), "error_code": actual.get("error_code"),
        })
    execution_pass = sum(item["execution_ok"] for item in postgres_results)
    result_pass = sum(item["result_ok"] for item in postgres_results)
    semantic_pass = sum(item["semantic_ok"] for item in postgres_results)
    mysql_execution = sum(item["execution_ok"] for item in mysql_results)
    mysql_result = sum(item["result_ok"] for item in mysql_results)
    original20_pass = all(
        item["execution_ok"] and item["result_ok"] and item["semantic_ok"]
        for item in postgres_results[:20]
    )
    result = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": manifest["manifest_sha256"],
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "original_golden20_regression": "PASS" if original20_pass else "FAIL",
        "postgresql": {
            "total": 50, "execution_pass": execution_pass, "result_pass": result_pass,
            "semantic_pass": semantic_pass, "execution_rate": execution_pass / 50,
            "result_rate": result_pass / 50, "cases": postgres_results,
        },
        "mysql": {
            "total": len(mysql_results), "execution_pass": mysql_execution,
            "result_pass": mysql_result, "cases": mysql_results,
        },
    }
    result["gate_pass"] = (
        original20_pass and execution_pass >= 49 and result_pass >= 48
        and mysql_execution == len(mysql_results) and mysql_result == len(mysql_results)
        and len(mysql_results) >= 10
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[2]
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--manifest", type=Path, default=root / "evaluation" / "golden" / "day4-golden-50.json")
    parser.add_argument("--original", type=Path, default=root / "evaluation" / "golden" / "day2-golden-20.json")
    parser.add_argument("--output", type=Path, default=root / "docs" / "evidence" / "day4" / "golden-50-results.json")
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    original = json.loads(args.original.read_text(encoding="utf-8"))
    if original.get("manifest_sha256") != ORIGINAL_SHA256 or manifest_hash(original) != ORIGINAL_SHA256:
        raise RuntimeError("Original Golden 20 manifest SHA-256 mismatch")
    if args.freeze:
        freeze(args.base_url, manifest, original)
        args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = evaluate(args.base_url, manifest, original)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "manifest_sha256": result["manifest_sha256"],
        "original_golden20": result["original_golden20_regression"],
        "postgresql_execution": f"{result['postgresql']['execution_pass']}/50",
        "postgresql_result": f"{result['postgresql']['result_pass']}/50",
        "postgresql_semantic": f"{result['postgresql']['semantic_pass']}/50",
        "mysql_execution": f"{result['mysql']['execution_pass']}/{result['mysql']['total']}",
        "mysql_result": f"{result['mysql']['result_pass']}/{result['mysql']['total']}",
        "gate_pass": result["gate_pass"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["gate_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
