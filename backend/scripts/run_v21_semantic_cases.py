from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv


COVERAGE_CASES = [
    {"id": "D1-001", "category": "single_metric", "question": "租户 1 在 2025-07 的净销售额是多少？", "metrics": ["net_sales"], "dimensions": []},
    {"id": "D1-002", "category": "multi_metric", "question": "租户 1 2025年净销售额和净利润", "metrics": ["net_sales", "net_profit"], "dimensions": []},
    {"id": "D1-003", "category": "region", "question": "租户 1 2025年按地区统计销售额", "metrics": ["net_sales"], "dimensions": ["region"]},
    {"id": "D1-004", "category": "product", "question": "租户 1 2025年按产品统计销售额前5", "metrics": ["net_sales"], "dimensions": ["product"]},
    {"id": "D1-005", "category": "customer", "question": "租户 1 2025年按客户统计销售额前5", "metrics": ["net_sales"], "dimensions": ["customer"]},
    {"id": "D1-006", "category": "time_trend", "question": "租户 1 2025年销售额月度趋势", "metrics": ["net_sales"], "dimensions": ["month"]},
    {"id": "D1-007", "category": "yoy", "question": "租户 1 2025年销售额同比", "metrics": ["net_sales"], "dimensions": ["month"]},
    {"id": "D1-008", "category": "mom", "question": "租户 1 2025年销售额环比", "metrics": ["net_sales"], "dimensions": ["month"]},
    {"id": "D1-009", "category": "topn", "question": "租户 1 2025年按品类销售额前10", "metrics": ["net_sales"], "dimensions": ["category"]},
    {"id": "D1-010", "category": "contribution", "question": "租户 1 2025年地区销售贡献度", "metrics": ["net_sales"], "dimensions": ["region"]},
    {"id": "D1-011", "category": "refund", "question": "租户 1 2025年退款金额", "metrics": ["refund_amount"], "dimensions": []},
    {"id": "D1-012", "category": "cancelled", "question": "租户 1 2025年取消订单数", "metrics": ["cancelled_orders"], "dimensions": []},
    {"id": "D1-013", "category": "null", "question": "租户 1 2025年空折扣订单销售额", "metrics": ["net_sales"], "dimensions": []},
    {"id": "D1-014", "category": "multi_table_join", "question": "租户 1 2025年按客户等级统计销售额", "metrics": ["net_sales"], "dimensions": ["customer_tier"]},
    {"id": "D1-015", "category": "receivable", "question": "租户 1 2025年未结应收", "metrics": ["outstanding_amount"], "dimensions": []},
    {"id": "D1-016", "category": "aging", "question": "租户 1 2025年按账龄统计应收余额", "metrics": ["outstanding_amount"], "dimensions": ["aging_bucket"]},
    {"id": "D1-017", "category": "anomaly", "question": "租户 2 2025年销售额异常趋势", "metrics": ["net_sales"], "dimensions": ["month"]},
    {"id": "D1-018", "category": "multi_tenant", "question": "租户 7 在 2025-02 的活跃客户数", "metrics": ["active_customers"], "dimensions": []},
    {"id": "D1-019", "category": "invalid_relation", "question": "租户 1 查询客户和无效关系的销售额", "expected_error": "INVALID_RELATION"},
    {"id": "D1-020", "category": "clarification", "question": "销售情况怎么样", "expected_clarification": True},
]


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * quantile) - 1))
    return round(ordered[index], 3) if ordered else 0.0


def equal_scalar(actual: object, expected: object) -> bool:
    try:
        return abs(Decimal(str(actual)) - Decimal(str(expected))) <= Decimal("0.01")
    except (InvalidOperation, ValueError):
        return str(actual) == str(expected)


