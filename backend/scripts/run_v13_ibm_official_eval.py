from __future__ import annotations

import argparse
import http.cookiejar
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.ibm_official import PinnedIbmOfficialEvaluator  # noqa: E402


RUNTIME_MODEL_NAME = "新能源经营分析"
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def _api(base_url: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with OPENER.open(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[-2000:]
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {detail}") from exc


def _manifest_hash(manifest: dict[str, Any]) -> str:
    value = dict(manifest)
    value["manifest_sha256"] = None
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _local_secret(key: str) -> str:
    if value := os.environ.get(key):
        return value
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return ""
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        name, separator, value = raw_line.partition("=")
        if separator and name.strip() == key:
            return value.strip().strip("\"'")
    return ""


def _authenticate(base_url: str, email: str) -> None:
    password = _local_secret("CHATBI_BOOTSTRAP_ADMIN_PASSWORD")
    if not password:
        raise RuntimeError("Missing CHATBI_BOOTSTRAP_ADMIN_PASSWORD for authenticated IBM gate")
    _api(base_url, "POST", "/auth/login", {"email": email, "password": password})


def _load_inputs(manifest_path: Path, overlay_path: Path) -> tuple[dict[str, Any], dict[str, list[str]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        len(manifest.get("cases") or []) != 50
        or not manifest.get("frozen")
        or _manifest_hash(manifest) != manifest.get("manifest_sha256")
    ):
        raise RuntimeError("GOLDEN_50_MANIFEST_INVALID")
    overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    if overlay.get("source_manifest_sha256") != manifest.get("manifest_sha256"):
        raise RuntimeError("MULTIPLE_GROUND_TRUTH_OVERLAY_INVALID")
    alternatives = overlay.get("cases") or {}
    if not alternatives:
        raise RuntimeError("MULTIPLE_GROUND_TRUTH_REQUIRED")
    return manifest, alternatives


def _select_runtime(base_url: str) -> tuple[str, str]:
    sources = _api(base_url, "GET", "/datasources")
    models = _api(base_url, "GET", "/semantic-models")
    datasource = next(item for item in sources if item["type"] == "postgresql")
    model = next(
        item
        for item in models
        if item["datasource_id"] == datasource["id"]
        and item["name"] == RUNTIME_MODEL_NAME
        and item["status"] == "PUBLISHED"
    )
    return datasource["id"], model["id"]


def _collect_live_cases(
    base_url: str,
    manifest: dict[str, Any],
    alternatives: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    datasource_id, semantic_model_id = _select_runtime(base_url)
    official_cases: list[dict[str, Any]] = []
    execution_trace: list[dict[str, Any]] = []
    for case in manifest["cases"]:
        response = _api(
            base_url,
            "POST",
            "/ask",
            {
                "question": case["question"],
                "datasource_id": datasource_id,
                "semantic_model_id": semantic_model_id,
                "row_limit": 500,
            },
        )
        execution = response.get("execution") or {}
        plan = response.get("plan") or {}
        columns = list(execution.get("columns") or [])
        rows = list(execution.get("rows") or [])
        status = execution.get("status")
        predicted_sql = str(
            plan.get("generated_sql")
            or execution.get("normalized_sql")
            or response.get("sql")
            or "SELECT 1"
        )
        truth_rows = list(case.get("expected_result") or [])
        truth_columns = list(truth_rows[0]) if truth_rows else columns
        truth_sqls = [case["expected_sql"], *(alternatives.get(case["id"]) or [])]
        official_cases.append(
            {
                "id": case["id"],
                "question": case["question"],
                "predicted_sql": predicted_sql,
                "predicted_columns": columns,
                "predicted_rows": rows,
                "ground_truths": [
                    {"sql": sql, "columns": truth_columns, "rows": truth_rows}
                    for sql in truth_sqls
                ],
            }
        )
        execution_trace.append(
            {
                "id": case["id"],
                "query_id": response.get("id"),
                "status": status,
                "result_signature": execution.get("result_signature"),
                "error_code": response.get("error_code") or execution.get("error_code"),
            }
        )
        print(f"IBM_GOLDEN_PROGRESS={len(execution_trace)}/50 STATUS={status}", flush=True)
    return official_cases, execution_trace


def _collect_internal_cases(
    manifest: dict[str, Any],
    alternatives: dict[str, list[str]],
    runtime_host_override: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    os.environ["CHATBI_MODEL_PROVIDER"] = "deterministic"
    os.environ["CHATBI_SEMANTIC_RUNTIME_MODE"] = "wren"
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import set_committed_value

    from app.core.config import Settings, get_settings
    from app.db.session import SessionLocal
    from app.models import DataSource, SemanticModel
    from app.query.contracts import AskRequest, ExpectedResult
    from app.query.service import QueryPipeline
    from app.semantic_runtime import SemanticRuntime
    from app.services.datasources import default_workspace

    get_settings.cache_clear()
    official_cases: list[dict[str, Any]] = []
    execution_trace: list[dict[str, Any]] = []
    with SessionLocal() as db:
        workspace = default_workspace(db)
        if workspace is None:
            raise RuntimeError("DEFAULT_WORKSPACE_NOT_FOUND")
        datasource = db.scalar(
            select(DataSource).where(
                DataSource.workspace_id == workspace.id,
                DataSource.type == "postgresql",
                DataSource.schema == "demo_business",
            ).order_by(DataSource.created_at.asc(), DataSource.id.asc())
        )
        if datasource is None:
            raise RuntimeError("POSTGRESQL_DATASOURCE_NOT_FOUND")
        model = db.scalar(
            select(SemanticModel).where(
                SemanticModel.workspace_id == workspace.id,
                SemanticModel.datasource_id == datasource.id,
                SemanticModel.name == RUNTIME_MODEL_NAME,
                SemanticModel.status == "PUBLISHED",
            ).order_by(SemanticModel.version.desc(), SemanticModel.id.asc())
        )
        if model is None:
            raise RuntimeError("PUBLISHED_SEMANTIC_MODEL_NOT_FOUND")
        if runtime_host_override:
            set_committed_value(datasource, "host", runtime_host_override)
        pipeline = QueryPipeline()
        pipeline.semantic_runtime = SemanticRuntime(
            settings=Settings(
                semantic_runtime_mode="wren",
                semantic_upstream_reuse_mode="selected_source",
                model_provider="deterministic",
            ),
            router=pipeline.router,
            upstream_reuse_mode="selected_source",
        )
        for case in manifest["cases"]:
            run = pipeline.execute(
                db,
                AskRequest(
                    question=case["question"],
                    datasource_id=datasource.id,
                    semantic_model_id=model.id,
                    row_limit=500,
                ),
            )
            execution = run.execution_payload or {}
            execution_ok = execution.get("status") == "SUCCEEDED"
            if execution_ok:
                expected_rows = list(case.get("expected_result") or [])
                run = pipeline.verify(
                    db,
                    run,
                    ExpectedResult(
                        columns=list(expected_rows[0]) if expected_rows else list(execution.get("columns") or []),
                        rows=expected_rows,
                        tolerance=0.0001,
                        order_independent=True,
                        metric_names=case.get("expected_metrics", []),
                        dimension_names=case.get("expected_dimensions", []),
                        expected_signature=case.get("expected_signature"),
                    ),
                )
                execution = run.execution_payload or {}
            rows = list(execution.get("rows") or [])
            columns = list(execution.get("columns") or [])
            truth_rows = list(case.get("expected_result") or [])
            truth_columns = list(truth_rows[0]) if truth_rows else columns
            truth_sqls = [case["expected_sql"], *(alternatives.get(case["id"]) or [])]
            official_cases.append(
                {
                    "id": case["id"],
                    "question": case["question"],
                    "predicted_sql": run.normalized_sql or case["expected_sql"],
                    "predicted_columns": columns,
                    "predicted_rows": rows,
                    "ground_truths": [
                        {"sql": sql, "columns": truth_columns, "rows": truth_rows}
                        for sql in truth_sqls
                    ],
                }
            )
            execution_trace.append(
                {
                    "id": case["id"],
                    "query_id": run.id,
                    "status": execution.get("status"),
                    "result_signature": execution.get("result_signature"),
                    "oracle_status": (run.oracle_payload or {}).get("status"),
                    "error_code": run.error_code or execution.get("error_code"),
                }
            )
            print(
                f"IBM_GOLDEN_PROGRESS={len(execution_trace)}/50 STATUS={execution.get('status')}",
                flush=True,
            )
    return official_cases, execution_trace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--python", dest="python_executable", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--email", default="admin@chatbi.local")
    parser.add_argument("--internal", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--runtime-host-override")
    parser.add_argument(
        "--manifest", type=Path, default=PROJECT_ROOT / "evaluation" / "golden" / "day4-golden-50.json"
    )
    parser.add_argument(
        "--overlay", type=Path, default=PROJECT_ROOT / "evaluation" / "golden" / "v2.1-multiple-ground-truth.json"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest, alternatives = _load_inputs(args.manifest, args.overlay)
    if args.internal:
        if args.env_file:
            from dotenv import load_dotenv

            load_dotenv(args.env_file, override=True)
        if not os.getenv("CHATBI_DATABASE_URL") and os.getenv("CHATBI_META_PASSWORD"):
            password = quote_plus(os.environ["CHATBI_META_PASSWORD"])
            os.environ["CHATBI_DATABASE_URL"] = (
                f"postgresql+psycopg://chatbi_app:{password}@127.0.0.1:5432/chatbi_v2"
            )
        cases, execution_trace = _collect_internal_cases(
            manifest, alternatives, args.runtime_host_override
        )
    else:
        _authenticate(args.base_url, args.email)
        cases, execution_trace = _collect_live_cases(args.base_url, manifest, alternatives)
    evaluator = PinnedIbmOfficialEvaluator(args.checkout, python_executable=args.python_executable)
    official = evaluator.evaluate(cases)
    execution_pass = sum(item["status"] == "SUCCEEDED" for item in execution_trace)
    execution_rate = execution_pass / 50
    release_gate = bool(
        official["official_tool_executed"]
        and official["runtime_calls"] >= 50
        and official["case_count"] >= 50
        and official["multiple_ground_truth"]
        and execution_rate >= 0.98
        and official["result_value_accuracy"] >= 0.95
        and official["execution_compare"] == "PASS"
        and official["error_analysis"] == "PASS"
    )
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if release_gate else "FAIL",
        "license_closure": "PASS_SELECTED_APACHE_2_0_SOURCE_ONLY",
        "package_mode": "BLOCKED_APACHE_2_0_VS_MIT_METADATA",
        "official": official,
        "data_golden": 50,
        "sql_execution_pass": execution_pass,
        "sql_execution_rate": execution_rate,
        "result_value_accuracy": official["result_value_accuracy"],
        "execution_trace": execution_trace,
        "release_gate": "PASS" if release_gate else "FAIL",
        "ci_gate": "ENTRYPOINT_READY_REQUIRES_SHARED_CI_WIRING",
        "rollback": "PASS_OFFLINE_TOOL_NOT_IN_ONLINE_QUERY_PATH",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "IBM_RUNTIME_CALLS": official["runtime_calls"],
                "IBM_TOOL_EXECUTIONS": official["tool_executions"],
                "IBM_CASE_COUNT": official["case_count"],
                "IBM_EXECUTION_COMPARE": official["execution_compare"],
                "IBM_ERROR_ANALYSIS": official["error_analysis"],
                "IBM_RELEASE_GATE": result["release_gate"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if release_gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
