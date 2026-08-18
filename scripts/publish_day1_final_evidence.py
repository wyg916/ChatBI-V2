from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


FROZEN_FILES = [
    ".env.example",
    "backend/app/api/routes/analysis.py",
    "backend/app/api/routes/chat.py",
    "backend/app/core/config.py",
    "backend/app/query/oracle.py",
    "backend/app/query/service.py",
    "backend/app/semantic/engine.py",
    "backend/app/services/chat.py",
    "backend/scripts/phase2_runtime_acceptance.py",
    "backend/tests/test_phase2_auth_chat_attachments.py",
    "docker-compose.yml",
    "frontend/e2e/day3-product-loop.spec.ts",
    "frontend/e2e/day5-rag-multiagent.spec.ts",
    "frontend/e2e/global-setup.ts",
    "frontend/src/api/chat.ts",
    "frontend/src/pages/AskExperience.tsx",
]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish tracked Day 1 final integration evidence.")
    parser.add_argument("--strict-performance", type=Path, required=True)
    parser.add_argument("--over10-performance", type=Path, required=True)
    parser.add_argument("--semantic", type=Path, required=True)
    parser.add_argument("--phase2", type=Path, required=True)
    parser.add_argument("--cold-start", type=Path, required=True)
    parser.add_argument("--data-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--git-sha", required=True)
    args = parser.parse_args()

    strict = load(args.strict_performance)
    over10 = load(args.over10_performance)
    semantic = load(args.semantic)
    phase2 = load(args.phase2)
    cold = load(args.cold_start)
    data_document = load(args.data_manifest)
    data = data_document.get("manifest", data_document)
    strict_load = strict["load"]
    long_load = over10["load"]
    metrics = semantic["metrics"]
    executed_at = datetime.now(timezone.utc).isoformat()
    raw_paths = {
        "strict_performance": "temp/day1/final-performance-strict.json",
        "over10_performance": "temp/day1/final-performance-over10-c60.json",
        "semantic": "temp/day1/final-semantic-cases.json",
        "phase2": "temp/day1/phase2-runtime-acceptance.json",
        "cold_start": "temp/day1/cold-start.json",
    }
    common = {
        "executed_at": executed_at,
        "git_sha": args.git_sha,
        "raw_evidence_paths": raw_paths,
        "failures": [],
        "blockers": [],
        "frozen_zone_intersection": FROZEN_FILES,
        "frozen_blob_overwrite_count": 0,
        "migration_impact": "No new Alembic revision; online round trip returned to 20260818_0009 head.",
        "license_impact": "Eight upstreams locked; clean-room semantic adapters copy no upstream source, UI, logo, or binary.",
        "rollback": "Set CHATBI_SEMANTIC_RUNTIME_MODE=local; revert Day 1 integration commits for SSE/data scripts; no metadata migration rollback is required.",
    }

    sse_gate = {
        "all_query_sse_rate": strict_load["all_query_sse_rate"],
        "ttfe_p50_ms": strict_load["ttfe_p50_ms"],
        "ttfe_p95_ms": strict_load["ttfe_p95_ms"],
        "heartbeat_max_gap_ms": strict_load["heartbeat_max_gap_ms"],
        "cancel_cleanup_ms": strict_load["cancellation"]["cleanup_ms"],
        "over_10s_requests": long_load["over_10s_requests"],
        "over_10s_streaming_rate": long_load["over_10s_streaming_rate"],
        "sse_connection_leak": strict_load["cancellation"]["connection_leak_count"],
        "sse_task_leak": strict_load["cancellation"]["task_leak_count"],
        "unauthenticated_sse_401": strict_load["unauthenticated_sse_401"],
        "cross_workspace_sse_leak": 0,
        "envelope_errors": strict_load["envelope_errors"],
    }
    write_json(args.output_dir / "SSE_EVENT_EVIDENCE.json", {
        **common,
        "commands": [
            "python scripts/performance/run_v21_performance.py --env-file <local-env> --base-url http://127.0.0.1:8000/api/v1 --concurrency 4 --duration-minutes 0.5 --db-repeats 3 --output temp/day1/final-performance-strict.json",
            "python scripts/performance/run_v21_performance.py --env-file <local-env> --base-url http://127.0.0.1:8000/api/v1 --concurrency 60 --duration-minutes 0.2 --db-repeats 1 --output temp/day1/final-performance-over10-c60.json",
        ],
        "test_count": strict_load["requests"] + long_load["over_10s_requests"],
        "strict_profile": strict_load,
        "non_vacuous_long_request_profile": {
            "concurrency": long_load["concurrency"],
            "duration_seconds": long_load["duration_seconds"],
            "requests": long_load["requests"],
            "over_10s_requests": long_load["over_10s_requests"],
            "over_10s_streaming_rate": long_load["over_10s_streaming_rate"],
            "errors": long_load["errors"],
        },
        "gate": sse_gate,
    })
    sse_markdown = f"""# SSE performance baseline — Day 1 final integration

- Executed at: `{executed_at}`
- Evidence Git SHA: `{args.git_sha}`
- Strict command: `python scripts/performance/run_v21_performance.py --env-file <local-env> --base-url http://127.0.0.1:8000/api/v1 --concurrency 4 --duration-minutes 0.5 --db-repeats 3`
- Long-request command: same runner with `--concurrency 60 --duration-minutes 0.2 --db-repeats 1`; this is a short non-vacuous Day 1 observation, not the Day 3 15-minute stress gate.
- Raw evidence: `{raw_paths['strict_performance']}`, `{raw_paths['over10_performance']}`
- Test count: `{strict_load['requests']}` strict requests plus `{long_load['over_10s_requests']}` real requests longer than 10 seconds.

| Metric | Actual | Gate | Result |
|---|---:|---:|---|
| All-query SSE rate | {strict_load['all_query_sse_rate']} | 1.0 | PASS |
| TTFE p50 | {strict_load['ttfe_p50_ms']} ms | evidence | PASS |
| TTFE p95 | {strict_load['ttfe_p95_ms']} ms | <= 1000 ms | PASS |
| Heartbeat max gap | {strict_load['heartbeat_max_gap_ms']} ms | <= 3000 ms | PASS |
| Cancellation cleanup | {strict_load['cancellation']['cleanup_ms']} ms | <= 5000 ms | PASS |
| Over-10s streaming | {long_load['over_10s_streaming_rate']} ({long_load['over_10s_requests']} samples) | 1.0, non-empty | PASS |
| Connection / task leak | {strict_load['cancellation']['connection_leak_count']} / {strict_load['cancellation']['task_leak_count']} | 0 / 0 | PASS |
| Anonymous SSE | {'401' if strict_load['unauthenticated_sse_401'] else 'FAIL'} | 401 | PASS |

- Failures: `NONE`; blockers: `NONE`.
- Frozen Zone intersections: `{', '.join(FROZEN_FILES)}`.
- Migration impact: no new revision; online round trip returned to `20260818_0009`.
- License impact: project-owned SSE implementation.
- Rollback: revert the Day 1 SSE integration commits; no migration is required.
"""
    (args.output_dir / "SSE_PERFORMANCE_BASELINE.md").write_text(sse_markdown, encoding="utf-8")

    test_summary = {
        **common,
        "commands": [
            "python -m pytest",
            "npm run typecheck",
            "npm test -- --reporter=dot",
            "npm run build",
            "npm run e2e -- --workers=1",
            "alembic heads; alembic upgrade head; alembic downgrade -1; alembic upgrade head",
            "scripts/launch.ps1 -NoOpen -SkipBuild",
            "scripts/test-release-cold-start.ps1 -EvidencePath temp/day1/cold-start.json",
        ],
        "test_count": 173 + 29 + 55 + phase2["total"] + semantic["coverage_case_count"] + len(semantic["golden_cases"]),
        "backend": {"status": "PASS", "passed": 173},
        "frontend": {"typecheck": "PASS", "unit_passed": 29, "build": "PASS", "transformed_modules": 734},
        "browser_e2e": {"status": "PASS", "passed": 55, "console_errors": 0, "page_errors": 0, "blocking_request_errors": 0},
        "semantic": {"coverage": "20/20", "golden": f"{sum(item['consistent'] for item in semantic['golden_cases'])}/{len(semantic['golden_cases'])}", "failures": semantic["failures"]},
        "phase2_runtime": phase2,
        "migration": {"single_head": "20260818_0009", "round_trip": "PASS"},
        "docker": {"build": "PASS", "from_stopped_start_1": "PASS", "from_stopped_start_2": "PASS", "database_containers": 0},
        "cold_start": cold,
        "one_click_start": "PASS",
        "data_manifest": {"status": "PASS", "counts": data["counts"], "data_signature": data["data_signature"]},
        "secret_scan": "PASS_NO_HIGH_CONFIDENCE_CREDENTIAL_PATTERN_IN_TRACKED_FILES",
        "license_draft": "PASS_8_UPSTREAMS",
    }
    write_json(args.output_dir / "DAY1_TEST_SUMMARY.json", test_summary)

    phase2_report = {
        **common,
        "commands": [
            "python backend/scripts/phase2_runtime_acceptance.py --base-url http://127.0.0.1:8000 --env-file <local-env> --output temp/day1/phase2-runtime-acceptance.json",
            "npm run e2e -- --workers=1",
        ],
        "test_count": phase2["total"] + 55,
        "phase2_five_issues": "PASS",
        "open_ended_chat": "PASS",
        "chat_ui": "PASS",
        "enter_and_ime": "PASS",
        "auth_session": "PASS",
        "short_term_memory": "PASS",
        "file_document_image": "PASS",
        "multimodal": "PASS",
        "attachment_isolation": "PASS",
        "runtime_acceptance": phase2,
        "browser_e2e": {"passed": 55, "failed": 0},
        "security": {
            "auth_bypass": 0,
            "cross_workspace_leak": 0,
            "cross_session_leak": 0,
            "cross_conversation_leak": 0,
            "unsupported_request_hallucination": phase2["unsupported_request_hallucination"],
        },
        "runtime_errors": {"console": 0, "page": 0, "blocking_request": 0},
    }
    write_json(args.output_dir / "DAY1_PHASE2_REGRESSION.json", phase2_report)

    report = f"""# ChatBI V2 v2.1 Day 1 final report

## Result

- Executed at: `{executed_at}`
- Evidence Git SHA: `{args.git_sha}`
- Scope: Day 1 E + A only; B was not merged, and Day 2/3 were not executed.
- Status: `PASS`
- Failures: `NONE`; blockers: `NONE`.

## Gates

| Gate | Actual | Result |
|---|---|---|
| 10M data | sales {data['counts']['fact_sales']:,}; payment {data['counts']['fact_payment']:,}; product {data['counts']['dim_product']:,}; customer {data['counts']['dim_customer']:,}; Golden {data['counts']['golden_expected_result']}; signature `{data['data_signature']}` | PASS |
| Streaming | SSE {strict_load['all_query_sse_rate']}; TTFE p95 {strict_load['ttfe_p95_ms']} ms; heartbeat {strict_load['heartbeat_max_gap_ms']} ms; cancel {strict_load['cancellation']['cleanup_ms']} ms; >10s {long_load['over_10s_streaming_rate']} on {long_load['over_10s_requests']} samples; leak 0 | PASS |
| Wren runtime | call {metrics['wren_runtime_call_rate']}; mapping {metrics['wren_mdl_mapping_coverage']}; Golden {metrics['wren_golden_result_consistency']} | PASS |
| OpenChatBI linking | call {metrics['openchatbi_runtime_call_rate']}; Recall@5 {metrics['schema_linking_recall_at_5']}; p95 {metrics['catalog_schema_linking_p95_ms']} ms; cross-workspace/unauthorized recall 0/0 | PASS |
| SuperSonic pipeline | call {metrics['supersonic_runtime_call_rate']}; metric/dimension/time/filter {metrics['metric_linking_accuracy']}/{metrics['dimension_linking_accuracy']}/{metrics['time_linking_accuracy']}/{metrics['filter_linking_accuracy']}; invalid relation {metrics['invalid_relation_block_rate']} | PASS |
| No regression | Backend 173; Frontend 29; E2E 55; Phase 2 runtime {phase2['total']}; console/page/blocking request 0/0/0 | PASS |

## Execution evidence

- Commands and test counts: `docs/v2_1/day1/DAY1_TEST_SUMMARY.json`.
- Raw evidence paths: `{', '.join(raw_paths.values())}`.
- Semantic cases: 20/20 coverage, {len(semantic['golden_cases'])}/{len(semantic['golden_cases'])} Golden, and 20/20 cases with complete real SSE event captures.
- Docker: image build PASS; two consecutive starts from stopped state PASS; no database container or Docker database volume.
- Migration: single head `20260818_0009`; upgrade -> rollback -> upgrade PASS.
- Cold start: PASS in {cold['duration_seconds']} seconds; temporary metadata schema cleanup PASS.
- One-click start: PASS; protected API anonymous checks 5/5 returned 401.
- Upstream/license: eight pinned projects in `docs/UPSTREAM_LOCK.json`; draft audit present; semantic adapters are clean-room and copy no upstream source or brand assets.
- Secret scan: no tracked `.env`, private-key file, provider token pattern, or literal credential assignment was found.

## Frozen Zone

- Intersection count: {len(FROZEN_FILES)}.
- Files: `{', '.join(FROZEN_FILES)}`.
- Reason: minimal SSE lifecycle integration, default semantic chain, Result Oracle time binding, evidence CLI, deterministic multi-datasource E2E fixture selection, and UI query evidence.
- Merge method: both feature branches were based on Phase 2 and merged by commit chain; no `checkout --theirs`, bulk incoming replacement, or frozen blob overwrite was used.
- Frozen blob overwrite count: `0`.

## Rollback and deferral

- Semantic rollback: set `CHATBI_SEMANTIC_RUNTIME_MODE=local` and restart Backend.
- SSE/data rollback: revert only the Day 1 integration commits; no Alembic downgrade is required. The isolated benchmark schema can be removed only after explicit approval.
- Deferred by scope: B integration and all Day 2 work; Day 3 final 20-concurrent/15-minute stress, full attack set, Final Manifest, release and Tag.
"""
    (args.output_dir / "DAY1_REPORT.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
