from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.certification.runtime_binding import run_exact_sha_runtime_preflight, seal_runtime_preflight_receipt
from app.core.config import get_settings
from app.model_gateway.configuration import configured_providers
from app.model_gateway.test_cost_control import TestCostController, TestExecutionLevel
from app.query.contracts import LinkedObject, QueryContext, SecurityPolicy
from app.query.nl2sql import OpenAICompatibleProvider
from app.query.sql_guard import SqlGuard


def _context(provider: str) -> QueryContext:
    case_id = f"FINAL-NL2SQL-{provider.upper()}"
    return QueryContext(
        request_id=case_id,
        trace_id=f"TRACE-{case_id}",
        route="DATA_QUERY",
        workspace_id="FINAL-NL2SQL-SYNTHETIC",
        workspace_name="Final NL2SQL synthetic workspace",
        datasource_id="FINAL-NL2SQL-DATASOURCE",
        datasource_name="Final NL2SQL synthetic datasource",
        dialect="postgresql",
        schema_name="demo_business",
        semantic_model_id="FINAL-NL2SQL-SEMANTIC",
        semantic_model_name="Final NL2SQL semantic model",
        semantic_model_version=1,
        entities=[{"name": "order", "table": "orders"}],
        candidate_tables=[
            LinkedObject(
                object_type="TABLE",
                object_id="orders",
                name="orders",
                label="订单",
                qualified_name="demo_business.orders",
                score=1.0,
                evidence=["owner-authorized synthetic final NL2SQL smoke"],
            )
        ],
        candidate_columns=[
            LinkedObject(
                object_type="COLUMN",
                object_id=f"orders.{name}",
                name=name,
                label=label,
                qualified_name=f"demo_business.orders.{name}",
                score=1.0,
                evidence=["owner-authorized synthetic final NL2SQL smoke"],
            )
            for name, label in (("region", "地区"), ("revenue", "收入"), ("status", "状态"))
        ],
        metrics=[{"name": "revenue", "expression": "SUM(orders.revenue)"}],
        dimensions=[{"name": "region", "column": "orders.region"}],
        relationships=[],
        business_terms=[{"term": "已支付", "definition": "orders.status = 'PAID'"}],
        now=datetime.now(timezone.utc),
        row_limit=100,
        token_budget=8_000,
        estimated_tokens=600,
        security_policy=SecurityPolicy(
            allowed_schemas=["demo_business"],
            allowed_tables=["orders"],
            allowed_columns={"orders": ["region", "revenue", "status"]},
            row_limit=100,
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("mimo", "deepseek"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    controller = TestCostController()
    configuration = controller.validate_configuration()
    if controller.level != TestExecutionLevel.FINAL:
        raise SystemExit("FINAL_TEST_LEVEL_REQUIRED")
    preflight = seal_runtime_preflight_receipt(
        run_exact_sha_runtime_preflight(
            repo_root=Path(__file__).resolve().parents[2],
            expected_git_sha=str(configuration["tested_sha"]),
        ),
        config_hash=controller.config_hash,
    )
    resolved = configured_providers(get_settings()).get(args.provider)
    if resolved is None:
        raise SystemExit(f"FINAL_NL2SQL_PROVIDER_NOT_CONFIGURED:{args.provider}")
    provider = OpenAICompatibleProvider(
        base_url=resolved.base_url,
        api_key=resolved.api_key,
        model_name=resolved.model_name,
        provider_name=resolved.provider_id,
        display_name=resolved.display_name,
        auth_header=resolved.auth_header,
        auth_prefix=resolved.auth_prefix,
        max_tokens_field=resolved.max_tokens_field,
        request_options=resolved.request_options,
    )
    context = _context(args.provider)
    plan = provider.generate(
        question="按地区统计已支付订单收入，按收入降序，仅使用授权表字段。",
        context=context,
    )
    guard = SqlGuard().validate(
        plan.generated_sql,
        dialect=plan.dialect,
        policy=context.security_policy,
    )
    summary = controller.summary()
    failures: list[str] = []
    if plan.provider != args.provider:
        failures.append("PROVIDER_IDENTITY_MISMATCH")
    if not guard.allowed:
        failures.append("SQL_GUARD_REJECTED")
    if not set(plan.selected_tables) <= {"orders", "demo_business.orders"}:
        failures.append("UNAUTHORIZED_TABLE_IN_PLAN")
    records = [
        row for row in summary.get("ledger_records") or []
        if row.get("case_id") == context.request_id
    ]
    if not records or any(row.get("provider") != args.provider for row in records):
        failures.append("LEDGER_PROVIDER_COVERAGE_INVALID")
    payload = {
        "schema_version": "chatbi-v1.3-final-nl2sql-provider-v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "tested_sha": configuration["tested_sha"],
        "provider": args.provider,
        "model": resolved.model_name,
        "case_id": context.request_id,
        "normalization": "CANONICAL_NL2SQL_RESPONSE_NORMALIZATION",
        "sql_guard": "PASS" if guard.allowed else "FAIL",
        "selected_tables": plan.selected_tables,
        "selected_columns": plan.selected_columns,
        "generated_sql_sha256": __import__("hashlib").sha256(plan.generated_sql.encode()).hexdigest(),
        "ledger_records": records,
        "exact_sha_runtime_preflight": preflight,
        "failures": failures,
        "direct_provider_bypass": 0,
        "secrets_exposed": False,
        "status": "PASS" if not failures else "FAIL",
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if resolved.api_key and resolved.api_key in serialized:
        raise SystemExit("SECRET_LEAK_IN_EVIDENCE")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized, encoding="utf-8")
    print(json.dumps({
        "status": payload["status"],
        "tested_sha": payload["tested_sha"],
        "provider": args.provider,
        "ledger_calls": len(records),
        "failures": failures,
    }, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
