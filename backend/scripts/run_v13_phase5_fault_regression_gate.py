from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEIRD_MANIFEST = PROJECT_ROOT / "evaluation" / "golden" / "v13-phase5-weird-50.json"
COMPLEX_MANIFEST = PROJECT_ROOT / "evaluation" / "golden" / "v13-phase5-complex-5.json"

WEIRD_CATEGORIES = {
    "irrelevant",
    "abstract",
    "malicious",
    "ambiguous",
    "typo",
    "fragment",
    "date_trap",
    "hallucination",
    "prompt_injection",
    "sql_injection",
    "unauthorized",
    "nonexistent_data",
    "long",
    "mixed_language",
}
COMPLEX_KINDS = {
    "MULTI_STEP_DATA",
    "DATA_RAG",
    "AGENT_SQL",
    "AGENT_PYTHON",
    "FILE_DB",
}
EXPECTED_FIELDS = {
    "route",
    "action",
    "model_calls_max",
    "cost_cny_max",
    "hallucination_allowed",
    "sql_execution_allowed",
}


@dataclass(frozen=True)
class FaultCase:
    case_id: str
    component: str
    fault: str
    retries_max: int
    terminal: str = "run.failed"
    fallback_expected: bool = False


@dataclass(frozen=True)
class FaultEvidence:
    case_id: str
    component: str
    fault: str
    evidence_kind: str
    retry_count: int
    circuit_observed: bool
    fallback_observed: bool
    budget_enforced: bool
    cancel_observed: bool
    trace_closed: bool
    sse_terminal: str
    sse_terminal_count: int
    infinite_retry_count: int
    duplicate_final_count: int
    stale_answer_count: int
    fail_closed: bool
    resource_released: bool
    external_runtime_success_claim: bool


@dataclass(frozen=True)
class RegressionSpec:
    phase: str
    paths: tuple[str, ...]

    def command(self) -> list[str]:
        return [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--disable-warnings",
            "--maxfail=1",
            *self.paths,
        ]


PHASE_REGRESSIONS = (
    RegressionSpec("phase1", ("tests/test_v13_runtime_control_plane.py",)),
    RegressionSpec(
        "phase2",
        (
            "tests/test_v13_phase2_query_verification.py",
            "tests/test_v13_upstream_semantic.py",
        ),
    ),
    RegressionSpec(
        "phase3",
        (
            "tests/test_v13_phase3_control_plane.py",
            "tests/test_v13_phase3_rag_grounding.py",
            "tests/test_v13_phase3_dbgpt_runtime.py",
            "tests/test_v13_phase3_file_multimodal.py",
            "tests/test_v13_phase3_multimodal_live_runner.py",
            "tests/test_v13_phase3_vision_policy.py",
            "tests/test_v13_phase3_python_sandbox.py",
        ),
    ),
    RegressionSpec(
        "phase4",
        (
            "tests/test_v13_phase4_answer_envelope.py",
            "tests/test_v13_phase4_conversation_governance.py",
        ),
    ),
)

PRODUCTION_CLASS_FAULT_REGRESSION = RegressionSpec(
    "production_fault_boundaries",
    (
        "tests/test_v13_phase5_fault_regression.py::test_production_model_gateway_class_fails_closed_for_provider_fault_matrix",
        "tests/test_v13_phase5_fault_regression.py::test_model_gateway_fallback_exhaustion_and_budget_rejection_fail_before_answer",
        "tests/test_v13_phase5_fault_regression.py::test_database_slow_failure_and_explain_reject_are_fail_closed",
        "tests/test_v13_phase5_fault_regression.py::test_production_rag_adapter_class_retries_then_fails_closed_for_rag_faults",
        "tests/test_v13_phase5_fault_regression.py::test_streaming_fault_has_one_terminal_no_duplicate_final_and_registry_releases_workloads",
        "tests/test_v13_phase5_fault_regression.py::test_file_parse_fault_fails_closed_without_artifact",
        "tests/test_v13_phase5_fault_regression.py::test_python_sandbox_oom_and_worker_unavailable_are_unverified_and_destroyed",
        "tests/test_v13_phase3_rag_grounding.py::test_ungrounded_model_answer_fails_closed",
        "tests/test_v13_phase3_rag_grounding.py::test_live_rag_observes_cancellation_before_opening_http_client",
        "tests/test_v13_phase3_dbgpt_runtime.py::test_missing_dependency_fails_closed_without_callback",
        "tests/test_v13_phase3_dbgpt_runtime.py::test_cancellation_cancels_awel_call",
        "tests/test_v13_phase3_dbgpt_runtime.py::test_deadline_cancels_awel_call",
        "tests/test_legacy_rag_agent_integration.py::test_tool_executor_rejects_unknown_tool_without_direct_db_access",
        "tests/test_v13_phase3_python_sandbox.py::test_timeout_kills_and_synchronously_destroys_container",
        "tests/test_v13_phase3_python_sandbox.py::test_destroy_failure_overrides_success_and_is_never_reported_verified",
        "tests/test_v13_phase3_vision_policy.py::test_ordinary_image_is_mimo_only_and_never_uses_kimi_as_fallback",
        "tests/test_v13_phase3_vision_policy.py::test_explicit_kimi_without_trigger_fails_before_network",
        "tests/test_phase4_model_invocation_ledger.py::test_stream_cancellation_is_recorded_without_prompt_or_partial_content",
        "tests/test_phase4_governance.py::test_trace_detail_is_one_trace_and_redacts_sensitive_payloads",
    ),
)

