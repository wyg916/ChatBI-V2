from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.core.config import Settings
from app.model_gateway.configuration import ResolvedProvider
from app.model_gateway.contracts import (
    BudgetMode,
    ModelCapability,
    ModelRequest,
    ModelResponse,
    ModelUsage,
    RequestContext,
)
from app.model_gateway.service import ModelGateway
from app.model_gateway.test_cost_control import (
    TestCostControlError as CostControlError,
    TestCostController as CostController,
)


SHA = "a" * 40


def _passing_runtime_preflight(*, repo_root: Path, expected_git_sha: str) -> dict[str, object]:
    return {
        "status": "PASS",
        "runtime_binding_gate": "PASS",
        "expected_git_sha": expected_git_sha,
        "actual_git_sha": expected_git_sha,
        "candidate_repository_root": str(repo_root),
        "receipt_sha256": "d" * 64,
    }


def _cost_controller(environment: dict[str, str]) -> CostController:
    return CostController(environ=environment, runtime_preflight=_passing_runtime_preflight)


def _provider(provider_id: str = "mimo") -> ResolvedProvider:
    return ResolvedProvider(
        provider_id=provider_id,
        display_name=provider_id,
        base_url=f"https://{provider_id}.invalid/v1",
        api_key="test-only",
        model_name=f"{provider_id}-test",
        max_tokens_field="max_completion_tokens" if provider_id in {"mimo", "kimi"} else "max_tokens",
    )


def _request(*, alias: str = "mimo", complexity: int = 20) -> ModelRequest:
    return ModelRequest(
        capability=ModelCapability.GENERAL,
        messages=({"role": "user", "content": "short test"},),
        requested_alias=alias,
        complexity_score=complexity,
        budget_mode=BudgetMode.BALANCED,
    )


def _context() -> RequestContext:
    return RequestContext(
        request_id="REQ-COST-CONTROL",
        trace_id="TRACE-COST-CONTROL",
        user_id="test-user",
        workspace_id="test-workspace",
    )


def _level0_receipt(tmp_path: Path) -> Path:
    policy = CostController(environ={}).policy
    receipt = tmp_path / "level0.json"
    receipt.write_text(json.dumps({
        "tested_sha": SHA,
        "level0_all_pass": True,
        "gates": {name: "PASS" for name in policy["required_level0_gates"]},
    }), encoding="utf-8")
    return receipt


def _level1_environment(tmp_path: Path, **updates: str) -> dict[str, str]:
    receipt = _level0_receipt(tmp_path)
    environment = {
        "CHATBI_TEST_COST_CONTROL": "YES",
        "CHATBI_TEST_EXECUTION_LEVEL": "LEVEL1",
        "CHATBI_PAID_GATE_AUTHORIZED": "YES",
        "CHATBI_TEST_SHA": SHA,
        "CHATBI_BACKEND_SHA": SHA,
        "CHATBI_TEST_RUN_ID": "RUN-TARGETED-001",
        "CHATBI_TEST_CASE_ID": "CASE-001",
        "CHATBI_TEST_GATE": "targeted_provider_smoke",
        "CHATBI_TEST_AFFECTED_PATH": "model_gateway",
        "CHATBI_TEST_ALLOWED_PROVIDERS": "mimo",
        "CHATBI_TEST_BUDGET_CLASS": "targeted_live_regression",
        "CHATBI_TEST_BUDGET_CNY": "1.0",
        "CHATBI_TEST_COST_LEDGER_ROOT": str(tmp_path),
        "CHATBI_TEST_NECESSITY_DECLARATION": "YES",
        "CHATBI_TEST_DETERMINISTIC_INSUFFICIENT_REASON": "Recorded transport cannot prove the named live provider path.",
        "CHATBI_PROMPT_VERSION": "phase5-test-prompt-v1",
        "CHATBI_LEVEL0_RECEIPT": str(receipt),
    }
    environment.update(updates)
    return environment


