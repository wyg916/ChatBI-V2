from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import Settings
from app.file_multimodal import FileParseError, parse_attachment
from app.model_gateway import (
    BudgetMode,
    ModelCapability,
    ModelGateway,
    ModelBudgetExceeded,
    ModelRequest,
    ModelUnavailable,
)
from app.sandbox import DockerSandboxExecutor, SandboxStatus
from chatbi_rag_adapter import LiveRagAdapter, RagAdapterError
from chatbi_rag_contracts import RagExecutionContext, RagRequest
from app.query.contracts import ExecutionResult
from app.query.explain_cost import ExplainCostGuard
from app.streaming.lifecycle import StreamRegistry
from app.streaming.protocol import StreamEventFactory
from scripts.run_v13_phase5_fault_regression_gate import (
    COMPLEX_MANIFEST,
    PHASE_REGRESSIONS,
    WEIRD_MANIFEST,
    build_fault_matrix,
    build_report,
    load_json,
    run_fault_matrix,
    run_phase_regressions,
    run_production_class_fault_regression,
    validate_complex_manifest,
    validate_weird_manifest,
)


def test_weird_50_is_frozen_exact_and_covers_route_refusal_clarification_zero_model_cost_and_no_hallucination():
    report = validate_weird_manifest(load_json(WEIRD_MANIFEST))
    assert report["status"] == "PASS"
    assert report["case_count"] == 50
    assert len(report["category_counts"]) == 14
    assert report["category_counts"] == {
        "abstract": 3,
        "ambiguous": 4,
        "date_trap": 4,
        "fragment": 3,
        "hallucination": 4,
        "irrelevant": 4,
        "long": 3,
        "malicious": 4,
        "mixed_language": 3,
        "nonexistent_data": 3,
        "prompt_injection": 4,
        "sql_injection": 4,
        "typo": 4,
        "unauthorized": 3,
    }
    assert report["zero_model_case_count"] >= 25
    assert report["hallucination_allowed_count"] == 0
    assert report["dangerous_sql_execution_allowed_count"] == 0
    payload = load_json(WEIRD_MANIFEST)
    actions = {case["expected"]["action"] for case in payload["cases"]}
    assert set(payload["answer_contracts"]) == actions
    assert all(
        payload["answer_contracts"][action]["claim_mode"]
        in {"NONE", "SAFE_ONLY", "DATE_ONLY", "EMPTY_ONLY", "VERIFIED_ONLY"}
        for action in actions
    )


def test_weird_50_tampering_fails_closed():
    payload = load_json(WEIRD_MANIFEST)
    payload["cases"][7]["expected"]["hallucination_allowed"] = True
    with pytest.raises(ValueError, match="hallucination"):
        validate_weird_manifest(payload)
    contract = load_json(WEIRD_MANIFEST)
    contract["answer_contracts"].pop("REFUSE")
    with pytest.raises(ValueError, match="answer contract"):
        validate_weird_manifest(contract)


def test_complex_5_has_all_five_families_and_every_evidence_dimension():
    report = validate_complex_manifest(load_json(COMPLEX_MANIFEST))
    assert report == {
        "status": "PASS",
        "case_count": 5,
        "kinds": ["AGENT_PYTHON", "AGENT_SQL", "DATA_RAG", "FILE_DB", "MULTI_STEP_DATA"],
        "evidence_dimensions": ["accuracy", "cancel", "cost", "latency", "steps", "tools", "verification"],
        "verification_case_count": 5,
        "accuracy_threshold_min": 0.95,
        "latency_budget_max_ms": 30000,
        "cost_budgeted_case_count": 5,
        "cancellable_case_count": 5,
    }
    payload = load_json(COMPLEX_MANIFEST)
    assert all(case["expected"]["stale_answer_count"] == 0 for case in payload["cases"])
    assert any(case["expected"].get("sandbox_destroyed_required") for case in payload["cases"])
    assert any(case["expected"].get("file_signature_required") for case in payload["cases"])
    assert all(set(case["expected"]["expected_evidence"]) == {"result", "citation", "file", "sandbox"} for case in payload["cases"])
    file_case = next(case for case in payload["cases"] if case["kind"] == "FILE_DB")
    assert file_case["expected"]["expected_evidence"]["file"] == {
        "required": True,
        "sha256": "56f70a1be361d0f4353096783cd6319d2e3bc7d6115298c06acee33827fac308",
        "row_count": 4,
        "columns": ["month", "region", "revenue", "cost"],
        "revenue_sum": 4430,
        "cost_sum": 2970,
    }


