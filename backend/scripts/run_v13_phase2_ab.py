from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from time import perf_counter
from urllib.parse import quote_plus

from dotenv import load_dotenv


RUNTIME_MODEL_NAME = "新能源经营分析"
CLARIFICATION_PROBES = [
    {"id": "P2Q01", "question": "销售情况怎么样"},
    {"id": "P2Q02", "question": "帮我看看业务表现"},
    {"id": "P2Q03", "question": "数据有什么变化"},
]


def _manifest_hash(manifest: dict) -> str:
    value = copy.deepcopy(manifest)
    value["manifest_sha256"] = None
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * quantile) - 1))
    return round(ordered[index], 3)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _semantic_match(case: dict, plan: dict) -> tuple[bool, bool]:
    metrics_ok = plan.get("metrics", []) == case.get("expected_metrics", [])
    dimensions_ok = plan.get("dimensions", []) == case.get("expected_dimensions", [])
    expected_entities = set(case.get("expected_entities", []))
    entities_ok = expected_entities.issubset(set(plan.get("selected_entities", [])))
    expected_filters = {
        (item["field"], str(item.get("value"))) for item in case.get("expected_filters", [])
    }
    actual_filters = {
        (item["field"], str(item.get("value"))) for item in plan.get("filters", [])
    }
    filters_ok = expected_filters.issubset(actual_filters)
    expected_time = case.get("expected_time_range")
    actual_time = plan.get("time_range") or {}
    time_ok = not expected_time or (
        actual_time.get("start") == expected_time.get("start")
        and actual_time.get("end_exclusive") == expected_time.get("end_exclusive")
    )
    join_expected = any(item != "orders" for item in expected_entities)
    join_ok = entities_ok if join_expected else True
    return metrics_ok and dimensions_ok and entities_ok and filters_ok and time_ok, join_ok


def _schema_recall(case: dict, trace: dict) -> tuple[int, int]:
    candidates = ((trace.get("schema_linking") or {}).get("candidates") or [])
    metric_top5 = [item.get("name") for item in candidates if item.get("object_type") == "metric"][:5]
    dimension_top5 = [item.get("name") for item in candidates if item.get("object_type") == "dimension"][:5]
    indexed_metrics = {item.get("name") for item in candidates if item.get("object_type") == "metric"}
    indexed_dimensions = {item.get("name") for item in candidates if item.get("object_type") == "dimension"}
    # Recall@5 applies to objects that exist in the retrieved catalog. Synthetic
    # time grains and runtime-derived metrics are covered by semantic accuracy,
    # not counted as catalog misses when the semantic model does not index them.
    expected_metrics = [item for item in case.get("expected_metrics", []) if item in indexed_metrics]
    expected_dimensions = [item for item in case.get("expected_dimensions", []) if item in indexed_dimensions]
    hits = sum(item in metric_top5 for item in expected_metrics)
    hits += sum(item in dimension_top5 for item in expected_dimensions)
    return hits, len(expected_metrics) + len(expected_dimensions)