def _level2_environment(tmp_path: Path, *, run_id: str = "RUN-FINAL-001", **updates: str) -> dict[str, str]:
    receipt = _level0_receipt(tmp_path)
    environment = _level1_environment(tmp_path)
    environment.update({
        "CHATBI_TEST_EXECUTION_LEVEL": "LEVEL2",
        "CHATBI_TEST_RUN_ID": run_id,
        "CHATBI_TEST_FINAL_SHA": SHA,
        "CHATBI_FINAL_CERTIFICATION": "YES",
        "CHATBI_PAID_TEST_CACHE_BYPASS": "YES",
        "CHATBI_LEVEL0_RECEIPT": str(receipt),
        "CHATBI_TEST_BUDGET_CLASS": "final_certification",
        "CHATBI_TEST_BUDGET_CNY": "3.0",
        "CHATBI_TEST_AFFECTED_PATH": "",
        "CHATBI_TEST_ALLOWED_PROVIDERS": "mimo,deepseek,kimi",
    })
    environment.update(updates)
    return environment


def _final_environment(tmp_path: Path, *, run_id: str = "RUN-OWNER-FINAL-001", **updates: str) -> dict[str, str]:
    environment = _level2_environment(tmp_path, run_id=run_id)
    environment["CHATBI_TEST_EXECUTION_LEVEL"] = "FINAL"
    environment.update(updates)
    return environment


def test_level0_blocks_real_transport_before_any_http_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATBI_TEST_COST_CONTROL", "YES")
    monkeypatch.setenv("CHATBI_TEST_EXECUTION_LEVEL", "LEVEL0")
    gateway = ModelGateway(
        Settings(_env_file=None),
        provider_overrides={"mimo": _provider()},
    )

    with pytest.raises(CostControlError, match="LEVEL0_PAID_PROVIDER_CALL_BLOCKED"):
        gateway.execute(_request(), _context())


def test_level0_allows_mock_transport_and_preserves_recorded_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATBI_TEST_COST_CONTROL", "YES")
    monkeypatch.setenv("CHATBI_TEST_EXECUTION_LEVEL", "LEVEL0")
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "mimo-test",
                "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    gateway = ModelGateway(
        Settings(_env_file=None),
        provider_overrides={"mimo": _provider()},
        transport=httpx.MockTransport(handler),
    )
    result = gateway.execute(_request(), _context())

    assert result.content == "OK"
    assert observed["max_completion_tokens"] == 4096
    assert gateway.test_cost_control.limit_output_tokens(4096) == 512
    assert gateway.test_cost_control.summary()["paid_test_calls"] == 0


def test_final_complex_route_uses_complex_output_cap_under_generic_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHATBI_TEST_COST_CONTROL", "YES")
    monkeypatch.setenv("CHATBI_TEST_EXECUTION_LEVEL", "FINAL")
    monkeypatch.setenv("CHATBI_TEST_GATE", "FINAL_REAL_PROVIDER_RECERTIFICATION")
    gateway = ModelGateway(
        Settings(_env_file=None),
        provider_overrides={"mimo": _provider()},
    )
    request = _request().model_copy(update={"max_output_tokens": 4096})
    data_context = _context().model_copy(update={"route": "DATA_QUERY"})
    complex_context = _context().model_copy(update={"route": "COMPLEX_ANALYSIS"})

    assert gateway._payload(
        _provider(), request, stream=False, context=data_context,
    )["max_completion_tokens"] == 512
    assert gateway._payload(
        _provider(), request, stream=False, context=complex_context,
    )["max_completion_tokens"] == 1024


def test_level1_requires_explicit_authorization_and_scope(tmp_path: Path) -> None:
    environment = _level1_environment(tmp_path, CHATBI_PAID_GATE_AUTHORIZED="NO")
    controller = _cost_controller(environment)
    with pytest.raises(CostControlError, match="PAID_GATE_AUTHORIZED_REQUIRED"):
        controller.validate_configuration()

    environment = _level1_environment(tmp_path, CHATBI_TEST_AFFECTED_PATH="database")
    controller = _cost_controller(environment)
    with pytest.raises(CostControlError, match="PAID_TEST_AFFECTED_PATH_NOT_ALLOWED"):
        controller.validate_configuration()

    environment = _level1_environment(tmp_path, CHATBI_TEST_ALLOWED_PROVIDERS="")
    controller = _cost_controller(environment)
    with pytest.raises(CostControlError, match="CHATBI_TEST_ALLOWED_PROVIDERS"):
        controller.validate_configuration()

    environment = _level1_environment(tmp_path, CHATBI_TEST_BUDGET_CLASS="final_certification")
    with pytest.raises(CostControlError, match="TEST_BUDGET_CLASS_NOT_ALLOWED_FOR_LEVEL"):
        _cost_controller(environment).validate_configuration()

    environment = _level1_environment(tmp_path, CHATBI_BACKEND_SHA="b" * 40)
    with pytest.raises(CostControlError, match="BACKEND_SHA_MUST_MATCH_TEST_SHA"):
        _cost_controller(environment).validate_configuration()

    environment = _level1_environment(tmp_path, CHATBI_TEST_NECESSITY_DECLARATION="NO")
    with pytest.raises(CostControlError, match="NECESSITY_DECLARATION_MUST_BE_YES"):
        _cost_controller(environment).validate_configuration()