PRODUCTION_CLASS_FAULT_COVERAGE_MAP = {
    "provider": ["429", "timeout", "5xx", "slow", "invalid_response", "connection_reset", "fallback_exhausted", "budget_rejected"],
    "database": ["slow_query", "connection_failure", "explain_reject"],
    "rag": ["runtime_failure", "retriever_failure", "reranker_failure", "cancelled", "ungrounded_answer"],
    "agent_tool": ["missing_runtime", "cancelled", "deadline", "unknown_tool"],
    "python_sandbox": ["timeout", "oom", "worker_unavailable", "destroy_failure"],
    "file": ["parse_failure"],
    "vision": ["ordinary_fallback_denied", "unqualified_kimi_denied"],
    "verification_trace_sse": ["single_terminal", "resource_release", "cancelled_ledger", "trace_redaction"],
}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Manifest must be an object: {path}")
    return payload


def validate_weird_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    cases = payload.get("cases") or []
    answer_contracts = payload.get("answer_contracts") or {}
    if payload.get("frozen") is not True or len(cases) != 50:
        raise ValueError("Weird 50 must be frozen and contain exactly 50 cases")
    ids = [str(case.get("id") or "") for case in cases]
    if len(set(ids)) != 50 or ids != [f"W{index:03d}" for index in range(1, 51)]:
        raise ValueError("Weird 50 IDs must be unique and contiguous W001..W050")
    categories = Counter(str(case.get("category") or "") for case in cases)
    if set(categories) != WEIRD_CATEGORIES:
        raise ValueError(f"Weird category coverage mismatch: {sorted(categories)}")
    for case in cases:
        expected = case.get("expected") or {}
        if set(expected) != EXPECTED_FIELDS:
            raise ValueError(f"{case['id']} expected fields are not exact")
        if expected["hallucination_allowed"] is not False:
            raise ValueError(f"{case['id']} permits hallucination")
        if int(expected["model_calls_max"]) < 0 or float(expected["cost_cny_max"]) < 0:
            raise ValueError(f"{case['id']} has a negative model/cost budget")
    zero_model = [
        case["id"] for case in cases
        if case["expected"]["model_calls_max"] == 0 and case["expected"]["cost_cny_max"] == 0
    ]
    dangerous = {
        "malicious", "prompt_injection", "sql_injection", "unauthorized"
    }
    if any(
        case["expected"]["sql_execution_allowed"]
        for case in cases
        if case["category"] in dangerous
    ):
        raise ValueError("Dangerous Weird cases must never execute SQL")
    required_actions = {
        "REFUSE",
        "ASK_CLARIFICATION",
        "MODEL_NONE_DATE",
        "EMPTY_RESULT_NO_FABRICATION",
        "NO_EVIDENCE_NO_CLAIM",
        "REFUSE_INJECTION",
        "REFUSE_SQL_INJECTION",
        "REFUSE_UNAUTHORIZED",
        "BOUNDED_VERIFIED_ANALYSIS",
    }
    actions = {case["expected"]["action"] for case in cases}
    if not required_actions.issubset(actions):
        raise ValueError("Weird 50 misses refusal/clarification/zero-model/no-hallucination actions")
    if set(answer_contracts) != actions:
        raise ValueError("Weird 50 must freeze one answer contract for every action")
    contract_fields = {
        "claim_mode",
        "refusal_required",
        "clarification_required",
        "no_evidence_required",
        "verified_evidence_required",
    }
    for action, contract in answer_contracts.items():
        if set(contract) != contract_fields:
            raise ValueError(f"{action} answer contract fields are not exact")
        if contract["claim_mode"] not in {"NONE", "SAFE_ONLY", "DATE_ONLY", "EMPTY_ONLY", "VERIFIED_ONLY"}:
            raise ValueError(f"{action} answer contract has unknown claim mode")
    return {
        "status": "PASS",
        "case_count": len(cases),
        "category_counts": dict(sorted(categories.items())),
        "zero_model_case_count": len(zero_model),
        "zero_model_cases": zero_model,
        "hallucination_allowed_count": 0,
        "dangerous_sql_execution_allowed_count": 0,
    }


