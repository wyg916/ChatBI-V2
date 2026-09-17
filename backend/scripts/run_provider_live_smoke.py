from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings
from app.query.contracts import LinkedObject, QueryContext, SecurityPolicy
from app.query.nl2sql import OpenAICompatibleProvider, PROVIDER_DEFINITIONS, _provider_values
from app.query.sql_guard import SqlGuard


ROOT = BACKEND_ROOT.parent


def _context() -> QueryContext:
    columns = [
        LinkedObject(
            object_type="COLUMN",
            object_id=f"orders.{name}",
            name=name,
            label=label,
            qualified_name=f"orders.{name}",
            score=1.0,
        )
        for name, label in (("order_id", "订单编号"), ("revenue", "收入"))
    ]
    return QueryContext(
        workspace_id="provider-smoke",
        workspace_name="Provider Smoke",
        datasource_id="provider-smoke-postgresql",
        datasource_name="Provider Smoke PostgreSQL",
        dialect="postgresql",
        schema_name="demo_business",
        semantic_model_id="provider-smoke-model",
        semantic_model_name="Provider Smoke Model",
        semantic_model_version=1,
        entities=[{"name": "orders", "table": "orders", "label": "订单"}],
        candidate_tables=[LinkedObject(
            object_type="TABLE",
            object_id="orders",
            name="orders",
            label="订单",
            qualified_name="demo_business.orders",
            score=1.0,
        )],
        candidate_columns=columns,
        metrics=[{"name": "order_count", "label": "订单量", "expression": "COUNT(orders.order_id)"}],
        dimensions=[],
        relationships=[],
        business_terms=[],
        now=datetime.now(timezone.utc),
        row_limit=100,
        token_budget=2000,
        estimated_tokens=400,
        security_policy=SecurityPolicy(
            allowed_schemas=["demo_business"],
            allowed_tables=["orders"],
            allowed_columns={"orders": ["order_id", "revenue"]},
            row_limit=100,
        ),
    )


def run() -> dict:
    settings = Settings(_env_file=ROOT / ".env")
    context = _context()
    results = []
    for definition in PROVIDER_DEFINITIONS[:3]:
        base_url, api_key, model_name = _provider_values(settings, definition)
        item = {
            "provider": definition.provider_id,
            "model": model_name,
            "configured": bool(base_url and api_key and model_name),
            "provider_discovery": False,
            "authentication": False,
            "chat_completion": False,
            "sqlplan_compatible": False,
            "sql_guard_allowed": False,
        }
        if not item["configured"]:
            item["error_type"] = "NOT_CONFIGURED"
            results.append(item)
            continue
        headers = {definition.auth_header: f"{definition.auth_prefix}{api_key}"}
        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(f"{base_url}/models", headers=headers)
                item["models_http"] = response.status_code
                response.raise_for_status()
                models = response.json().get("data", [])
                item["provider_discovery"] = any(model.get("id") == model_name for model in models)
                item["authentication"] = True

            provider = OpenAICompatibleProvider(
                provider_name=definition.provider_id,
                display_name=definition.display_name,
                base_url=base_url,
                api_key=api_key,
                model_name=model_name,
                auth_header=definition.auth_header,
                auth_prefix=definition.auth_prefix,
                request_options=definition.request_options,
                timeout_seconds=60,
            )
            plan = provider.generate(question="统计订单数量", context=context)
            item["chat_completion"] = True
            item["sqlplan_compatible"] = plan.provider == definition.provider_id
            guard = SqlGuard().validate(
                plan.generated_sql,
                dialect=context.dialect,
                policy=context.security_policy,
            )
            item["sql_guard_allowed"] = guard.allowed
        except Exception as exc:  # evidence intentionally records type only
            item["error_type"] = type(exc).__name__
        results.append(item)
    passed = all(
        item["configured"]
        and item["provider_discovery"]
        and item["authentication"]
        and item["chat_completion"]
        and item["sqlplan_compatible"]
        and item["sql_guard_allowed"]
        for item in results
    )
    return {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": "day5_provider_discovery_auth_chat_sqlplan",
        "active_release_provider": settings.model_provider,
        "secrets_recorded": False,
        "results": results,
        "result": "PASS" if passed else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run()
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