def test_paid_cost_gate_rejects_runtime_binding_failure_before_reservation(tmp_path: Path) -> None:
    def blocked_preflight(**_kwargs):
        from app.certification.runtime_binding import RuntimeBindingError

        raise RuntimeBindingError(
            "EXACT_SHA_RUNTIME_PREFLIGHT_FAILED",
            receipt={"failures": ["PTH_OUTSIDE_CANDIDATE:stale.pth:old-worktree"]},
        )

    controller = CostController(
        environ=_level1_environment(tmp_path),
        runtime_preflight=blocked_preflight,
    )
    with pytest.raises(CostControlError, match="EXACT_SHA_RUNTIME_PREFLIGHT_FAILED"):
        controller.reserve_attempt(
            provider="mimo",
            model="mimo-test",
            request=_request(),
            context=_context(),
            estimated_cost_cny=0,
            retry_count=0,
            recorded_transport=False,
        )
    assert not (tmp_path / "phase5-paid-test-ledger.sqlite3").exists()


def test_level1_reserves_and_records_complete_sanitized_cost_ledger(tmp_path: Path) -> None:
    controller = _cost_controller(_level1_environment(tmp_path))
    attempt = controller.reserve_attempt(
        provider="mimo",
        model="mimo-test",
        request=_request(),
        context=_context(),
        estimated_cost_cny=0.05,
        retry_count=0,
        recorded_transport=False,
    )
    assert attempt is not None
    response = ModelResponse(
        content="not persisted in test ledger",
        requested_alias="mimo",
        resolved_provider="mimo",
        resolved_model="mimo-test",
        usage=ModelUsage(input_tokens=12, cached_input_tokens=2, output_tokens=4, total_tokens=16, exact=True),
        cost_cny=0.02,
        latency_ms=37,
        retry_count=0,
    )
    controller.complete_attempt(attempt, status="SUCCEEDED", response=response)

    summary = controller.summary()
    assert summary["paid_test_calls"] == 1
    assert summary["paid_test_cost_cny"] == 0.02
    assert summary["cost_by_provider"] == {"mimo": 0.02}
    assert summary["cost_by_gate"] == {"targeted_provider_smoke": 0.02}
    assert summary["input_tokens"] == 12
    assert summary["cached_input_tokens"] == 2
    assert summary["output_tokens"] == 4
    ledger = tmp_path / "phase5-paid-test-ledger.sqlite3"
    assert "not persisted" not in ledger.read_bytes().decode("utf-8", errors="ignore")
    assert summary["necessity_declarations_complete"] is True
    assert summary["untracked_paid_calls"] == 0
    assert summary["unnecessary_duplicate_paid_calls"] == 0
    assert summary["unbounded_retry"] == 0
    assert summary["daily_cost_before_cny"] == 0
    assert summary["daily_cost_after_cny"] == 0.05
    assert summary["paid_ledger_schema_version"] == 3
    assert summary["trace_ids"] == ["TRACE-COST-CONTROL"]
    assert summary["request_ids"] == ["REQ-COST-CONTROL"]
    assert summary["latency_ms"] == [37]
    assert summary["premium_escalations"] == [False]
    assert summary["paid_ledger_required_field_completeness"] == 100.0


