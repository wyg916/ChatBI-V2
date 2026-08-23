from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.model_gateway.test_cost_control import (  # noqa: E402
    TestCostControlError,
    TestCostController,
    TestExecutionLevel,
)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _base_environment(args: argparse.Namespace) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update({
        "CHATBI_TEST_COST_CONTROL": "YES",
        "CHATBI_TEST_EXECUTION_LEVEL": args.level,
    })
    optional = {
        "CHATBI_PAID_GATE_AUTHORIZED": getattr(args, "paid_gate_authorized", None),
        "CHATBI_TEST_SHA": getattr(args, "sha", None),
        "CHATBI_TEST_FINAL_SHA": getattr(args, "final_sha", None),
        "CHATBI_TEST_RUN_ID": getattr(args, "test_run_id", None),
        "CHATBI_TEST_CASE_ID": getattr(args, "case_id", None),
        "CHATBI_TEST_GATE": getattr(args, "gate", None),
        "CHATBI_TEST_AFFECTED_PATH": getattr(args, "affected_path", None),
        "CHATBI_TEST_ALLOWED_PROVIDERS": getattr(args, "providers", None),
        "CHATBI_TEST_BUDGET_CLASS": getattr(args, "budget_class", None),
        "CHATBI_TEST_BUDGET_CNY": str(getattr(args, "budget_cny", "") or ""),
        "CHATBI_TEST_COST_LEDGER_PATH": str(getattr(args, "ledger", "") or ""),
        "CHATBI_FINAL_CERTIFICATION": getattr(args, "final_certification", None),
        "CHATBI_PAID_TEST_CACHE_BYPASS": getattr(args, "cache_bypass", None),
        "CHATBI_LEVEL0_RECEIPT": str(getattr(args, "level0_receipt", "") or ""),
    }
    environment.update({key: value for key, value in optional.items() if value not in (None, "")})
    return environment


def _strategy_fields(level: TestExecutionLevel) -> dict[str, Any]:
    if level == TestExecutionLevel.LEVEL0:
        return {
            "test_strategy": "LEVEL0_DETERMINISTIC_LOCAL_RECORDED",
            "load_test_provider_mode": "DETERMINISTIC_CONTROLLED_OR_RECORDED_PROVIDER_RESPONSE",
            "control_matrix_paid_provider_calls": 0,
            "data100_paid_provider_calls": 0,
            "complex5_paid_provider_calls": 0,
            "multimodal10_paid_provider_calls": 0,
            "paid_test_cache_bypass": False,
        }
    if level == TestExecutionLevel.LEVEL1:
        return {
            "test_strategy": "LEVEL1_TARGETED_REAL_PROVIDER_SMOKE",
            "load_test_provider_mode": "NOT_APPLICABLE",
            "paid_test_cache_bypass": False,
        }
    return {
        "test_strategy": "LEVEL2_FINAL_PAID_CERTIFICATION_ONCE_PER_FINAL_SHA",
        "load_test_provider_mode": "SEPARATE_FROM_20X15_DETERMINISTIC_LOAD",
        "paid_test_cache_bypass": True,
    }


def command_plan(args: argparse.Namespace) -> int:
    tested_sha = args.sha.lower() if args.sha else None
    if tested_sha is not None and not re.fullmatch(r"[0-9a-f]{40}", tested_sha):
        raise TestCostControlError("CHATBI_TEST_SHA_MUST_BE_FULL_SHA")
    controller = TestCostController(environ=_base_environment(args))
    configuration = controller.validate_configuration()
    estimated = max(0.0, float(args.estimated_cost_cny))
    if configuration.get("paid_calls_allowed") and estimated > float(configuration["run_budget_cny"]):
        raise TestCostControlError(
            f"TEST_BUDGET_EXCEEDED REQUIRED_ESTIMATED_COST={estimated:.8f} "
            f"REASON=run_hard_cap_{float(configuration['run_budget_cny']):.2f}"
        )
    payload = {
        "schema_version": "chatbi-v1.3-phase5-test-execution-plan-v1",
        "tested_sha": tested_sha,
        **_strategy_fields(controller.level),
        **configuration,
        "estimated_cost_cny": estimated,
        "free_test_calls": 0,
        "paid_test_calls": 0,
        "paid_test_cost_cny": 0.0,
        "mimo_test_cost_cny": 0.0,
        "deepseek_test_cost_cny": 0.0,
        "kimi_test_cost_cny": 0.0,
        "duplicate_paid_tests_avoided": "ENFORCED_BY_LEVEL_AND_FAILED_CASE_SCOPE",
        "budget_exceeded": False,
        "test_cost_control_gate": "PASS",
    }
    if args.output:
        _atomic_json(args.output, payload)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def _parse_gates(values: list[str]) -> dict[str, str]:
    gates: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise TestCostControlError(f"INVALID_GATE_ASSIGNMENT:{value}")
        name, status = value.split("=", 1)
        gates[name.strip()] = status.strip().upper()
    return gates


