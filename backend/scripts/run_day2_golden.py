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


def api(base_url: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {detail}") from exc


def manifest_hash(manifest: dict[str, Any]) -> str:
    copy_value = copy.deepcopy(manifest)
    copy_value["manifest_sha256"] = None
    payload = json.dumps(copy_value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def select_runtime(base_url: str, dialect: str) -> tuple[str, str]:
    sources = api(base_url, "GET", "/api/v1/datasources")
    models = api(base_url, "GET", "/api/v1/semantic-models")
    datasource = next(item for item in sources if item["type"] == dialect)
    model = next(item for item in models if item["datasource_id"] == datasource["id"])
    return datasource["id"], model["id"]


def ask(base_url: str, question: str, datasource_id: str, semantic_model_id: str) -> dict[str, Any]:
    return api(base_url, "POST", "/api/v1/ask", {
        "question": question,
        "datasource_id": datasource_id,
        "semantic_model_id": semantic_model_id,
        "row_limit": 500,
    })


def freeze(base_url: str, manifest: dict[str, Any]) -> None:
    pg_source, pg_model = select_runtime(base_url, "postgresql")
    mysql_source, mysql_model = select_runtime(base_url, "mysql")
    for index, case in enumerate(manifest["cases"]):
        expected = ask(base_url, case["expected_sql"], pg_source, pg_model)
        if expected["status"] != "SUCCEEDED":
            raise RuntimeError(f"{case['id']} PostgreSQL expected SQL failed: {expected['error_code']} {expected['error_message']}")
        case["expected_result"] = expected["execution"]["rows"]
        case["expected_signature"] = expected["execution"]["result_signature"]
        if index < 5:
            mysql_expected = ask(base_url, case["mysql_expected_sql"], mysql_source, mysql_model)
            if mysql_expected["status"] != "SUCCEEDED":
                raise RuntimeError(f"{case['id']} MySQL expected SQL failed: {mysql_expected['error_code']} {mysql_expected['error_message']}")
            case["mysql_expected_result"] = mysql_expected["execution"]["rows"]
            case["mysql_expected_signature"] = mysql_expected["execution"]["result_signature"]
    manifest["frozen"] = True
    manifest["frozen_at"] = datetime.now(timezone.utc).isoformat()
    manifest["manifest_sha256"] = manifest_hash(manifest)


def semantic_match(case: dict[str, Any], actual: dict[str, Any]) -> tuple[bool, list[str]]:
    plan = actual.get("plan") or {}
    reasons: list[str] = []
    for key, expected_key in [
        ("metrics", "expected_metrics"),
        ("dimensions", "expected_dimensions"),
    ]:
        if plan.get(key, []) != case.get(expected_key, []):
            reasons.append(f"{key}: {plan.get(key, [])} != {case.get(expected_key, [])}")
    if not set(case.get("expected_entities", [])).issubset(set(plan.get("selected_entities", []))):
        reasons.append("selected_entities missing expected values")
    actual_filters = {(item["field"], str(item["value"])) for item in plan.get("filters", [])}
    expected_filters = {(item["field"], str(item["value"])) for item in case.get("expected_filters", [])}
    if not expected_filters.issubset(actual_filters):
        reasons.append("filters missing expected values")
    expected_time = case.get("expected_time_range")
    if expected_time:
        actual_time = plan.get("time_range") or {}
        if actual_time.get("start") != expected_time["start"] or actual_time.get("end_exclusive") != expected_time["end_exclusive"]:
            reasons.append("time_range mismatch")
    return not reasons, reasons


def evaluate(base_url: str, manifest: dict[str, Any]) -> dict[str, Any]:
    if not manifest.get("frozen") or manifest_hash(manifest) != manifest.get("manifest_sha256"):
        raise RuntimeError("Golden manifest is not frozen or its SHA-256 is invalid")
    pg_source, pg_model = select_runtime(base_url, "postgresql")
    mysql_source, mysql_model = select_runtime(base_url, "mysql")
    case_results: list[dict[str, Any]] = []
    for case in manifest["cases"]:
        actual = ask(base_url, case["question"], pg_source, pg_model)
        semantic_ok, semantic_reasons = semantic_match(case, actual)
        execution_ok = actual.get("execution", {}).get("status") == "SUCCEEDED"
        result_ok = False
        verified = actual
        if execution_ok:
            verified = api(base_url, "POST", f"/api/v1/queries/{actual['id']}/verify", {
                "expected": {
                    "columns": list(case["expected_result"][0]) if case["expected_result"] else [],
                    "rows": case["expected_result"],
                    "tolerance": 0.0001,
                    "order_independent": True,
                    "metric_names": case["expected_metrics"],
                    "dimension_names": case["expected_dimensions"],
                    "expected_signature": case["expected_signature"],
                }
            })
            result_ok = verified.get("oracle", {}).get("status") == "PASSED"
        case_results.append({
            "id": case["id"], "category": case["category"], "status": verified.get("status"),
            "execution_ok": execution_ok, "result_ok": result_ok, "semantic_ok": semantic_ok,
            "semantic_reasons": semantic_reasons, "query_id": actual.get("id"),
            "signature": actual.get("execution", {}).get("result_signature"),
            "error_code": actual.get("error_code"),
        })

    mysql_results: list[dict[str, Any]] = []
    for case in manifest["cases"][:5]:
        actual = ask(base_url, case["question"], mysql_source, mysql_model)
        execution_ok = actual.get("execution", {}).get("status") == "SUCCEEDED"
        result_ok = False
        if execution_ok:
            verified = api(base_url, "POST", f"/api/v1/queries/{actual['id']}/verify", {
                "expected": {
                    "columns": list(case["mysql_expected_result"][0]) if case["mysql_expected_result"] else [],
                    "rows": case["mysql_expected_result"],
                    "tolerance": 0.0001,
                    "order_independent": True,
                    "expected_signature": case["mysql_expected_signature"],
                }
            })
            result_ok = verified.get("oracle", {}).get("status") == "PASSED"
        mysql_results.append({
            "id": case["id"], "execution_ok": execution_ok, "result_ok": result_ok,
            "query_id": actual.get("id"), "error_code": actual.get("error_code"),
        })

    execution_pass = sum(item["execution_ok"] for item in case_results)
    result_pass = sum(item["result_ok"] for item in case_results)
    semantic_pass = sum(item["semantic_ok"] for item in case_results)
    mysql_execution_pass = sum(item["execution_ok"] for item in mysql_results)
    mysql_result_pass = sum(item["result_ok"] for item in mysql_results)
    return {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": manifest["manifest_sha256"],
        "postgresql": {
            "total": len(case_results), "execution_pass": execution_pass,
            "result_pass": result_pass, "semantic_pass": semantic_pass,
            "execution_rate": execution_pass / len(case_results),
            "result_rate": result_pass / len(case_results),
            "cases": case_results,
        },
        "mysql": {
            "total": len(mysql_results), "execution_pass": mysql_execution_pass,
            "result_pass": mysql_result_pass, "cases": mysql_results,
        },
        "gate_pass": execution_pass >= 19 and result_pass >= 18 and mysql_execution_pass >= 5 and mysql_result_pass >= 5,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[2]
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--manifest", type=Path, default=root / "evaluation" / "golden" / "day2-golden-20.json")
    parser.add_argument("--output", type=Path, default=root / "docs" / "evidence" / "day2" / "golden-results.json")
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.freeze:
        freeze(args.base_url, manifest)
        args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = evaluate(args.base_url, manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "manifest_sha256": result["manifest_sha256"],
        "postgresql_execution": f"{result['postgresql']['execution_pass']}/{result['postgresql']['total']}",
        "postgresql_result": f"{result['postgresql']['result_pass']}/{result['postgresql']['total']}",
        "postgresql_semantic": f"{result['postgresql']['semantic_pass']}/{result['postgresql']['total']}",
        "mysql_execution": f"{result['mysql']['execution_pass']}/{result['mysql']['total']}",
        "mysql_result": f"{result['mysql']['result_pass']}/{result['mysql']['total']}",
        "gate_pass": result["gate_pass"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["gate_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