def test_served_backend_exposes_only_cost_control_runtime_identity(
    client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _level1_environment(tmp_path)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        "app.model_gateway.test_cost_control.run_exact_sha_runtime_preflight",
        _passing_runtime_preflight,
    )

    response = client.get("/api/v1/test-cost-control-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["tested_sha"] == payload["backend_sha"] == SHA
    assert len(payload["config_hash"]) == 64
    assert len(payload["ledger_identity"]) == 64
    assert len(payload["runtime_identity_sha256"]) == 64
    assert "ledger_path" not in payload
    assert "deterministic_insufficient_reason" not in payload


def test_level1_enforces_run_budget_before_provider_call(tmp_path: Path) -> None:
    controller = _cost_controller(_level1_environment(tmp_path, CHATBI_TEST_BUDGET_CNY="0.50"))
    with pytest.raises(CostControlError, match="TEST_BUDGET_EXCEEDED"):
        controller.reserve_attempt(
            provider="mimo",
            model="mimo-test",
            request=_request(),
            context=_context(),
            estimated_cost_cny=0.51,
            retry_count=0,
            recorded_transport=False,
        )


def test_level0_paid_exception_is_explicit_and_capped_at_fifty_fen(tmp_path: Path) -> None:
    environment = _level1_environment(tmp_path)
    environment.update({
        "CHATBI_TEST_EXECUTION_LEVEL": "LEVEL0",
        "CHATBI_LEVEL0_PAID_EXCEPTION": "YES",
        "CHATBI_TEST_BUDGET_CLASS": "normal_fix_iteration",
        "CHATBI_TEST_BUDGET_CNY": "0.50",
    })
    controller = _cost_controller(environment)
    assert controller.validate_configuration()["level0_paid_exception"] is True
    with pytest.raises(CostControlError, match="TEST_BUDGET_EXCEEDED"):
        controller.reserve_attempt(
            provider="mimo",
            model="mimo-test",
            request=_request(),
            context=_context(),
            estimated_cost_cny=0.51,
            retry_count=0,
            recorded_transport=False,
        )


def test_duplicate_paid_case_is_blocked_but_one_gateway_retry_is_recorded(tmp_path: Path) -> None:
    controller = _cost_controller(_level1_environment(tmp_path))
    first = controller.reserve_attempt(
        provider="mimo", model="mimo-test", request=_request(), context=_context(),
        estimated_cost_cny=0.01, retry_count=0, recorded_transport=False,
    )
    assert first is not None
    with pytest.raises(CostControlError, match="UNNECESSARY_DUPLICATE_PAID_CALL_BLOCKED"):
        controller.reserve_attempt(
            provider="mimo", model="mimo-test", request=_request(), context=_context(),
            estimated_cost_cny=0.01, retry_count=0, recorded_transport=False,
        )
    retry = controller.reserve_attempt(
        provider="mimo", model="mimo-test", request=_request(), context=_context(),
        estimated_cost_cny=0.01, retry_count=1, recorded_transport=False,
    )
    assert retry is not None
    assert retry.duplicate_key == first.duplicate_key


def test_caller_cannot_switch_ledger_file_to_reset_daily_cap(tmp_path: Path) -> None:
    environment = _level1_environment(
        tmp_path,
        CHATBI_TEST_COST_LEDGER_PATH=str(tmp_path / "alternate.sqlite3"),
    )
    with pytest.raises(CostControlError, match="CALLER_SUPPLIED_LEDGER_PATH_FORBIDDEN"):
        _cost_controller(environment).validate_configuration()


def test_level1_records_actual_cost_then_stops_when_provider_exceeds_estimate(tmp_path: Path) -> None:
    controller = _cost_controller(_level1_environment(tmp_path, CHATBI_TEST_BUDGET_CNY="0.50"))
    attempt = controller.reserve_attempt(
        provider="mimo",
        model="mimo-test",
        request=_request(),
        context=_context(),
        estimated_cost_cny=0.01,
        retry_count=0,
        recorded_transport=False,
    )
    assert attempt is not None
    response = ModelResponse(
        content="bounded",
        requested_alias="mimo",
        resolved_provider="mimo",
        resolved_model="mimo-test",
        usage=ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2, exact=True),
        cost_cny=0.51,
    )
    with pytest.raises(CostControlError, match="actual_run_hard_cap"):
        controller.complete_attempt(attempt, status="SUCCEEDED", response=response)
    assert controller.summary()["paid_test_cost_cny"] == 0.51
    assert controller.summary()["budget_exceeded"] is True