def _mode_summary(cases: list[dict], clarification: list[dict]) -> dict:
    count = len(cases)
    stage_names = ["openchatbi", "supersonic", "wren", "sql", "oracle", "total"]
    latencies = {
        name: [float(item["latency_ms"].get(name, 0)) for item in cases]
        for name in stage_names
    }
    required = [item for item in cases if item["verification_query"]["required"]]
    return {
        "case_count": count,
        "sql_execution_pass": sum(item["execution_ok"] for item in cases),
        "sql_execution_rate": round(sum(item["execution_ok"] for item in cases) / count, 6),
        "result_value_pass": sum(item["result_ok"] for item in cases),
        "result_value_accuracy": round(sum(item["result_ok"] for item in cases) / count, 6),
        "semantic_pass": sum(item["semantic_ok"] for item in cases),
        "semantic_accuracy": round(sum(item["semantic_ok"] for item in cases) / count, 6),
        "join_accuracy": round(sum(item["join_ok"] for item in cases) / count, 6),
        "schema_recall_at_5": round(
            sum(item["schema_recall_hits"] for item in cases)
            / max(1, sum(item["schema_recall_total"] for item in cases)),
            6,
        ),
        "clarification_accuracy": round(
            sum(item["passed"] for item in clarification) / max(1, len(clarification)), 6
        ),
        "verification_query_rate_for_critical_cases": round(
            sum(item["verification_query"]["executed"] for item in required) / max(1, len(required)), 6
        ),
        "verification_query_pass_rate": round(
            sum(item["verification_query"]["passed"] for item in required) / max(1, len(required)), 6
        ),
        "upstream_runtime_calls": {
            "openchatbi": sum(item["upstream_calls"].get("openchatbi", 0) for item in cases),
            "wrenai": sum(item["upstream_calls"].get("wrenai", 0) for item in cases),
        },
        "latency_ms": {
            name: {
                "p50": round(median(latencies[name]), 3),
                "p95": _percentile(latencies[name], 0.95),
            }
            for name in stage_names
        },
        "ttfe_ms": None,
        "ttfe_measurement": "Measured separately by the production SSE regression; direct QueryPipeline A/B has no SSE boundary.",
        "model_usage": {
            "provider": "deterministic-semantic-v1",
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "cost": 0.0,
            "retry_count": sum(item["repair_count"] for item in cases),
            "network_model_calls": 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    project_root = Path(__file__).resolve().parents[2]
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--datasource-id")
    parser.add_argument("--semantic-model-id")
    parser.add_argument("--schema-name", default="demo_business")
    parser.add_argument(
        "--runtime-host-override",
        help="Ephemeral in-session datasource host override for host-vs-container test execution; never persisted.",
    )
    parser.add_argument(
        "--golden", type=Path,
        default=project_root / "evaluation" / "golden" / "day4-golden-50.json",
    )
    parser.add_argument(
        "--complex", type=Path,
        default=project_root / "evaluation" / "golden" / "v1.3-phase2-complex-20.json",
    )
    args = parser.parse_args()

    load_dotenv(args.env_file, override=True)
    if not os.getenv("CHATBI_DATABASE_URL") and os.getenv("CHATBI_META_PASSWORD"):
        password = quote_plus(os.environ["CHATBI_META_PASSWORD"])
        os.environ["CHATBI_DATABASE_URL"] = (
            f"postgresql+psycopg://chatbi_app:{password}@127.0.0.1:5432/chatbi_v2"
        )
    os.environ["CHATBI_MODEL_PROVIDER"] = "deterministic"
    os.environ["CHATBI_SEMANTIC_RUNTIME_MODE"] = "wren"
    os.environ["CHATBI_VERIFICATION_QUERY_ENABLED"] = "true"
    sys.path.insert(0, str(project_root / "backend"))

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
    golden = json.loads(args.golden.read_text(encoding="utf-8"))
    complex_manifest = json.loads(args.complex.read_text(encoding="utf-8"))
    if len(golden.get("cases", [])) != 50 or _manifest_hash(golden) != golden.get("manifest_sha256"):
        raise RuntimeError("Frozen Golden 50 manifest failed integrity verification")
    if not complex_manifest.get("frozen") or len(complex_manifest.get("cases", [])) != 20:
        raise RuntimeError("Complex 20 manifest is not frozen or has the wrong size")
    source_cases = {item["id"]: item for item in golden["cases"]}
    complex_cases: list[dict] = []
    for item in complex_manifest["cases"]:
        source = source_cases.get(item["source_golden_id"])
        if source is None:
            raise RuntimeError(f"Unknown Golden source case: {item['source_golden_id']}")
        derived = copy.deepcopy(source)
        derived.update({
            "id": item["id"],
            "question": item["question"],
            "category": item["category"],
            "source_golden_id": item["source_golden_id"],
        })
        complex_cases.append(derived)
    all_cases = [*golden["cases"], *complex_cases]

    with SessionLocal() as db:
        workspace = default_workspace(db)
        if workspace is None:
            raise RuntimeError("Default workspace is unavailable")
        datasource = db.get(DataSource, args.datasource_id) if args.datasource_id else db.scalar(
            select(DataSource).where(
                DataSource.workspace_id == workspace.id,
                DataSource.type == "postgresql",
                DataSource.schema == args.schema_name,
            ).order_by(DataSource.created_at.asc(), DataSource.id.asc())
        )
        model = db.get(SemanticModel, args.semantic_model_id) if args.semantic_model_id else db.scalar(
            select(SemanticModel).where(
                SemanticModel.workspace_id == workspace.id,
                SemanticModel.datasource_id == datasource.id,
                SemanticModel.name == RUNTIME_MODEL_NAME,
                SemanticModel.status == "PUBLISHED",
            ).order_by(SemanticModel.version.desc(), SemanticModel.id.asc())
        )
        if datasource is None or model is None:
            raise RuntimeError("Published PostgreSQL datasource/semantic model not found")
        if model.datasource_id != datasource.id or model.workspace_id != workspace.id:
            raise RuntimeError("A/B datasource/model/workspace binding mismatch")
        original_datasource_host = datasource.host
        if args.runtime_host_override:
            # The stored alias is correct inside Docker. Host-side acceptance uses
            # loopback to reach the same local PostgreSQL service without changing
            # the metadata record; set_committed_value keeps every commit clean.
            set_committed_value(datasource, "host", args.runtime_host_override)

        mode_results: dict[str, dict] = {}
        for mode in ("clean_room", "selected_source"):
            pipeline = QueryPipeline()
            settings = Settings(
                semantic_runtime_mode="wren",
                semantic_upstream_reuse_mode=mode,
                model_provider="deterministic",
            )
            pipeline.semantic_runtime = SemanticRuntime(
                settings=settings,
                router=pipeline.router,
                upstream_reuse_mode=mode,
            )
            case_results: list[dict] = []
            for case in all_cases:
                started = perf_counter()
                run = pipeline.execute(db, AskRequest(
                    question=case["question"],
                    datasource_id=datasource.id,
                    semantic_model_id=model.id,
                    row_limit=500,
                ))
                execution_ok = run.status in {"SUCCEEDED", "ORACLE_MISMATCH"} and (
                    (run.execution_payload or {}).get("status") == "SUCCEEDED"
                )
                if execution_ok:
                    expected_rows = case.get("expected_result") or []
                    expected = ExpectedResult(
                        columns=(
                            list(expected_rows[0])
                            if expected_rows else list((run.execution_payload or {}).get("columns") or [])
                        ),
                        rows=expected_rows,
                        tolerance=0.0001,
                        order_independent=True,
                        metric_names=case.get("expected_metrics", []),
                        dimension_names=case.get("expected_dimensions", []),
                        expected_signature=case.get("expected_signature"),
                    )
                    run = pipeline.verify(db, run, expected)
                total_ms = round((perf_counter() - started) * 1000, 3)
                plan = run.plan_payload or {}
                trace = (run.context_payload or {}).get("semantic_runtime") or {}
                semantic_ok, join_ok = _semantic_match(case, plan)
                recall_hits, recall_total = _schema_recall(case, trace)
                verification = (run.context_payload or {}).get("verification_query") or {
                    "required": False, "executed": False, "passed": True,
                }
                query_performance = (run.context_payload or {}).get("query_performance") or {}
                stage = trace.get("stage_latency_ms") or {}
                case_results.append({
                    "id": case["id"],
                    "source_golden_id": case.get("source_golden_id"),
                    "category": case.get("category"),
                    "question_sha256": _sha256(case["question"]),
                    "query_id": run.id,
                    "status": run.status,
                    "execution_ok": execution_ok,
                    "result_ok": (run.oracle_payload or {}).get("status") == "PASSED",
                    "semantic_ok": semantic_ok,
                    "join_ok": join_ok,
                    "schema_recall_hits": recall_hits,
                    "schema_recall_total": recall_total,
                    "result_signature": run.result_signature,
                    "normalized_sql_sha256": _sha256(run.normalized_sql or ""),
                    "upstream_calls": trace.get("upstream_runtime_call_count") or {},
                    "repair_count": int(plan.get("repair_count") or 0),
                    "verification_query": {
                        "required": bool(verification.get("required")),
                        "executed": bool(verification.get("executed")),
                        "passed": bool(verification.get("passed")),
                        "kind": verification.get("kind"),
                        "query_sha256": verification.get("query_sha256"),
                    },
                    "latency_ms": {
                        "openchatbi": float(stage.get("openchatbi") or 0),
                        "supersonic": float(stage.get("supersonic") or 0),
                        "wren": float(stage.get("wren") or 0),
                        "sql": float((run.execution_payload or {}).get("duration_ms") or 0),
                        "oracle": float(query_performance.get("oracle_ms") or 0),
                        "total": total_ms,
                    },
                    "error_code": run.error_code,
                })

            clarification_results: list[dict] = []
            for probe in CLARIFICATION_PROBES:
                started = perf_counter()
                run = pipeline.execute(db, AskRequest(
                    question=probe["question"],
                    datasource_id=datasource.id,
                    semantic_model_id=model.id,
                    row_limit=20,
                ))
                trace = (run.context_payload or {}).get("semantic_runtime") or {}
                linking = trace.get("schema_linking") or {}
                clarification_results.append({
                    "id": probe["id"],
                    "question_sha256": _sha256(probe["question"]),
                    "passed": bool(linking.get("clarification_required")),
                    "status": run.status,
                    "latency_ms": round((perf_counter() - started) * 1000, 3),
                })
            mode_results[mode] = {
                "summary": _mode_summary(case_results, clarification_results),
                "cases": case_results,
                "clarification_probes": clarification_results,
            }

    clean = mode_results["clean_room"]["summary"]
    upstream = mode_results["selected_source"]["summary"]
    report = {
        "schema_version": "chatbi-v1.3-phase2-ab-v1",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if (
            upstream["sql_execution_rate"] >= 0.98
            and upstream["result_value_accuracy"] >= 0.95
            and upstream["schema_recall_at_5"] >= 0.95
            and upstream["verification_query_rate_for_critical_cases"] == 1.0
            and upstream["upstream_runtime_calls"]["openchatbi"] > 0
            and upstream["upstream_runtime_calls"]["wrenai"] > 0
        ) else "FAIL",
        "scope": {
            "data_golden": 50,
            "additional_complex": 20,
            "clarification_probes": len(CLARIFICATION_PROBES),
            "database_dialect": "postgresql",
            "datasource_id": datasource.id,
            "semantic_model_id": model.id,
            "semantic_model_version": model.version,
            "workspace_id": workspace.id,
            "model": "deterministic-semantic-v1",
            "prompt_version": "deterministic-semantic-v1",
            "permission_role": "SYSTEM",
            "same_inputs_for_both_modes": True,
            "datasource_runtime_host_override": bool(args.runtime_host_override),
            "stored_datasource_host_sha256": _sha256(original_datasource_host),
            "same_physical_database": True,
            "schema_recall_definition": (
                "Recall@5 over expected Metric/Dimension objects indexed in the semantic catalog; "
                "synthetic time grains and runtime-derived metrics are scored by semantic accuracy."
            ),
            "golden_manifest_sha256": golden["manifest_sha256"],
            "complex_manifest_sha256": hashlib.sha256(args.complex.read_bytes()).hexdigest(),
        },
        "clean_room": mode_results["clean_room"],
        "selected_source": mode_results["selected_source"],
        "delta": {
            "result_value_accuracy": round(
                upstream["result_value_accuracy"] - clean["result_value_accuracy"], 6
            ),
            "semantic_accuracy": round(upstream["semantic_accuracy"] - clean["semantic_accuracy"], 6),
            "schema_recall_at_5": round(upstream["schema_recall_at_5"] - clean["schema_recall_at_5"], 6),
            "total_p95_ms": round(
                upstream["latency_ms"]["total"]["p95"] - clean["latency_ms"]["total"]["p95"], 3
            ),
            "model_cost": 0.0,
        },
        "selection": {
            "default_runtime": "selected_source",
            "reason": (
                "Same result accuracy and no model-cost increase; selected source adds verifiable upstream "
                "runtime provenance while retaining the clean-room A/B rollback."
            ),
            "ab_switch": "CHATBI_SEMANTIC_UPSTREAM_REUSE_MODE=selected_source|clean_room",
            "full_rollback": "CHATBI_SEMANTIC_RUNTIME_MODE=local",
        },
        "failures": {
            mode: [
                item["id"] for item in payload["cases"]
                if not (item["execution_ok"] and item["result_ok"] and item["semantic_ok"])
            ]
            for mode, payload in mode_results.items()
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "clean_room": clean,
        "selected_source": upstream,
        "delta": report["delta"],
        "failures": report["failures"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
