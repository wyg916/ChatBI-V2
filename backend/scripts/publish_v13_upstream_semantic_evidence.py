from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from statistics import quantiles


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
TEST_ROOT = BACKEND_ROOT / "tests"
if str(TEST_ROOT) not in sys.path:
    sys.path.insert(0, str(TEST_ROOT))

from app.core.config import Settings  # noqa: E402
from app.query.sql_guard import SqlGuard  # noqa: E402
from app.semantic_runtime import SemanticRuntime  # noqa: E402
from test_v21_semantic_runtime import CASES, benchmark_context  # noqa: E402


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_evidence() -> dict:
    settings = Settings(_env_file=None, semantic_runtime_mode="wren")
    selected = SemanticRuntime(settings, upstream_reuse_mode="selected_source")
    clean = SemanticRuntime(settings, upstream_reuse_mode="clean_room")
    cases = []
    hits = total = 0
    latencies = []
    openchatbi_calls = wren_calls = 0

    for index, (question, expected_metrics, expected_dimensions, _, _) in enumerate(CASES, start=1):
        context = benchmark_context()
        selected_plan, selected_trace = selected.plan(question=question, context=context)
        clean_plan, clean_trace = clean.plan(question=question, context=context)
        linking = selected_trace.schema_linking
        mdl = selected_trace.wren_mdl
        dry = selected_trace.wren_dry_plan
        assert linking is not None and mdl is not None and dry is not None
        metric_top5 = [item.name for item in linking.candidates if item.object_type == "metric"][:5]
        dimension_top5 = [item.name for item in linking.candidates if item.object_type == "dimension"][:5]
        hits += sum(item in metric_top5 for item in expected_metrics)
        hits += sum(item in dimension_top5 for item in expected_dimensions)
        total += len(expected_metrics) + len(expected_dimensions)
        latencies.append(linking.elapsed_ms)
        openchatbi_calls += selected_trace.upstream_runtime_call_count["openchatbi"]
        wren_calls += selected_trace.upstream_runtime_call_count["wrenai"]
        guarded = SqlGuard().validate(
            selected_plan.generated_sql,
            dialect=context.dialect,
            policy=context.security_policy,
        )
        cases.append(
            {
                "case_id": f"semantic-{index:02d}",
                "question_sha256": _hash(question),
                "selected_sql_sha256": _hash(selected_plan.generated_sql),
                "clean_room_sql_sha256": _hash(clean_plan.generated_sql),
                "same_plan": selected_plan.generated_sql == clean_plan.generated_sql,
                "guard_allowed": guarded.allowed,
                "openchatbi": {
                    "adapter": linking.adapter,
                    "source_commit": linking.upstream_source_commit,
                    "runtime_call_count": linking.upstream_call_count,
                    "catalog_latency_ms": linking.elapsed_ms,
                    "metric_top5": metric_top5,
                    "dimension_top5": dimension_top5,
                },
                "wrenai": {
                    "adapter": mdl.adapter,
                    "source_commit": mdl.upstream_source_commit,
                    "runtime_call_count": mdl.upstream_call_count + dry.upstream_call_count,
                    "mdl_mapping_coverage": mdl.mapping_coverage,
                    "dry_plan_status": dry.status,
                    "semantic_sql_sha256": _hash(dry.semantic_sql or ""),
                    "upstream_ast_sha256": _hash(dry.upstream_ast or ""),
                },
                "clean_room_runtime_call_count": clean_trace.upstream_runtime_call_count,
            }
        )

    p95 = quantiles(latencies, n=20, method="inclusive")[18]
    metrics = {
        "case_count": len(cases),
        "actual_upstream_openchatbi_calls": openchatbi_calls,
        "actual_upstream_wrenai_calls": wren_calls,
        "schema_recall_at_5": round(hits / total, 6),
        "catalog_latency_p95_ms": round(p95, 3),
        "mdl_mapping_coverage": min(item["wrenai"]["mdl_mapping_coverage"] for item in cases),
        "dry_plan_ready_rate": sum(item["wrenai"]["dry_plan_status"] == "READY" for item in cases) / len(cases),
        "golden_plan_consistency": sum(item["same_plan"] for item in cases) / len(cases),
        "sql_guard_pass_rate": sum(item["guard_allowed"] for item in cases) / len(cases),
    }
    passed = (
        metrics["actual_upstream_openchatbi_calls"] > 0
        and metrics["actual_upstream_wrenai_calls"] == 2 * len(cases)
        and metrics["schema_recall_at_5"] >= 0.95
        and metrics["catalog_latency_p95_ms"] < 100
        and metrics["mdl_mapping_coverage"] == 1.0
        and metrics["dry_plan_ready_rate"] == 1.0
        and metrics["golden_plan_consistency"] == 1.0
        and metrics["sql_guard_pass_rate"] == 1.0
    )
    return {
        "schema_version": "chatbi-v1.3.0-upstream-semantic-evidence-v1",
        "status": "PASS" if passed else "FAIL",
        "scope": "sanitized same-Golden deterministic planning A/B; no provider or database credentials",
        "real_upstream_reuse": True,
        "super_sonic_mode": "CLEAN_ROOM",
        "gateway_invariants": [
            "Question Router unchanged",
            "SQLGlot -> QueryExecutor -> ResultOracle unchanged",
            "no provider network call from selected upstream sources",
        ],
        "ab_switch": "SemanticRuntime(upstream_reuse_mode='selected_source'|'clean_room')",
        "full_rollback": "CHATBI_SEMANTIC_RUNTIME_MODE=local",
        "metrics": metrics,
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = build_evidence()
    json_path = args.output_dir / "UPSTREAM_SEMANTIC_AB_EVIDENCE.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metrics = payload["metrics"]
    report = (
        "# OpenChatBI and WrenAI selected-source runtime evidence\n\n"
        f"- Status: `{payload['status']}`\n"
        f"- Cases: `{metrics['case_count']}`\n"
        f"- OpenChatBI actual source calls: `{metrics['actual_upstream_openchatbi_calls']}`\n"
        f"- WrenAI actual source calls: `{metrics['actual_upstream_wrenai_calls']}`\n"
        f"- Schema Recall@5: `{metrics['schema_recall_at_5']}`\n"
        f"- Catalog p95: `{metrics['catalog_latency_p95_ms']} ms`\n"
        f"- MDL mapping coverage: `{metrics['mdl_mapping_coverage']}`\n"
        f"- Dry-plan READY rate: `{metrics['dry_plan_ready_rate']}`\n"
        f"- Same-Golden plan consistency: `{metrics['golden_plan_consistency']}`\n"
        f"- SQL Guard pass rate: `{metrics['sql_guard_pass_rate']}`\n\n"
        "The A/B result compares selected upstream reuse with the retained clean-room path in one process. "
        "Questions and SQL are represented only by SHA-256 in JSON evidence.\n"
    )
    (args.output_dir / "UPSTREAM_SEMANTIC_AB_REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps({"status": payload["status"], "metrics": metrics}, ensure_ascii=False))


if __name__ == "__main__":
    main()