def test_level1_kimi_is_rejected_outside_premium_vision_or_complex_scope(tmp_path: Path) -> None:
    controller = _cost_controller(_level1_environment(
        tmp_path,
        CHATBI_TEST_ALLOWED_PROVIDERS="kimi",
    ))
    with pytest.raises(CostControlError, match="LEVEL1_KIMI"):
        controller.reserve_attempt(
            provider="kimi",
            model="kimi-test",
            request=_request(alias="kimi", complexity=90),
            context=_context(),
            estimated_cost_cny=0.10,
            retry_count=0,
            recorded_transport=False,
        )


def test_level2_requires_same_sha_complete_level0_receipt_and_cache_bypass(tmp_path: Path) -> None:
    environment = _level2_environment(tmp_path)
    configuration = _cost_controller(environment).validate_configuration()
    assert configuration["level"] == "LEVEL2"
    assert configuration["run_budget_cny"] == 3.0

    environment["CHATBI_PAID_TEST_CACHE_BYPASS"] = "NO"
    with pytest.raises(CostControlError, match="PAID_TEST_CACHE_BYPASS_REQUIRED"):
        _cost_controller(environment).validate_configuration()


def test_owner_final_level_enforces_execution_plan_provider_caps_and_vision_reservation(tmp_path: Path) -> None:
    controller = _cost_controller(_final_environment(tmp_path))
    configuration = controller.validate_configuration()
    assert configuration["level"] == "FINAL"
    assert configuration["run_budget_cny"] == 3.0
    plan = configuration["final_provider_execution_plan"]
    assert plan["total_real_provider_call_cap"] == 12
    assert plan["provider_call_caps"] == {"mimo": 4, "deepseek": 4, "kimi": 4}
    assert plan["kimi_reserved_vision"] == 3

    for case_id in ("P5-CANCEL-P5C03-test", "P5-CANCEL-P5C04-test"):
        assert controller.reserve_attempt(
            provider="deepseek", model="deepseek-test", request=_request(alias="deepseek"),
            context=RequestContext(
                request_id=case_id,
                trace_id=f"TRACE-{case_id}",
                route="COMPLEX_ANALYSIS",
            ),
            estimated_cost_cny=0, retry_count=0, recorded_transport=False,
        ) is not None

    optional_context = RequestContext(
        request_id="FINAL-KIMI-TEXT-OPTIONAL",
        trace_id="TRACE-FINAL-KIMI-TEXT-OPTIONAL",
        route="DATA_QUERY",
    )
    optional = controller.reserve_attempt(
        provider="kimi", model="kimi-test", request=_request(alias="kimi"),
        context=optional_context, estimated_cost_cny=0, retry_count=0,
        recorded_transport=False,
    )
    assert optional is not None
    with pytest.raises(CostControlError, match="FINAL_PROVIDER_RESERVED_CAPACITY_REQUIRED:kimi"):
        controller.reserve_attempt(
            provider="kimi", model="kimi-test", request=_request(alias="kimi"),
            context=optional_context, estimated_cost_cny=0, retry_count=1,
            recorded_transport=False,
        )

    for case_id in ("LIVE-M04", "LIVE-M06", "LIVE-M10"):
        assert controller.reserve_attempt(
            provider="kimi", model="kimi-test", request=_request(alias="kimi"),
            context=RequestContext(
                request_id=case_id,
                trace_id=f"TRACE-{case_id}",
                route="MULTIMODAL_QUERY",
            ),
            estimated_cost_cny=0, retry_count=0, recorded_transport=False,
        ) is not None
    with pytest.raises(CostControlError, match="FINAL_PROVIDER_CALL_CAP_EXCEEDED:kimi"):
        controller.reserve_attempt(
            provider="kimi", model="kimi-test", request=_request(alias="kimi"),
            context=optional_context,
            estimated_cost_cny=0, retry_count=1, recorded_transport=False,
        )

    with sqlite3.connect(tmp_path / "phase5-paid-test-ledger.sqlite3") as connection:
        assert connection.execute(
            "SELECT DISTINCT test_level FROM paid_test_calls"
        ).fetchall() == [("FINAL",)]