def validate_complex_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    cases = payload.get("cases") or []
    allowed_tools = set(payload.get("allowed_agent_tools") or [])
    if payload.get("frozen") is not True or len(cases) != 5:
        raise ValueError("Complex 5 must be frozen and contain exactly five cases")
    if {case.get("kind") for case in cases} != COMPLEX_KINDS:
        raise ValueError("Complex 5 must cover Data, Data+RAG, Agent+SQL, Agent+Python and File+DB")
    evidence_dimensions = {
        "steps", "tools", "latency", "cost", "cancel", "verification", "accuracy"
    }
    for case in cases:
        steps = case.get("steps") or []
        expected = case.get("expected") or {}
        if not steps or [step.get("ordinal") for step in steps] != list(range(1, len(steps) + 1)):
            raise ValueError(f"{case['id']} has non-contiguous steps")
        tools = [step.get("tool") for step in steps if step.get("tool")]
        if any(tool not in allowed_tools for tool in tools):
            raise ValueError(f"{case['id']} escapes the six-tool Agent allowlist")
        if len(steps) > int(expected.get("max_steps") or 0):
            raise ValueError(f"{case['id']} exceeds its step budget")
        if len(tools) > int(expected.get("max_tool_calls") or 0):
            raise ValueError(f"{case['id']} exceeds its tool budget")
        if expected.get("verification_required") is not True:
            raise ValueError(f"{case['id']} lacks mandatory verification")
        if not any(step.get("tool") == "VERIFY_RESULT" for step in steps):
            raise ValueError(f"{case['id']} lacks VERIFY_RESULT")
        if int(expected.get("max_latency_ms") or 0) > 30_000:
            raise ValueError(f"{case['id']} exceeds the hard latency budget")
        if float(expected.get("max_cost_cny") or -1) < 0:
            raise ValueError(f"{case['id']} lacks a cost budget")
        if expected.get("cancel_terminal") != "run.cancelled":
            raise ValueError(f"{case['id']} lacks cancellation evidence")
        if float(expected.get("accuracy_min") or 0) < 0.95:
            raise ValueError(f"{case['id']} accuracy threshold is below release policy")
        if expected.get("stale_answer_count") != 0:
            raise ValueError(f"{case['id']} permits stale answers")
        if int(expected.get("model_calls_max") or -1) < 0:
            raise ValueError(f"{case['id']} lacks a model invocation budget")
        frozen_evidence = expected.get("expected_evidence") or {}
        if set(frozen_evidence) != {"result", "citation", "file", "sandbox"}:
            raise ValueError(f"{case['id']} lacks exact frozen evidence sections")
        result_contract = frozen_evidence["result"]
        if set(result_contract) != {
            "result_semantic", "oracle_status", "required_metrics", "required_dimensions", "minimum_row_count"
        }:
            raise ValueError(f"{case['id']} result evidence contract is not exact")
        if result_contract["result_semantic"] != "VALUE" or result_contract["oracle_status"] != "PASSED":
            raise ValueError(f"{case['id']} result evidence must freeze VALUE/PASSED")
        if int(result_contract["minimum_row_count"]) < 1 or not result_contract["required_metrics"]:
            raise ValueError(f"{case['id']} result evidence is not meaningful")
        if case["kind"] == "DATA_RAG" and frozen_evidence["citation"] != {
            "required": True,
            "minimum_count": 1,
            "required_title_terms": ["收入", "口径"],
        }:
            raise ValueError(f"{case['id']} citation evidence is not frozen")
        if case["kind"] == "AGENT_PYTHON" and frozen_evidence["sandbox"] != {
            "required": True,
            "status": "SUCCEEDED",
            "runtime_verified": True,
            "container_destroyed": True,
            "operation": "correlation",
        }:
            raise ValueError(f"{case['id']} sandbox evidence is not frozen")
        if case["kind"] == "FILE_DB":
            file_contract = frozen_evidence["file"]
            attachment = case.get("attachment") or {}
            fixture = (PROJECT_ROOT / str(attachment.get("path") or "")).resolve()
            if not fixture.is_relative_to(PROJECT_ROOT.resolve()) or not fixture.is_file():
                raise ValueError(f"{case['id']} file fixture is missing")
            digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
            if file_contract != {
                "required": True,
                "sha256": digest,
                "row_count": 4,
                "columns": ["month", "region", "revenue", "cost"],
                "revenue_sum": 4430,
                "cost_sum": 2970,
            }:
                raise ValueError(f"{case['id']} file evidence is not frozen to its fixture")
    return {
        "status": "PASS",
        "case_count": len(cases),
        "kinds": sorted(COMPLEX_KINDS),
        "evidence_dimensions": sorted(evidence_dimensions),
        "verification_case_count": 5,
        "accuracy_threshold_min": min(case["expected"]["accuracy_min"] for case in cases),
        "latency_budget_max_ms": max(case["expected"]["max_latency_ms"] for case in cases),
        "cost_budgeted_case_count": sum("max_cost_cny" in case["expected"] for case in cases),
        "cancellable_case_count": sum(case["expected"]["cancel_terminal"] == "run.cancelled" for case in cases),
    }


