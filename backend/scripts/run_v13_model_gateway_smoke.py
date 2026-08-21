from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from app.core.config import get_settings
from app.model_gateway import BudgetMode, ModelCapability, ModelGateway, ModelRequest, RequestContext


def main() -> int:
    settings = get_settings()
    results = []
    for provider in ("mimo", "deepseek", "kimi"):
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
                    request_id=f"SMOKE-{provider}-{uuid4()}",
                    trace_id=f"TRACE-SMOKE-{provider}-{uuid4()}",
                    question="provider connectivity probe",
                    budget_mode=BudgetMode.QUALITY,
                ),
            )
            results.append({
                "provider": provider,
                "status": "PASS" if response.content.strip() else "FAIL",
                "resolved_provider": response.resolved_provider,
                "resolved_model": response.resolved_model,
                "usage": response.usage.model_dump(mode="json"),
                "cost_cny": response.cost_cny,
                "latency_ms": response.latency_ms,
                "fallback_used": response.fallback_used,
                "retry_count": response.retry_count,
                "reasoning_observed": response.reasoning_observed,
            })
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
        "test": "V1.3 canonical ModelGateway live non-stream smoke",
        "secrets_exposed": False,
        "authorization_headers_exposed": False,
        "results": results,
        "status": "PASS" if all(item["status"] == "PASS" for item in results) else "FAIL",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