def test_level2_is_registered_only_once_per_final_sha(tmp_path: Path) -> None:
    first = _cost_controller(_level2_environment(tmp_path, run_id="RUN-FINAL-001"))
    attempt = first.reserve_attempt(
        provider="mimo", model="mimo-test", request=_request(), context=_context(),
        estimated_cost_cny=0.01, retry_count=0, recorded_transport=False,
    )
    assert attempt is not None
    assert first.summary()["level2_runs_per_sha"] == 1

    second = _cost_controller(_level2_environment(
        tmp_path,
        run_id="RUN-FINAL-002",
        CHATBI_TEST_CASE_ID="CASE-002",
    ))
    with pytest.raises(CostControlError, match="LEVEL2_ALREADY_EXECUTED_FOR_SHA"):
        second.reserve_attempt(
            provider="deepseek", model="deepseek-test", request=_request(alias="deepseek"),
            context=RequestContext(request_id="REQ-COST-CONTROL-2", trace_id="TRACE-COST-CONTROL-2"),
            estimated_cost_cny=0.01, retry_count=0, recorded_transport=False,
        )


def test_test_retry_limit_is_one_retry_and_402_is_not_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATBI_TEST_COST_CONTROL", "YES")
    monkeypatch.setenv("CHATBI_TEST_EXECUTION_LEVEL", "LEVEL0")
    gateway = ModelGateway(
        Settings(_env_file=None),
        provider_overrides={"mimo": _provider()},
        transport=httpx.MockTransport(lambda _request: httpx.Response(402, json={"error": "balance"})),
        sleeper=lambda _seconds: pytest.fail("402 must not retry"),
    )
    gateway.health_config = {**gateway.health_config, "retry_attempts": 10}

    with pytest.raises(Exception, match="All configured model providers failed"):
        gateway.execute(_request(), _context())
    assert gateway.test_cost_control.limit_attempts(10) == 2


def _unique_context(*, route: str = "GENERAL_CHAT") -> RequestContext:
    identifier = str(uuid4())
    return RequestContext(
        request_id=f"REQ-{identifier}",
        trace_id=f"TRACE-{uuid4()}",
        route=route,
        user_id="ledger-test-user",
        workspace_id="ledger-test-workspace",
    )


def _zero_cost_response(provider: str, *, latency_ms: int, retry_count: int = 0, fallback_count: int = 0) -> ModelResponse:
    return ModelResponse(
        content="mock-only",
        requested_alias=provider,
        resolved_provider=provider,
        resolved_model=f"{provider}-test",
        usage=ModelUsage(input_tokens=3, cached_input_tokens=1, output_tokens=2, total_tokens=5, exact=True),
        cost_cny=0,
        latency_ms=latency_ms,
        retry_count=retry_count,
        fallback_count=fallback_count,
        fallback_used=fallback_count > 0,
    )


def test_paid_ledger_keeps_provider_local_retry_count_when_response_reports_total_retries(tmp_path: Path) -> None:
    controller = _cost_controller(_level1_environment(tmp_path))
    context = _unique_context()
    request = _request()
    failed = controller.reserve_attempt(
        provider="mimo",
        model="mimo-test",
        request=request,
        context=context,
        estimated_cost_cny=0,
        retry_count=0,
        recorded_transport=False,
        premium_escalation=False,
    )
    controller.complete_attempt(
        failed,
        status="FAILED",
        error_code="HTTP_503",
        latency_ms=10,
    )
    retried = controller.reserve_attempt(
        provider="mimo",
        model="mimo-test",
        request=request,
        context=context,
        estimated_cost_cny=0,
        retry_count=1,
        recorded_transport=False,
        premium_escalation=False,
    )
    controller.complete_attempt(
        retried,
        status="SUCCEEDED",
        response=_zero_cost_response(
            "mimo",
            latency_ms=20,
            retry_count=2,
        ),
        latency_ms=20,
    )

    summary = controller.summary()
    succeeded = next(
        record for record in summary["ledger_records"]
        if record["status"] == "SUCCEEDED"
    )
    assert succeeded["retry_count"] == 1
    assert summary["unbounded_retry"] == 0