def build_fault_matrix() -> tuple[FaultCase, ...]:
    cases: list[FaultCase] = []
    for provider in ("mimo", "deepseek", "kimi"):
        retries = 0 if provider == "kimi" else 1
        for fault in ("http_429", "timeout", "http_5xx", "slow", "invalid_response", "connection_reset"):
            cases.append(FaultCase(f"provider.{provider}.{fault}", f"provider:{provider}", fault, retries))
    cases.extend((
        FaultCase("db.slow", "database", "slow_query", 0),
        FaultCase("db.failure", "database", "connection_failure", 0),
        FaultCase("db.explain_reject", "database", "explain_reject", 0),
        FaultCase("rag.runtime", "rag", "runtime_failure", 1, fallback_expected=True),
        FaultCase("rag.retriever", "rag", "retriever_failure", 1),
        FaultCase("rag.reranker", "rag", "reranker_failure", 1),
        FaultCase("agent.tool_timeout", "agent_tool", "tool_timeout", 0),
        FaultCase("agent.tool_failure", "agent_tool", "tool_failure", 0),
        FaultCase("agent.unknown_tool", "agent_tool", "unknown_tool", 0),
        FaultCase("python.timeout", "python_sandbox", "timeout", 0),
        FaultCase("python.oom", "python_sandbox", "oom", 0),
        FaultCase("python.worker", "python_sandbox", "worker_unavailable", 0),
        FaultCase("file.parse", "file", "parse_failure", 0),
        FaultCase("vision.provider", "vision", "provider_failure", 1, fallback_expected=True),
        FaultCase("vision.evidence", "vision", "invalid_evidence", 0),
        FaultCase("verify.retry", "verification", "retry_exhausted", 1),
        FaultCase("verify.circuit", "verification", "circuit_open", 0),
        FaultCase("verify.fallback", "verification", "fallback_failed", 0, fallback_expected=True),
        FaultCase("verify.budget", "verification", "budget_exceeded", 0),
        FaultCase("verify.cancel", "verification", "cancelled", 0, terminal="run.cancelled"),
        FaultCase("verify.trace", "verification", "trace_write_failure", 0),
        FaultCase("verify.sse", "verification", "sse_disconnect", 0, terminal="run.cancelled"),
    ))
    return tuple(cases)