def test_complex_5_rejects_unknown_agent_tool_and_missing_verification():
    unknown = load_json(COMPLEX_MANIFEST)
    unknown["cases"][0]["steps"][1]["tool"] = "RUN_ARBITRARY_COMMAND"
    with pytest.raises(ValueError, match="six-tool"):
        validate_complex_manifest(unknown)
    unverified = load_json(COMPLEX_MANIFEST)
    unverified["cases"][1]["expected"]["verification_required"] = False
    with pytest.raises(ValueError, match="mandatory verification"):
        validate_complex_manifest(unverified)
    unfrozen = load_json(COMPLEX_MANIFEST)
    unfrozen["cases"][4]["expected"]["expected_evidence"]["file"]["row_count"] = 5
    with pytest.raises(ValueError, match="file evidence"):
        validate_complex_manifest(unfrozen)


def test_fault_matrix_is_exactly_scoped_and_all_fail_closed_with_release_evidence():
    matrix = build_fault_matrix()
    report = run_fault_matrix()
    providers = [case for case in matrix if case.component.startswith("provider:")]
    provider_coverage = Counter(case.component for case in providers)
    assert provider_coverage == {
        "provider:mimo": 6,
        "provider:deepseek": 6,
        "provider:kimi": 6,
    }
    assert {case.fault for case in providers} == {
        "http_429", "timeout", "http_5xx", "slow", "invalid_response", "connection_reset"
    }
    assert {case.component.split(":", 1)[0] for case in matrix} == {
        "provider", "database", "rag", "agent_tool", "python_sandbox", "file", "vision", "verification"
    }
    assert report["status"] == "CONTRACT_PASS"
    assert report["case_count"] == 40
    assert report["infinite_retry_count"] == 0
    assert report["duplicate_final_count"] == 0
    assert report["stale_answer_count"] == 0
    assert report["fail_closed_count"] == report["case_count"]
    assert report["resource_released_count"] == report["case_count"]
    assert report["evidence_kind"] == "SIMULATED_FAULT_CONTRACT"
    assert report["external_runtime_success_claim"] is False


@pytest.mark.parametrize("provider", ["mimo", "deepseek", "kimi"])
@pytest.mark.parametrize(
    "fault",
    ["http_429", "timeout", "http_5xx", "slow", "invalid_response", "connection_reset"],
)
def test_production_model_gateway_class_fails_closed_for_provider_fault_matrix(provider: str, fault: str):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if fault == "http_429":
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "phase5 injected"})
        if fault == "http_5xx":
            return httpx.Response(503, json={"error": "phase5 injected"})
        if fault in {"timeout", "slow"}:
            raise httpx.ReadTimeout("phase5 injected", request=request)
        if fault == "connection_reset":
            raise httpx.ReadError("phase5 injected", request=request)
        return httpx.Response(200, json={"model": "invalid-without-choices"})

    secrets = {
        "mimo_api_key": "phase5-secret-mimo" if provider == "mimo" else "",
        "deepseek_api_key": "phase5-secret-deepseek" if provider == "deepseek" else "",
        "kimi_api_key": "phase5-secret-kimi" if provider == "kimi" else "",
    }
    gateway = ModelGateway(
        Settings(_env_file=None, **secrets),
        transport=httpx.MockTransport(handler),
        sleeper=lambda _: None,
    )
    request = ModelRequest(
        capability=ModelCapability.GENERAL,
        messages=({"role": "user", "content": "phase5 fault probe"},),
        requested_alias=provider,
        budget_mode=BudgetMode.QUALITY if provider == "kimi" else BudgetMode.BALANCED,
        complexity_score=90 if provider == "kimi" else 25,
        max_output_tokens=32,
    )
    with pytest.raises(ModelUnavailable) as caught:
        gateway.execute(request)
    assert gateway.last_response is None
    assert len(calls) <= (1 if provider == "kimi" or fault == "invalid_response" else 2)
    assert len(calls) >= 1
    assert "phase5-secret" not in str(caught.value)


def test_model_gateway_fallback_exhaustion_and_budget_rejection_fail_before_answer(monkeypatch):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(503, json={"error": "phase5 injected"})

    gateway = ModelGateway(
        Settings(
            _env_file=None,
            mimo_api_key="phase5-secret-mimo",
            deepseek_api_key="phase5-secret-deepseek",
            kimi_api_key="",
        ),
        transport=httpx.MockTransport(handler),
        sleeper=lambda _: None,
    )
    request = ModelRequest(
        capability=ModelCapability.GENERAL,
        messages=({"role": "user", "content": "phase5 fallback probe"},),
        max_output_tokens=32,
    )
    with pytest.raises(ModelUnavailable):
        gateway.execute(request)
    assert len(calls) == 4
    assert gateway.last_response is None

    budget_gateway = ModelGateway(
        Settings(_env_file=None, mimo_api_key="phase5-secret-mimo"),
        transport=httpx.MockTransport(lambda _request: pytest.fail("budget rejection must precede network")),
    )
    monkeypatch.setattr(budget_gateway.policy, "within_budget", lambda *_args, **_kwargs: False)
    with pytest.raises(ModelBudgetExceeded):
        budget_gateway.execute(request)
    assert budget_gateway.last_response is None