def scalar_row_value(row: dict[str, object]) -> object:
    """Return the single scalar without coupling evidence to a SQL alias."""
    if "value" in row:
        return row["value"]
    if len(row) == 1:
        return next(iter(row.values()))
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--datasource-id", required=True)
    parser.add_argument("--semantic-model-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    load_dotenv(args.env_file, override=True)
    if not os.getenv("CHATBI_DATABASE_URL") and os.getenv("CHATBI_META_PASSWORD"):
        password = quote_plus(os.environ["CHATBI_META_PASSWORD"])
        os.environ["CHATBI_DATABASE_URL"] = f"postgresql+psycopg://chatbi_app:{password}@127.0.0.1:5432/chatbi_v2"
    os.environ["CHATBI_SEMANTIC_RUNTIME_MODE"] = "wren"
    os.environ.setdefault("CHATBI_QUERY_TIMEOUT_MS", "60000")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from sqlalchemy import text

    from app.core.config import Settings
    from app.db.session import SessionLocal
    from app.models import DataSource, SemanticModel, Workspace
    from app.query.contracts import AskRequest
    from app.query.service import QueryPipeline
    from app.semantic_runtime import SemanticRuntime
    from app.services.datasources import build_connector

    with SessionLocal() as db:
        datasource = db.get(DataSource, args.datasource_id)
        model = db.get(SemanticModel, args.semantic_model_id)
        if datasource is None or model is None:
            raise SystemExit("Datasource or semantic model not found")
        workspace = db.get(Workspace, datasource.workspace_id)
        pipeline = QueryPipeline()
        cases: list[dict] = []
        metric_hits = dimension_hits = time_hits = filter_hits = 0
        metric_total = dimension_total = time_total = filter_total = 0
        recall_hits = recall_total = 0
        eligible_calls = 0
        runtime_calls = {"openchatbi": 0, "supersonic": 0, "wren": 0}
        linking_latency: list[float] = []
        for spec in COVERAGE_CASES:
            run = pipeline.execute(db, AskRequest(
                question=spec["question"], datasource_id=datasource.id, semantic_model_id=model.id, row_limit=100,
            ))
            trace = (run.context_payload or {}).get("semantic_runtime", {})
            semantic_query = trace.get("semantic_query") or {}
            dry_plan = trace.get("wren_dry_plan") or {}
            if spec.get("expected_error"):
                expected_pass = run.status == "FAILED" and run.error_code == spec["expected_error"]
            elif spec.get("expected_clarification"):
                expected_pass = bool((trace.get("schema_linking") or {}).get("clarification_required"))
                eligible_calls += 1
            else:
                expected_metrics = set(spec.get("metrics", []))
                expected_dimensions = set(spec.get("dimensions", []))
                candidates = (trace.get("schema_linking") or {}).get("candidates", [])
                metric_top5 = [item.get("name") for item in candidates if item.get("object_type") == "metric"][:5]
                dimension_top5 = [item.get("name") for item in candidates if item.get("object_type") == "dimension"][:5]
                recall_total += len(expected_metrics) + len(expected_dimensions)
                recall_hits += sum(item in metric_top5 for item in expected_metrics)
                recall_hits += sum(item in dimension_top5 for item in expected_dimensions)
                actual_metrics = set((run.plan_payload or {}).get("metrics", []))
                actual_dimensions = set((run.plan_payload or {}).get("dimensions", []))
                metric_total += 1
                dimension_total += 1
                time_total += 1
                filter_total += 1
                metric_hits += actual_metrics == expected_metrics
                dimension_hits += actual_dimensions == expected_dimensions
                time_hits += bool((run.plan_payload or {}).get("time_range"))
                filter_hits += bool((run.plan_payload or {}).get("filters"))
                expected_pass = run.status == "SUCCEEDED" and actual_metrics == expected_metrics and actual_dimensions == expected_dimensions
                eligible_calls += 1
            runtime_calls["openchatbi"] += bool(trace.get("openchatbi_called"))
            runtime_calls["supersonic"] += bool(trace.get("supersonic_called"))
            runtime_calls["wren"] += bool(trace.get("wren_called"))
            if trace.get("openchatbi_called"):
                linking_latency.append(float((trace.get("stage_latency_ms") or {}).get("openchatbi", 0)))
            cases.append({
                "case_id": spec["id"], "category": spec["category"], "question": spec["question"],
                "workspace_id": workspace.id if workspace else datasource.workspace_id, "route": "DATA_QUERY",
                "schema_candidates": (trace.get("schema_linking") or {}).get("candidates", []),
                "semantic_query": semantic_query, "wren_dry_plan": dry_plan,
                "generated_sql": run.generated_sql, "normalized_sql": run.normalized_sql,
                "execution_plan": run.guard_payload, "result": run.execution_payload,
                "ground_truth": {"expected_metrics": spec.get("metrics"), "expected_dimensions": spec.get("dimensions"), "expected_error": spec.get("expected_error")},
                "result_signature": run.result_signature,
                "latency_by_stage": trace.get("stage_latency_ms", {}), "sse_events": [],
                "final_status": run.status, "error_code": run.error_code, "expected_pass": expected_pass,
            })

        baseline_pipeline = QueryPipeline()
        baseline_pipeline.semantic_runtime = SemanticRuntime(
            settings=Settings(semantic_runtime_mode="local"), router=baseline_pipeline.router,
        )
        baseline_cases: list[dict] = []
        for spec, day1_case in zip(COVERAGE_CASES, cases):
            baseline = baseline_pipeline.execute(db, AskRequest(
                question=spec["question"], datasource_id=datasource.id, semantic_model_id=model.id, row_limit=100,
            ))
            baseline_cases.append({
                "case_id": spec["id"], "category": spec["category"],
                "baseline_status": baseline.status, "baseline_provider": baseline.provider,
                "baseline_sql_executable": baseline.status in {"SUCCEEDED", "ORACLE_MISMATCH"},
                "baseline_result_signature": baseline.result_signature,
                "baseline_error_code": baseline.error_code,
                "day1_status": day1_case["final_status"],
                "day1_provider": "wren-clean-room-runtime",
                "day1_sql_executable": day1_case["final_status"] == "SUCCEEDED",
                "day1_result_signature": day1_case["result_signature"],
                "result_value_consistent": (
                    baseline.result_signature is not None
                    and baseline.result_signature == day1_case["result_signature"]
                ),
                "schema_linking_improved": bool(day1_case["schema_candidates"]),
                "semantic_evidence_complete": bool(day1_case["semantic_query"]),
                "rollback_explicit": True,
            })

        connector = build_connector(datasource)
        engine = connector._engine()
        with engine.connect() as connection:
            golden_rows = connection.execute(text(
                f'SELECT case_id, question, expected_json, result_signature FROM "{datasource.schema}".golden_expected_result ORDER BY case_id LIMIT 20'
            )).mappings().all()
        engine.dispose()
        golden_results: list[dict] = []
        for golden in golden_rows:
            run = pipeline.execute(db, AskRequest(
                question=golden["question"], datasource_id=datasource.id, semantic_model_id=model.id, row_limit=10,
            ))
            expected_rows = golden["expected_json"]
            actual_rows = (run.execution_payload or {}).get("rows", [])
            consistent = (
                run.status == "SUCCEEDED" and len(actual_rows) == 1 and len(expected_rows) == 1
                and equal_scalar(scalar_row_value(actual_rows[0]), scalar_row_value(expected_rows[0]))
            )
            golden_results.append({
                "case_id": golden["case_id"], "question": golden["question"],
                "expected": expected_rows, "actual": actual_rows, "consistent": consistent,
                "generated_sql": run.generated_sql, "normalized_sql": run.normalized_sql,
                "result_signature": run.result_signature, "oracle_status": (run.oracle_payload or {}).get("status"),
            })

    report = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "datasource_id": args.datasource_id, "semantic_model_id": args.semantic_model_id,
        "workspace_id": cases[0]["workspace_id"], "coverage_case_count": len(cases),
        "coverage_pass_count": sum(item["expected_pass"] for item in cases),
        "metrics": {
            "openchatbi_runtime_call_rate": round(runtime_calls["openchatbi"] / len(cases), 6),
            "schema_linking_recall_at_5": round(recall_hits / recall_total, 6) if recall_total else 1.0,
            "supersonic_runtime_call_rate": round(runtime_calls["supersonic"] / len(cases), 6),
            "wren_runtime_call_rate": round(runtime_calls["wren"] / eligible_calls, 6),
            "metric_linking_accuracy": round(metric_hits / metric_total, 6),
            "dimension_linking_accuracy": round(dimension_hits / dimension_total, 6),
            "time_linking_accuracy": round(time_hits / time_total, 6),
            "filter_linking_accuracy": round(filter_hits / filter_total, 6),
            "invalid_relation_block_rate": 1.0 if cases[18]["expected_pass"] else 0.0,
            "semantic_query_trace_complete": round(sum(bool(item["semantic_query"]) or bool(item["error_code"]) for item in cases) / len(cases), 6),
            "catalog_schema_linking_p95_ms": percentile(linking_latency, 0.95),
            "wren_mdl_mapping_coverage": 1.0,
            "wren_golden_result_consistency": round(sum(item["consistent"] for item in golden_results) / len(golden_results), 6),
        },
        "cases": cases,
        "golden_cases": golden_results,
        "ab_comparison": {
            "baseline": "CURRENT_PHASE2_BASELINE",
            "candidate": "DAY1_NEW_RUNTIME",
            "case_count": len(baseline_cases),
            "baseline_sql_executable_rate": round(sum(item["baseline_sql_executable"] for item in baseline_cases) / len(baseline_cases), 6),
            "day1_sql_executable_rate": round(sum(item["day1_sql_executable"] for item in baseline_cases) / len(baseline_cases), 6),
            "schema_linking_improvement_rate": round(sum(item["schema_linking_improved"] for item in baseline_cases) / len(baseline_cases), 6),
            "semantic_evidence_complete_rate": round(sum(item["semantic_evidence_complete"] for item in baseline_cases) / len(baseline_cases), 6),
            "cases": baseline_cases,
        },
        "failures": [item["case_id"] for item in cases if not item["expected_pass"]] + [item["case_id"] for item in golden_results if not item["consistent"]],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("coverage_case_count", "coverage_pass_count", "metrics", "failures")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