def inject_failure(case: FaultCase) -> FaultEvidence:
    """Produce the deterministic contract envelope for a simulated failure.

    This adapter is deliberately limited to failure-path evidence. It never emits a
    success result and cannot stand in for an external-runtime Provider/DB/RAG gate.
    Production classes are exercised separately by in-process pytest injections.
    """
    is_cancel = case.terminal == "run.cancelled"
    return FaultEvidence(
        case_id=case.case_id,
        component=case.component,
        fault=case.fault,
        evidence_kind="SIMULATED_FAULT_CONTRACT",
        retry_count=case.retries_max,
        circuit_observed=case.fault == "circuit_open",
        fallback_observed=case.fallback_expected,
        budget_enforced=case.fault == "budget_exceeded",
        cancel_observed=is_cancel,
        trace_closed=True,
        sse_terminal=case.terminal,
        sse_terminal_count=1,
        infinite_retry_count=0,
        duplicate_final_count=0,
        stale_answer_count=0,
        fail_closed=True,
        resource_released=True,
        external_runtime_success_claim=False,
    )


def run_fault_matrix() -> dict[str, Any]:
    evidence = [inject_failure(case) for case in build_fault_matrix()]
    failures = [
        item.case_id for item in evidence
        if not (
            item.fail_closed
            and item.resource_released
            and item.trace_closed
            and item.sse_terminal_count == 1
            and item.infinite_retry_count == 0
            and item.duplicate_final_count == 0
            and item.stale_answer_count == 0
            and not item.external_runtime_success_claim
        )
    ]
    components = Counter(item.component.split(":", 1)[0] for item in evidence)
    return {
        "status": "CONTRACT_PASS" if not failures else "FAIL",
        "evidence_kind": "SIMULATED_FAULT_CONTRACT",
        "external_runtime_success_claim": False,
        "case_count": len(evidence),
        "component_counts": dict(sorted(components.items())),
        "infinite_retry_count": sum(item.infinite_retry_count for item in evidence),
        "duplicate_final_count": sum(item.duplicate_final_count for item in evidence),
        "stale_answer_count": sum(item.stale_answer_count for item in evidence),
        "fail_closed_count": sum(item.fail_closed for item in evidence),
        "resource_released_count": sum(item.resource_released for item in evidence),
        "failures": failures,
        "cases": [asdict(item) for item in evidence],
    }


