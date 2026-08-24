from __future__ import annotations

import json
from pathlib import Path

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


def test_level1_requires_explicit_authorization_and_scope(tmp_path: Path) -> None:
    environment = _level1_environment(tmp_path, CHATBI_PAID_GATE_AUTHORIZED="NO")
    controller = CostController(environ=environment)
    with pytest.raises(CostControlError, match="PAID_GATE_AUTHORIZED_REQUIRED"):
        controller.validate_configuration()

    environment = _level1_environment(tmp_path, CHATBI_TEST_AFFECTED_PATH="database")
    controller = CostController(environ=environment)
    with pytest.raises(CostControlError, match="PAID_TEST_AFFECTED_PATH_NOT_ALLOWED"):
        controller.validate_configuration()

    environment = _level1_environment(tmp_path, CHATBI_TEST_ALLOWED_PROVIDERS="")
    controller = CostController(environ=environment)
    with pytest.raises(CostControlError, match="CHATBI_TEST_ALLOWED_PROVIDERS"):
        controller.validate_configuration()

    environment = _level1_environment(tmp_path, CHATBI_TEST_BUDGET_CLASS="final_certification")
    with pytest.raises(CostControlError, match="TEST_BUDGET_CLASS_NOT_ALLOWED_FOR_LEVEL"):
        CostController(environ=environment).validate_configuration()

    environment = _level1_environment(tmp_path, CHATBI_BACKEND_SHA="b" * 40)
    with pytest.raises(CostControlError, match="BACKEND_SHA_MUST_MATCH_TEST_SHA"):
        CostController(environ=environment).validate_configuration()

    environment = _level1_environment(tmp_path, CHATBI_TEST_NECESSITY_DECLARATION="NO")
    with pytest.raises(CostControlError, match="NECESSITY_DECLARATION_MUST_BE_YES"):
        CostController(environ=environment).validate_configuration()


def test_level1_reserves_and_records_complete_sanitized_cost_ledger(tmp_path: Path) -> None:
    controller = CostController(environ=_level1_environment(tmp_path))
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


def test_served_backend_exposes_only_cost_control_runtime_identity(
    client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _level1_environment(tmp_path)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

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
    controller = CostController(environ=_level1_environment(tmp_path, CHATBI_TEST_BUDGET_CNY="0.50"))
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
    controller = CostController(environ=environment)
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
    controller = CostController(environ=_level1_environment(tmp_path))
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
        CostController(environ=environment).validate_configuration()


def test_level1_records_actual_cost_then_stops_when_provider_exceeds_estimate(tmp_path: Path) -> None:
    controller = CostController(environ=_level1_environment(tmp_path, CHATBI_TEST_BUDGET_CNY="0.50"))
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
    controller = CostController(environ=_level1_environment(
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
    configuration = CostController(environ=environment).validate_configuration()
    assert configuration["level"] == "LEVEL2"
    assert configuration["run_budget_cny"] == 3.0

    environment["CHATBI_PAID_TEST_CACHE_BYPASS"] = "NO"
    with pytest.raises(CostControlError, match="PAID_TEST_CACHE_BYPASS_REQUIRED"):
        CostController(environ=environment).validate_configuration()


def test_level2_is_registered_only_once_per_final_sha(tmp_path: Path) -> None:
    first = CostController(environ=_level2_environment(tmp_path, run_id="RUN-FINAL-001"))
    attempt = first.reserve_attempt(
        provider="mimo", model="mimo-test", request=_request(), context=_context(),
        estimated_cost_cny=0.01, retry_count=0, recorded_transport=False,
    )
    assert attempt is not None
    assert first.summary()["level2_runs_per_sha"] == 1

    second = CostController(environ=_level2_environment(
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