def command_certify_level0(args: argparse.Namespace) -> int:
    if not re.fullmatch(r"[0-9a-f]{40}", args.sha.lower()):
        raise TestCostControlError("CHATBI_TEST_SHA_MUST_BE_FULL_SHA")
    environment = {
        "CHATBI_TEST_COST_CONTROL": "YES",
        "CHATBI_TEST_EXECUTION_LEVEL": "LEVEL0",
    }
    controller = TestCostController(environ=environment)
    gates = _parse_gates(args.gate)
    missing = [name for name in controller.policy["required_level0_gates"] if gates.get(name) != "PASS"]
    payload = {
        "schema_version": "chatbi-v1.3-phase5-level0-receipt-v1",
        "tested_sha": args.sha.lower(),
        "level0_all_pass": not missing,
        "gates": gates,
        "missing_or_failed_required_gates": missing,
        "paid_test_calls": 0,
        "paid_test_cost_cny": 0.0,
        "final_gate_thresholds_unchanged": True,
    }
    _atomic_json(args.output, payload)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if not missing else 2


def command_summary(args: argparse.Namespace) -> int:
    controller = TestCostController(environ=_base_environment(args))
    summary = {
        "schema_version": "chatbi-v1.3-phase5-paid-test-cost-summary-v1",
        **_strategy_fields(controller.level),
        **controller.summary(),
        "final_gate_thresholds_unchanged": True,
        "test_cost_control_gate": "PASS",
    }
    if args.output:
        _atomic_json(args.output, summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _paid_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sha")
    parser.add_argument("--final-sha")
    parser.add_argument("--test-run-id")
    parser.add_argument("--case-id")
    parser.add_argument("--gate")
    parser.add_argument("--affected-path")
    parser.add_argument("--providers")
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--budget-class")
    parser.add_argument("--budget-cny", type=float)
    parser.add_argument("--paid-gate-authorized", default="NO")
    parser.add_argument("--final-certification", default="NO")
    parser.add_argument("--cache-bypass", default="NO")
    parser.add_argument("--level0-receipt", type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan and certify cost-controlled ChatBI Phase5 tests")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--level", choices=[level.value for level in TestExecutionLevel], required=True)
    plan.add_argument("--estimated-cost-cny", type=float, default=0.0)
    plan.add_argument("--output", type=Path)
    _paid_arguments(plan)
    plan.set_defaults(handler=command_plan)

    certify = subparsers.add_parser("certify-level0")
    certify.add_argument("--sha", required=True)
    certify.add_argument("--gate", action="append", default=[])
    certify.add_argument("--output", type=Path, required=True)
    certify.set_defaults(handler=command_certify_level0)

    summary = subparsers.add_parser("summary")
    summary.add_argument("--level", choices=[level.value for level in TestExecutionLevel], required=True)
    summary.add_argument("--output", type=Path)
    _paid_arguments(summary)
    summary.set_defaults(handler=command_summary)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.handler(args))
    except TestCostControlError as exc:
        payload = {
            "schema_version": "chatbi-v1.3-phase5-test-cost-control-error-v1",
            "status": "FAIL",
            "error": str(exc),
            "budget_exceeded": str(exc).startswith("TEST_BUDGET_EXCEEDED"),
            "test_cost_control_gate": "FAIL",
        }
        output = getattr(args, "output", None)
        if output:
            _atomic_json(output, payload)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