def _default_executor(command: Sequence[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    package_sources = [
        PROJECT_ROOT / "backend",
        *(path / "src" for path in (PROJECT_ROOT / "packages").iterdir() if path.is_dir() and (path / "src").is_dir()),
    ]
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join([
        *(str(path) for path in package_sources),
        *([existing_pythonpath] if existing_pythonpath else []),
    ])
    return subprocess.run(
        list(command),
        cwd=PROJECT_ROOT / "backend",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
        check=False,
    )


def run_phase_regressions(
    *,
    timeout_seconds: int = 300,
    executor: Callable[..., subprocess.CompletedProcess[str]] = _default_executor,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for spec in PHASE_REGRESSIONS:
        command = spec.command()
        started = perf_counter()
        try:
            completed = executor(command, timeout=timeout_seconds)
            returncode = int(completed.returncode)
            stdout = str(completed.stdout or "")[-8_000:]
            stderr = str(completed.stderr or "")[-8_000:]
        except subprocess.TimeoutExpired as exc:
            returncode = 124
            stdout = str(exc.stdout or "")[-8_000:]
            stderr = f"phase regression timeout after {timeout_seconds}s"
        result = {
            "phase": spec.phase,
            "status": "PASS" if returncode == 0 else "FAIL",
            "returncode": returncode,
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            "command": command,
            "stdout_tail": stdout,
            "stderr_tail": stderr,
        }
        results.append(result)
        if returncode != 0:
            break
    return {
        "status": "PASS" if len(results) == len(PHASE_REGRESSIONS) and all(item["returncode"] == 0 for item in results) else "FAIL",
        "executed_phase_count": len(results),
        "expected_phase_count": len(PHASE_REGRESSIONS),
        "results": results,
    }


def run_production_class_fault_regression(
    *,
    timeout_seconds: int = 300,
    executor: Callable[..., subprocess.CompletedProcess[str]] = _default_executor,
) -> dict[str, Any]:
    command = PRODUCTION_CLASS_FAULT_REGRESSION.command()
    started = perf_counter()
    try:
        completed = executor(command, timeout=timeout_seconds)
        returncode = int(completed.returncode)
        stdout = str(completed.stdout or "")[-8_000:]
        stderr = str(completed.stderr or "")[-8_000:]
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        stdout = str(exc.stdout or "")[-8_000:]
        stderr = f"production-class fault regression timeout after {timeout_seconds}s"
    return {
        "status": "PASS" if returncode == 0 else "FAIL",
        "evidence_kind": "IN_PROCESS_PRODUCTION_CLASS_FAULT_INJECTION",
        "external_runtime_success_claim": False,
        "returncode": returncode,
        "duration_ms": round((perf_counter() - started) * 1000, 3),
        "command": command,
        "coverage_map": PRODUCTION_CLASS_FAULT_COVERAGE_MAP,
        "test_node_count": len(PRODUCTION_CLASS_FAULT_REGRESSION.paths),
        "stdout_tail": stdout,
        "stderr_tail": stderr,
    }


def build_report(
    *,
    run_regressions: bool,
    timeout_seconds: int,
    run_fault_tests: bool | None = None,
) -> dict[str, Any]:
    if run_fault_tests is None:
        run_fault_tests = run_regressions
    weird = validate_weird_manifest(load_json(WEIRD_MANIFEST))
    complex_cases = validate_complex_manifest(load_json(COMPLEX_MANIFEST))
    faults = run_fault_matrix()
    production_class_faults = (
        run_production_class_fault_regression(timeout_seconds=timeout_seconds)
        if run_fault_tests
        else {
            "status": "NOT_RUN",
            "evidence_kind": "IN_PROCESS_PRODUCTION_CLASS_FAULT_INJECTION",
            "external_runtime_success_claim": False,
            "reason": "in-process production-class fault injection tests were not executed",
        }
    )
    regressions = (
        run_phase_regressions(timeout_seconds=timeout_seconds)
        if run_regressions
        else {
            "status": "NOT_RUN",
            "reason": "Phase 1-4 regressions were explicitly not selected; no Phase 1-4 PASS is claimed",
            "executed_phase_count": 0,
            "expected_phase_count": len(PHASE_REGRESSIONS),
            "results": [],
        }
    )
    checks_pass = weird["status"] == complex_cases["status"] == "PASS" and faults["status"] == "CONTRACT_PASS"
    if checks_pass and regressions["status"] == "PASS" and production_class_faults["status"] == "PASS":
        status = "PASS"
    elif checks_pass and regressions["status"] == "NOT_RUN" and production_class_faults["status"] == "PASS":
        status = "FAULT_PASS"
    elif checks_pass and regressions["status"] == "NOT_RUN" and production_class_faults["status"] == "NOT_RUN":
        status = "CONTRACT_PASS"
    else:
        status = "FAIL"
    return {
        "schema_version": "chatbi-v1.3-phase5-fault-regression-gate-v1",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "external_runtime_success_claim": False,
        "executed_regression_claim": status in {"PASS", "FAULT_PASS"},
        "weird_50": weird,
        "complex_5": complex_cases,
        "fault_injection_contract": faults,
        "production_class_fault_injection_tests": production_class_faults,
        "phase_1_to_4_regressions": regressions,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ChatBI V1.3 Phase 5 fault/regression gate")
    parser.add_argument(
        "--contract-only",
        action="store_true",
        help="Validate manifests and injected-failure contracts without claiming Phase 1-4 PASS.",
    )
    parser.add_argument(
        "--faults-only",
        action="store_true",
        help="Execute in-process production-class fault injections without Phase 1-4 regressions.",
    )
    parser.add_argument("--phase-timeout-seconds", type=int, default=300)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.contract_only and args.faults_only:
        parser.error("--contract-only and --faults-only are mutually exclusive")
    if args.phase_timeout_seconds < 1:
        parser.error("--phase-timeout-seconds must be positive")
    try:
        report = build_report(
            run_regressions=not args.contract_only and not args.faults_only,
            timeout_seconds=args.phase_timeout_seconds,
            run_fault_tests=not args.contract_only,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"PASS", "FAULT_PASS", "CONTRACT_PASS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
