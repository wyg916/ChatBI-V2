from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings
from app.model_gateway import BudgetMode, ModelCapability, ModelGateway, ModelRequest, RequestContext
from app.model_gateway.test_cost_control import TestCostControlError, TestCostController, TestExecutionLevel


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an authorized targeted or final Provider connectivity smoke")
    parser.add_argument("--provider", action="append", choices=("mimo", "deepseek", "kimi"))
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _write_evidence(path: Path, payload: dict[str, object]) -> None:
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


def main() -> int:
    arguments = _arguments()
    controller = TestCostController()
    try:
        configuration = controller.validate_configuration()
    except TestCostControlError as exc:
        raise SystemExit(str(exc)) from exc
    if not configuration.get("paid_calls_allowed"):
        raise SystemExit("REAL_PROVIDER_SMOKE_REQUIRES_LEVEL1_OR_LEVEL2_AUTHORIZATION")
    providers = tuple(arguments.provider or ())
    if controller.level == TestExecutionLevel.LEVEL1 and not providers:
        raise SystemExit("LEVEL1_REQUIRES_EXPLICIT_TARGET_PROVIDER")
    if controller.level == TestExecutionLevel.LEVEL2 and providers:
        raise SystemExit("LEVEL2_FINAL_PROVIDER_SMOKE_MUST_EXECUTE_ALL_THREE_PROVIDERS")
    providers = providers or ("mimo", "deepseek", "kimi")
    settings = get_settings()
    results = []
    cost_control_failure: str | None = None
    for provider in providers:
        gateway = ModelGateway(settings)
        try:
            response = gateway.execute(
                ModelRequest(
                    capability=ModelCapability.GENERAL,
                    messages=(
                        {"role": "system", "content": "You are a provider connectivity probe."},
                        {"role": "user", "content": "Reply with CHATBI_SMOKE_OK only."},
                    ),
                    requested_alias=provider,
                    budget_mode=BudgetMode.QUALITY,
                    max_output_tokens=32,
                ),
                RequestContext(
                    request_id=f"SMOKE-{provider}",
                    trace_id=f"TRACE-SMOKE-{provider}-{uuid4()}",
                    question="provider connectivity probe",
                    budget_mode=BudgetMode.QUALITY,
                ),
            )
            expected_model = gateway.providers[provider].model_name
            exact_provider = response.resolved_provider == provider
            exact_model = response.resolved_model == expected_model
            no_fallback = response.fallback_used is False and response.fallback_count == 0
            exact_probe = response.content.strip() == "CHATBI_SMOKE_OK"
            results.append({
                "provider": provider,
                "status": "PASS" if exact_provider and exact_model and no_fallback and exact_probe else "FAIL",
                "expected_model": expected_model,
                "resolved_provider": response.resolved_provider,
                "resolved_model": response.resolved_model,
                "exact_provider": exact_provider,
                "exact_model": exact_model,
                "exact_probe": exact_probe,
                "usage": response.usage.model_dump(mode="json"),
                "cost_cny": response.cost_cny,
                "latency_ms": response.latency_ms,
                "fallback_used": response.fallback_used,
                "fallback_count": response.fallback_count,
                "retry_count": response.retry_count,
                "reasoning_observed": response.reasoning_observed,
            })
        except TestCostControlError as exc:
            results.append({
                "provider": provider,
                "status": "FAIL",
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            cost_control_failure = str(exc)
            break
        except Exception as exc:  # Deliberately reports the real provider failure class/status only.
            results.append({
                "provider": provider,
                "status": "FAIL",
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
    payload = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "tested_sha": configuration["tested_sha"],
        "test_execution_level": controller.level.value,
        "test": "V1.3 canonical ModelGateway live non-stream smoke",
        "secrets_exposed": False,
        "authorization_headers_exposed": False,
        "cost_control_failure": cost_control_failure,
        "backend_cost_control_identity": controller.runtime_identity(),
        "paid_test_summary": controller.summary(),
        "results": results,
        "status": "PASS" if all(item["status"] == "PASS" for item in results) else "FAIL",
    }
    _write_evidence(arguments.output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