def test_paid_ledger_v3_covers_success_failure_retry_fallback_and_premium_without_network(tmp_path: Path) -> None:
    environment = _level1_environment(
        tmp_path,
        CHATBI_TEST_ALLOWED_PROVIDERS="mimo,deepseek,kimi",
        CHATBI_TEST_AFFECTED_PATH="premium",
    )
    controller = _cost_controller(environment)

    nonpremium_context = _unique_context()
    nonpremium = controller.reserve_attempt(
        provider="mimo", model="mimo-test", request=_request(), context=nonpremium_context,
        estimated_cost_cny=0, retry_count=0, recorded_transport=False,
        premium_escalation=False,
    )
    controller.complete_attempt(
        nonpremium,
        status="SUCCEEDED",
        response=_zero_cost_response("mimo", latency_ms=11),
        latency_ms=11,
    )

    retry_context = _unique_context(route="DATA_QUERY")
    retry_request = _request(alias="deepseek")
    failed = controller.reserve_attempt(
        provider="deepseek", model="deepseek-test", request=retry_request, context=retry_context,
        estimated_cost_cny=0, retry_count=0, recorded_transport=False,
        premium_escalation=False,
    )
    controller.complete_attempt(failed, status="FAILED", error_code="HTTP_500", latency_ms=13)
    retried = controller.reserve_attempt(
        provider="deepseek", model="deepseek-test", request=retry_request, context=retry_context,
        estimated_cost_cny=0, retry_count=1, recorded_transport=False,
        premium_escalation=False,
    )
    controller.complete_attempt(
        retried,
        status="SUCCEEDED",
        response=_zero_cost_response("deepseek", latency_ms=17, retry_count=1),
        latency_ms=17,
    )

    fallback_context = _unique_context(route="KNOWLEDGE_QUERY")
    fallback = controller.reserve_attempt(
        provider="mimo", model="mimo-test", request=_request(), context=fallback_context,
        estimated_cost_cny=0, retry_count=0, recorded_transport=False, fallback_count=1,
        premium_escalation=False,
    )
    controller.complete_attempt(
        fallback,
        status="SUCCEEDED",
        response=_zero_cost_response("mimo", latency_ms=19, fallback_count=1),
        latency_ms=19,
    )

    premium_context = _unique_context(route="COMPLEX_ANALYSIS")
    premium_request = ModelRequest(
        capability=ModelCapability.GENERAL,
        messages=({"role": "user", "content": "bounded premium simulation"},),
        requested_alias="auto",
        complexity_score=90,
        budget_mode=BudgetMode.QUALITY,
        premium_triggers=frozenset({"explicit_deep_analysis"}),
    )
    premium = controller.reserve_attempt(
        provider="kimi", model="kimi-test", request=premium_request, context=premium_context,
        estimated_cost_cny=0, retry_count=0, recorded_transport=False,
        premium_escalation=True,
    )
    controller.complete_attempt(
        premium,
        status="SUCCEEDED",
        response=_zero_cost_response("kimi", latency_ms=23),
        latency_ms=23,
    )

    summary = controller.summary()
    assert summary["paid_test_calls"] == 5
    assert summary["paid_test_cost_cny"] == 0
    assert summary["paid_ledger_schema_version"] == 3
    assert summary["paid_ledger_required_field_completeness"] == 100.0
    assert {record["status"] for record in summary["ledger_records"]} == {"SUCCEEDED", "FAILED"}
    assert {record["error_code"] for record in summary["ledger_records"]} == {"NONE", "HTTP_500"}
    assert any(record["retry_count"] == 1 for record in summary["ledger_records"])
    assert any(record["fallback_count"] == 1 for record in summary["ledger_records"])
    assert any(record["premium_escalation"] == 1 for record in summary["ledger_records"])
    assert all(record["trace_id"].startswith("TRACE-") for record in summary["ledger_records"])
    assert all(record["request_id"].startswith("REQ-") for record in summary["ledger_records"])
    assert all(record["latency_ms"] > 0 for record in summary["ledger_records"])
    assert summary["token_usage_unknown_calls"] == 1
    assert summary["provider_reported_cost_unknown_calls"] == 5
    assert summary["external_provider_total_billing"] == "UNKNOWN_PARTIAL"


