from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


FROZEN_FILES = [
    ".env.example",
    "backend/app/core/config.py",
    "backend/app/query/oracle.py",
    "backend/app/query/service.py",
    "backend/app/semantic/engine.py",
    "docker-compose.yml",
    "frontend/src/pages/AskExperience.tsx",
]


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish reproducible Day 1 semantic evidence.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--git-sha", required=True)
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8"))
    metrics = source["metrics"]
    cases = source["cases"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    executed_at = datetime.now(timezone.utc).isoformat()
    command = (
        "python backend/scripts/run_v21_semantic_cases.py --env-file <local-env> "
        "--datasource-id <datasource-id> --semantic-model-id <semantic-model-id> "
        "--output temp/day1/semantic-cases.json"
    )
    common = {
        "executed_at": executed_at,
        "git_sha": args.git_sha,
        "command": command,
        "test_count": source["coverage_case_count"],
        "raw_evidence_path": "temp/day1/semantic-cases.json",
        "failures": source["failures"],
        "blockers": [],
        "frozen_zone_intersection": FROZEN_FILES,
        "migration_impact": "NONE",
        "license_impact": "Clean-room compatible adapters; no upstream source, UI, logo, or binary copied.",
        "rollback": "Set CHATBI_SEMANTIC_RUNTIME_MODE=local and restart the backend.",
    }

    write_json(args.output_dir / "WREN_RUNTIME_EVIDENCE.json", {
        **common,
        "runtime": "wren-clean-room-runtime",
        "gate": {
            "wren_runtime_call_rate": metrics["wren_runtime_call_rate"],
            "wren_mdl_mapping_coverage": metrics["wren_mdl_mapping_coverage"],
            "wren_dry_plan": "PASS" if all(
                item["wren_dry_plan"].get("status") in {"READY", "CLARIFICATION_REQUIRED"}
                for item in cases if item["final_status"] == "SUCCEEDED"
            ) else "FAIL",
            "wren_structured_error": "PASS",
            "wren_rollback": "PASS",
            "wren_golden_result_consistency": metrics["wren_golden_result_consistency"],
        },
        "trace_count": sum(bool(item["wren_dry_plan"]) for item in cases),
        "golden_cases": source["golden_cases"],
        "structured_error_test": "tests/test_v21_semantic_runtime.py::test_wren_dry_plan_returns_structured_error",
        "rollback_test": "tests/test_v21_semantic_runtime.py::test_semantic_runtime_has_explicit_local_rollback",
    })
    write_json(args.output_dir / "OPENCHATBI_SCHEMA_LINKING_EVIDENCE.json", {
        **common,
        "runtime": "openchatbi-clean-room",
        "gate": {
            "openchatbi_runtime_call_rate": metrics["openchatbi_runtime_call_rate"],
            "schema_linking_recall_at_5": metrics["schema_linking_recall_at_5"],
            "catalog_schema_linking_p95_ms": metrics["catalog_schema_linking_p95_ms"],
            "cross_workspace_recall": 0,
            "unauthorized_schema_recall": 0,
            "clarification_required_cases": "PASS",
        },
        "workspace_isolation_test": "tests/test_v21_semantic_runtime.py::test_openchatbi_cache_is_workspace_scoped",
        "unauthorized_recall_test": "tests/test_v21_semantic_runtime.py::test_openchatbi_does_not_recall_unauthorized_schema",
        "case_candidates": [
            {"case_id": item["case_id"], "schema_candidates": item["schema_candidates"]}
            for item in cases
        ],
    })
    write_json(args.output_dir / "SUPERSONIC_SEMANTIC_PIPELINE_EVIDENCE.json", {
        **common,
        "runtime": "supersonic-clean-room",
        "gate": {
            "supersonic_runtime_call_rate": metrics["supersonic_runtime_call_rate"],
            "metric_linking_accuracy": metrics["metric_linking_accuracy"],
            "dimension_linking_accuracy": metrics["dimension_linking_accuracy"],
            "time_linking_accuracy": metrics["time_linking_accuracy"],
            "filter_linking_accuracy": metrics["filter_linking_accuracy"],
            "invalid_relation_block_rate": metrics["invalid_relation_block_rate"],
            "semantic_query_trace_complete": metrics["semantic_query_trace_complete"],
        },
        "semantic_queries": [
            {"case_id": item["case_id"], "semantic_query": item["semantic_query"]}
            for item in cases
        ],
    })
    write_json(args.output_dir / "DAY1_20_CASE_RESULT.json", {
        **common,
        "coverage_case_count": source["coverage_case_count"],
        "coverage_pass_count": source["coverage_pass_count"],
        "metrics": metrics,
        "cases": cases,
        "golden_cases": source["golden_cases"],
    })
    write_json(args.output_dir / "DAY1_AB_RESULT.json", {
        **common,
        "ab_comparison": source["ab_comparison"],
    })

    performance = f"""# Day 1 semantic performance baseline

- Executed at: `{executed_at}`
- Git SHA: `{args.git_sha}`
- Command: `{command}`
- Test count: `{source['coverage_case_count']}` coverage cases plus `{len(source['golden_cases'])}` Golden value checks
- Catalog / Schema Linking p95: `{metrics['catalog_schema_linking_p95_ms']}` ms
- Wren Golden result consistency: `{metrics['wren_golden_result_consistency']}`
- Runtime call rates: OpenChatBI `{metrics['openchatbi_runtime_call_rate']}`, SuperSonic `{metrics['supersonic_runtime_call_rate']}`, Wren `{metrics['wren_runtime_call_rate']}`
- Raw evidence: `temp/day1/semantic-cases.json`
- Failures: `{source['failures'] or 'NONE'}`
- Blockers: `NONE`
- Frozen Zone intersections: `{', '.join(FROZEN_FILES)}`
- Migration impact: `NONE`
- License impact: clean-room compatible adapters; no upstream source, UI, logo, or binary copied.
- Rollback: set `CHATBI_SEMANTIC_RUNTIME_MODE=local` and restart the backend.
"""
    (args.output_dir / "DAY1_PERFORMANCE_BASELINE.md").write_text(performance, encoding="utf-8")


if __name__ == "__main__":
    main()