@pytest.mark.parametrize("fault", ["runtime", "retriever", "reranker"])
def test_production_rag_adapter_class_retries_then_fails_closed_for_rag_faults(fault: str):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(fault)
        return httpx.Response(503, request=request, json={"error_code": f"{fault.upper()}_FAILED"})

    transport = httpx.MockTransport(handler)

    def client_factory(**kwargs):
        return httpx.Client(transport=transport, **kwargs)

    adapter = LiveRagAdapter(
        base_url="http://rag-runtime.invalid",
        retry_count=1,
        client_factory=client_factory,
    )
    request = RagRequest(
        query="phase5 governed knowledge",
        scenario_id="charging_ops",
        limit=5,
        context=RagExecutionContext(
            workspace_id="workspace-phase5",
            user_id="user-phase5",
            roles=frozenset({"ANALYST"}),
            allowed_datasources=frozenset(),
            allowed_semantic_models=frozenset(),
            allowed_tools=frozenset({"RETRIEVE_KNOWLEDGE"}),
            trace_id="TRACE-phase5-rag-fault",
            timeout_ms=5000,
            max_steps=8,
            token_budget=1024,
        ),
    )
    with pytest.raises(RagAdapterError):
        adapter.retrieve(request)
    assert calls == [fault, fault]


@pytest.mark.parametrize(
    ("status", "rows", "expected_status", "expected_reason"),
    [
        ("TIMEOUT", [], "ERROR", "QUERY_TIMEOUT"),
        ("FAILED", [], "ERROR", "DATABASE_CONNECTION_FAILED"),
        ("SUCCEEDED", [{"plan": {"Plan": {"Total Cost": 999999}}}], "BLOCKED", "QUERY_COST_LIMIT_EXCEEDED"),
    ],
)
def test_database_slow_failure_and_explain_reject_are_fail_closed(status, rows, expected_status, expected_reason):
    result = ExecutionResult(
        status=status,
        rows=rows,
        row_count=len(rows),
        duration_ms=45_000 if status == "TIMEOUT" else 2,
        datasource_id="phase5-datasource",
        dialect="postgresql",
        normalized_sql="EXPLAIN (FORMAT JSON) SELECT 1",
        error_code=(
            "QUERY_TIMEOUT" if status == "TIMEOUT" else
            "DATABASE_CONNECTION_FAILED" if status == "FAILED" else None
        ),
    )
    assessment = ExplainCostGuard().assess(result, maximum_cost=100)
    assert assessment.status == expected_status
    assert assessment.reason == expected_reason


def test_streaming_fault_has_one_terminal_no_duplicate_final_and_registry_releases_workloads():
    factory = StreamEventFactory(
        run_id="TRACE-phase5-fault",
        request_id="REQ-phase5-fault",
        conversation_id="conversation-phase5",
        message_id="message-phase5",
    )
    events = [
        factory.create("run.started", status="RUNNING"),
        factory.create("phase.started", phase="verifying"),
        factory.create("run.failed", status="FAILED", error_code="VERIFY_FAILED"),
    ]
    with pytest.raises(RuntimeError, match="after terminal"):
        factory.create("run.completed", status="SUCCEEDED")
    assert sum(item["event_type"].startswith("run.") and item["event_type"] in {"run.failed", "run.completed", "run.cancelled"} for item in events) == 1

    registry = StreamRegistry()
    lifecycle = registry.register(
        "TRACE-phase5-release",
        conversation_id="conversation-phase5",
        client_message_id="client-phase5",
    )
    registry.task_started(lifecycle.trace_id)
    with pytest.raises(RuntimeError, match="injected"):
        with registry.workload("agent"), registry.workload("sandbox"):
            raise RuntimeError("phase5 injected")
    registry.connection_closed(lifecycle.trace_id)
    registry.task_finished(lifecycle.trace_id)
    snapshot = registry.snapshot()
    assert snapshot["active_connections"] == 0
    assert snapshot["active_tasks"] == 0
    assert snapshot["active_agent_tasks"] == 0
    assert snapshot["active_sandbox_tasks"] == 0
    assert snapshot["trace_ids"] == []


def test_file_parse_fault_fails_closed_without_artifact():
    with pytest.raises(FileParseError, match="FILE_SIGNATURE_MISMATCH"):
        parse_attachment("phase5.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", b"not-a-zip")