def test_model_gateway_supplies_runtime_identity_timing_and_premium_decision_to_ledger(tmp_path: Path) -> None:
    environment = _level1_environment(
        tmp_path,
        CHATBI_TEST_ALLOWED_PROVIDERS="kimi",
        CHATBI_TEST_AFFECTED_PATH="premium",
    )
    controller = _cost_controller(environment)
    original_reserve = controller.reserve_attempt

    def record_mock_transport(**kwargs):
        kwargs["recorded_transport"] = False
        return original_reserve(**kwargs)

    controller.reserve_attempt = record_mock_transport  # type: ignore[method-assign]
    gateway = ModelGateway(
        Settings(_env_file=None),
        provider_overrides={"kimi": _provider("kimi")},
        transport=httpx.MockTransport(lambda _request: httpx.Response(
            200,
            json={
                "model": "kimi-test",
                "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            },
        )),
    )
    gateway.test_cost_control = controller
    context = _unique_context(route="COMPLEX_ANALYSIS")
    request = ModelRequest(
        capability=ModelCapability.GENERAL,
        messages=({"role": "user", "content": "mock premium route"},),
        requested_alias="auto",
        complexity_score=90,
        budget_mode=BudgetMode.QUALITY,
        premium_triggers=frozenset({"explicit_deep_analysis"}),
    )

    response = gateway.execute(request, context)
    record = controller.summary()["ledger_records"][0]

    assert response.resolved_provider == "kimi"
    assert record["trace_id"] == context.trace_id
    assert record["request_id"] == context.request_id
    assert record["capability"] == request.capability.value
    assert record["route"] == context.route
    assert record["latency_ms"] >= 0
    assert record["premium_escalation"] == 1


def test_paid_ledger_v1_is_upgraded_without_destroying_historical_rows(tmp_path: Path) -> None:
    ledger = tmp_path / "phase5-paid-test-ledger.sqlite3"
    connection = sqlite3.connect(ledger)
    connection.execute(
        """
        CREATE TABLE paid_test_calls (
          call_id TEXT PRIMARY KEY, test_date TEXT NOT NULL, test_run_id TEXT NOT NULL,
          test_level TEXT NOT NULL, git_sha TEXT NOT NULL, backend_sha TEXT NOT NULL,
          config_hash TEXT NOT NULL, prompt_version TEXT NOT NULL, case_id TEXT NOT NULL,
          gate_name TEXT NOT NULL, necessity_declaration TEXT NOT NULL,
          deterministic_insufficient_reason TEXT NOT NULL, provider TEXT NOT NULL,
          model TEXT NOT NULL, status TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0,
          cached_input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
          reserved_cost_cny REAL NOT NULL, actual_cost_cny REAL NOT NULL DEFAULT 0,
          retry_count INTEGER NOT NULL DEFAULT 0, fallback_count INTEGER NOT NULL DEFAULT 0,
          duplicate_key TEXT NOT NULL, daily_cost_before_cny REAL NOT NULL,
          daily_cost_after_cny REAL NOT NULL, error_code TEXT, created_at TEXT NOT NULL,
          completed_at TEXT
        )
        """
    )
    connection.execute(
        """INSERT INTO paid_test_calls (
          call_id, test_date, test_run_id, test_level, git_sha, backend_sha, config_hash,
          prompt_version, case_id, gate_name, necessity_declaration,
          deterministic_insufficient_reason, provider, model, status, reserved_cost_cny,
          actual_cost_cny, duplicate_key, daily_cost_before_cny, daily_cost_after_cny,
          created_at
        ) VALUES ('legacy-call', '2026-08-25', 'LEGACY-RUN', 'LEVEL1', ?, ?, ?,
          'legacy-prompt', 'legacy-case', 'legacy-gate', 'YES', 'historical reason',
          'mimo', 'mimo-old', 'SUCCEEDED', 0.1, 0.05, 'legacy-duplicate', 0, 0.1,
          '2026-08-25T00:00:00+08:00')""",
        (SHA, SHA, "c" * 64),
    )
    connection.commit()
    connection.close()

    controller = _cost_controller(_level1_environment(tmp_path))
    attempt = controller.reserve_attempt(
        provider="mimo", model="mimo-test", request=_request(), context=_unique_context(),
        estimated_cost_cny=0, retry_count=0, recorded_transport=False,
    )
    controller.complete_attempt(
        attempt, status="SUCCEEDED", response=_zero_cost_response("mimo", latency_ms=7), latency_ms=7
    )

    connection = sqlite3.connect(ledger)
    legacy = connection.execute(
        "SELECT call_id, ledger_id, actual_cost_cny, trace_id FROM paid_test_calls WHERE call_id = 'legacy-call'"
    ).fetchone()
    schema_version = connection.execute(
        "SELECT value FROM paid_test_ledger_meta WHERE key = 'schema_version'"
    ).fetchone()[0]
    connection.close()
    assert legacy == ("legacy-call", "legacy-call", 0.05, None)
    assert schema_version == "3"
    assert controller.summary()["paid_ledger_required_field_completeness"] == 100.0