def test_python_sandbox_oom_and_worker_unavailable_are_unverified_and_destroyed():
    class NotFound(Exception):
        status_code = 404

    class Container:
        id = "phase5-oom-container"

        def __init__(self):
            self.removed = False

        def start(self):
            return None

        def exec_run(self, *_args, **_kwargs):
            return SimpleNamespace(
                exit_code=137,
                output=json.dumps({
                    "status": "FAILED",
                    "error_code": "SANDBOX_MEMORY_LIMIT",
                    "stdout": "",
                    "stderr": "",
                }).encode(),
            )

        def remove(self, force=False):
            self.removed = True

        def kill(self):
            return None

    class Containers:
        def __init__(self, container):
            self.container = container

        def create(self, **_kwargs):
            return self.container

        def get(self, _container_id):
            if self.container.removed:
                raise NotFound()
            return self.container

    class Client:
        def __init__(self, container, *, unavailable=False):
            self.containers = Containers(container)
            self.unavailable = unavailable

        def ping(self):
            if self.unavailable:
                raise RuntimeError("phase5 injected")
            return True

        def close(self):
            return None

    oom_container = Container()
    oom = DockerSandboxExecutor(client_factory=lambda: Client(oom_container)).execute("result = 1", {})
    assert oom.status is SandboxStatus.FAILED
    assert oom.error_code == "SANDBOX_MEMORY_LIMIT"
    assert oom.container_destroyed is True
    assert oom.runtime_verified is False
    assert oom_container.removed is True

    unavailable = DockerSandboxExecutor(
        client_factory=lambda: Client(Container(), unavailable=True)
    ).execute("result = 1", {})
    assert unavailable.status is SandboxStatus.UNAVAILABLE
    assert unavailable.error_code == "SANDBOX_DOCKER_UNAVAILABLE"
    assert unavailable.runtime_verified is False


def test_phase_1_to_4_regression_orchestration_is_ordered_and_stops_on_first_failure():
    observed: list[list[str]] = []

    def passing(command, *, timeout):
        assert timeout == 17
        observed.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="1 passed", stderr="")

    passed = run_phase_regressions(timeout_seconds=17, executor=passing)
    assert passed["status"] == "PASS"
    assert [item["phase"] for item in passed["results"]] == ["phase1", "phase2", "phase3", "phase4"]
    assert len(observed) == len(PHASE_REGRESSIONS)
    assert all(command[:3] == [command[0], "-m", "pytest"] for command in observed)

    calls = 0

    def fail_phase2(command, *, timeout):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            command,
            1 if calls == 2 else 0,
            stdout="injected regression failure" if calls == 2 else "pass",
            stderr="",
        )

    failed = run_phase_regressions(timeout_seconds=17, executor=fail_phase2)
    assert failed["status"] == "FAIL"
    assert failed["executed_phase_count"] == 2
    assert failed["results"][-1]["phase"] == "phase2"


def test_production_class_fault_report_requires_in_process_pytest_execution_and_preserves_failure():
    def passing(command, *, timeout):
        assert timeout == 19
        assert any("test_production_model_gateway_class" in item for item in command)
        assert any("test_timeout_kills_and_synchronously_destroys_container" in item for item in command)
        return subprocess.CompletedProcess(command, 0, stdout="28 passed", stderr="")

    passed = run_production_class_fault_regression(timeout_seconds=19, executor=passing)
    assert passed["status"] == "PASS"
    assert passed["evidence_kind"] == "IN_PROCESS_PRODUCTION_CLASS_FAULT_INJECTION"
    assert passed["external_runtime_success_claim"] is False

    failed = run_production_class_fault_regression(
        timeout_seconds=19,
        executor=lambda command, *, timeout: subprocess.CompletedProcess(
            command, 1, stdout="1 failed", stderr="production boundary failure"
        ),
    )
    assert failed["status"] == "FAIL"
    assert failed["returncode"] == 1


def test_contract_only_report_never_claims_external_runtime_or_phase_regression_pass(tmp_path: Path):
    report = build_report(run_regressions=False, timeout_seconds=1)
    assert report["status"] == "CONTRACT_PASS"
    assert report["external_runtime_success_claim"] is False
    assert report["executed_regression_claim"] is False
    assert report["phase_1_to_4_regressions"]["status"] == "NOT_RUN"
    assert report["fault_injection_contract"]["status"] == "CONTRACT_PASS"
    assert report["production_class_fault_injection_tests"]["status"] == "NOT_RUN"
    serialized = json.dumps(report, ensure_ascii=False)
    assert "no Phase 1-4 PASS is claimed" in serialized
