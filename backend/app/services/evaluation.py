from __future__ import annotations

import copy
import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.evaluation import DANGEROUS_SQL_CASES
from app.models import DataSource, EvaluationCaseResult, EvaluationRun, SemanticModel
from app.query.context_builder import ContextBuilder
from app.query.contracts import AskRequest, ExpectedResult
from app.query.service import QueryPipeline
from app.query.sql_guard import SqlGuard
from app.services.datasources import default_workspace


_SERVICE_FILE = Path(__file__).resolve()
_GOLDEN_MANIFEST_CANDIDATES = (
    _SERVICE_FILE.parents[3] / "evaluation" / "golden" / "day4-golden-50.json",
    _SERVICE_FILE.parents[2] / "evaluation" / "golden" / "day4-golden-50.json",
)
GOLDEN_MANIFEST_PATH = next(
    (candidate for candidate in _GOLDEN_MANIFEST_CANDIDATES if candidate.is_file()),
    _GOLDEN_MANIFEST_CANDIDATES[-1],
)
GOLDEN_MANIFEST_SHA256 = "25580af42bc76ebddd3d49e6b9c16f8bfabba8ba485a835c453c29175ee2a64a"
SOURCE_GOLDEN_20_SHA256 = "d40bb690a4208240ecf347abe47e045cd74c8eb89b9162d5d53890ecf24bc282"


def manifest_hash(manifest: dict[str, Any]) -> str:
    value = copy.deepcopy(manifest)
    value["manifest_sha256"] = None
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_golden_manifest() -> dict[str, Any]:
    manifest = json.loads(GOLDEN_MANIFEST_PATH.read_text(encoding="utf-8"))
    if (
        not manifest.get("frozen")
        or len(manifest.get("cases") or []) != 50
        or manifest.get("source_manifest_sha256") != SOURCE_GOLDEN_20_SHA256
        or manifest.get("manifest_sha256") != GOLDEN_MANIFEST_SHA256
        or manifest_hash(manifest) != GOLDEN_MANIFEST_SHA256
    ):
        raise RuntimeError("Golden 50 manifest is not frozen or its SHA-256 is invalid")
    return manifest


def evaluation_overview(db: Session) -> dict:
    comparisons = list(db.scalars(select(EvaluationRun).order_by(EvaluationRun.sort_order, EvaluationRun.completed_at.desc())))
    if not comparisons:
        raise LookupError("No evaluation records are available")
    current = next((run for run in comparisons if run.is_current), comparisons[0])
    previous = next((run for run in comparisons if run.id != current.id), current)
    metrics = [
        {"key": "sql_generation_rate", "label": "SQL 执行成功率", "value": current.sql_generation_rate, "unit": "%", "change": round(current.sql_generation_rate - previous.sql_generation_rate, 1)},
        {"key": "result_accuracy", "label": "结果值准确率", "value": current.result_accuracy, "unit": "%", "change": round(current.result_accuracy - previous.result_accuracy, 1)},
        {"key": "semantic_accuracy", "label": "语义匹配准确率", "value": current.semantic_accuracy, "unit": "%", "change": round(current.semantic_accuracy - previous.semantic_accuracy, 1)},
        {"key": "average_response_seconds", "label": "平均响应时间", "value": current.average_response_seconds, "unit": "s", "change": round(current.average_response_seconds - previous.average_response_seconds, 1)},
    ]
    return {"current": current, "metrics": metrics, "comparisons": comparisons}


def _runtime(db: Session, dialect: str) -> tuple[DataSource, SemanticModel]:
    datasource = db.scalar(select(DataSource).where(DataSource.type == dialect).order_by(DataSource.created_at))
    if datasource is None:
        raise LookupError(f"No {dialect} datasource is configured")
    model = db.scalar(
        select(SemanticModel)
        .where(SemanticModel.datasource_id == datasource.id)
        .order_by((SemanticModel.status == "PUBLISHED").desc(), SemanticModel.created_at.asc(), SemanticModel.id.asc())
    )
    if model is None:
        raise LookupError(f"No {dialect} semantic model is configured")
    return datasource, model


def _semantic_match(case: dict[str, Any], plan: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for key, expected_key in (("metrics", "expected_metrics"), ("dimensions", "expected_dimensions")):
        if plan.get(key, []) != case.get(expected_key, []):
            reasons.append(f"{key} mismatch")
    if not set(case.get("expected_entities", [])).issubset(set(plan.get("selected_entities", []))):
        reasons.append("selected_entities missing expected values")
    actual_filters = {(item["field"], str(item["value"])) for item in plan.get("filters", [])}
    expected_filters = {(item["field"], str(item["value"])) for item in case.get("expected_filters", [])}
    if not expected_filters.issubset(actual_filters):
        reasons.append("filters missing expected values")
    expected_time = case.get("expected_time_range")
    if expected_time:
        actual_time = plan.get("time_range") or {}
        if actual_time.get("start") != expected_time["start"] or actual_time.get("end_exclusive") != expected_time["end_exclusive"]:
            reasons.append("time_range mismatch")
    return not reasons, reasons


def _result_diff(case: dict[str, Any], actual: dict[str, Any], result_ok: bool) -> list[dict[str, Any]]:
    if result_ok:
        return []
    expected_rows = case.get("expected_result") or []
    actual_rows = actual.get("rows") or []
    return [{
        "kind": "RESULT_VALUE",
        "expected_signature": case.get("expected_signature"),
        "actual_signature": actual.get("result_signature"),
        "expected_row_count": len(expected_rows),
        "actual_row_count": len(actual_rows),
        "expected_sample": expected_rows[:3],
        "actual_sample": actual_rows[:3],
    }]


def _error_category(*, execution_ok: bool, result_ok: bool, semantic_ok: bool, error_code: str | None) -> str | None:
    if not execution_ok:
        if error_code and ("GUARD" in error_code or "NOT_ALLOWED" in error_code or "AUTHORIZED" in error_code):
            return "SQL_GUARD"
        return "SQL_EXECUTION"
    if not result_ok:
        return "RESULT_VALUE"
    if not semantic_ok:
        return "SEMANTIC"
    return None


def _security_regression(db: Session) -> tuple[int, int]:
    workspace = default_workspace(db)
    policies = {}
    for dialect in {item[0] for item in DANGEROUS_SQL_CASES}:
        datasource, model = _runtime(db, dialect)
        policies[dialect] = ContextBuilder().build(
            db, question="危险 SQL 安全回归", workspace=workspace,
            datasource=datasource, semantic_model=model, row_limit=100,
        ).security_policy
    guard = SqlGuard()
    blocked = sum(
        not guard.validate(sql, dialect=dialect, policy=policies[dialect]).allowed
        for dialect, sql in DANGEROUS_SQL_CASES
    )
    return len(DANGEROUS_SQL_CASES), blocked


def run_golden_evaluation(db: Session) -> EvaluationRun:
    manifest = load_golden_manifest()
    workspace = default_workspace(db)
    datasource, model = _runtime(db, "postgresql")
    started = time.perf_counter()
    run = EvaluationRun(
        workspace_id=workspace.id, release_name="ChatBI V2 Day 4 Golden 50",
        model_name="Local Runtime Provider", status="RUNNING", is_current=False,
        golden_set_count=len(manifest["cases"]), manifest_sha256=manifest["manifest_sha256"],
        completed_at=datetime.now(timezone.utc), sort_order=0,
    )
    db.add(run)
    db.flush()
    pipeline = QueryPipeline()
    case_rows: list[EvaluationCaseResult] = []
    for case in manifest["cases"]:
        query = pipeline.execute(db, AskRequest(
            question=case["question"], datasource_id=datasource.id,
            semantic_model_id=model.id, row_limit=500,
        ))
        plan = query.plan_payload or {}
        execution = query.execution_payload or {}
        execution_ok = execution.get("status") == "SUCCEEDED"
        semantic_ok, semantic_reasons = _semantic_match(case, plan)
        result_ok = False
        if execution_ok:
            expected_rows = case.get("expected_result") or []
            expected_columns = (
                list(expected_rows[0]) if expected_rows
                else [*(case.get("expected_dimensions") or []), *(case.get("expected_metrics") or [])]
            )
            query = pipeline.verify(db, query, ExpectedResult(
                columns=expected_columns,
                rows=expected_rows, tolerance=0.0001, order_independent=True,
                metric_names=case.get("expected_metrics") or [], dimension_names=case.get("expected_dimensions") or [],
                expected_signature=case.get("expected_signature"),
            ))
            result_ok = (query.oracle_payload or {}).get("status") == "PASSED"
        category = _error_category(
            execution_ok=execution_ok, result_ok=result_ok,
            semantic_ok=semantic_ok, error_code=query.error_code,
        )
        item = EvaluationCaseResult(
            evaluation_run_id=run.id, case_id=case["id"], category=case["category"],
            question=case["question"], status="PASS" if execution_ok and result_ok and semantic_ok else "FAIL",
            execution_ok=execution_ok, result_ok=result_ok, semantic_ok=semantic_ok,
            expected={
                "metrics": case.get("expected_metrics") or [], "dimensions": case.get("expected_dimensions") or [],
                "filters": case.get("expected_filters") or [], "time_range": case.get("expected_time_range"),
                "rows": case.get("expected_result") or [], "result_signature": case.get("expected_signature"),
                "sql": case.get("expected_sql"),
            },
            actual={"plan": plan, "execution": execution, "oracle": query.oracle_payload or {}, "semantic_reasons": semantic_reasons},
            generated_sql=query.normalized_sql or query.generated_sql,
            result_diff=_result_diff(case, execution, result_ok), error_category=category, query_run_id=query.id,
        )
        db.add(item)
        case_rows.append(item)
    dangerous_total, dangerous_blocked = _security_regression(db)
    execution_pass = sum(item.execution_ok for item in case_rows)
    result_pass = sum(item.result_ok for item in case_rows)
    semantic_pass = sum(item.semantic_ok for item in case_rows)
    total = len(case_rows)
    error_counts = Counter(item.error_category for item in case_rows if item.error_category)
    colors = {"SQL_EXECUTION": "#f04444", "RESULT_VALUE": "#f59e0b", "SEMANTIC": "#2f80ed", "SQL_GUARD": "#7c3aed"}
    if error_counts:
        failed_total = sum(error_counts.values())
        run.error_distribution = [
            {"label": key, "percent": round(value / failed_total * 100, 1), "color": colors.get(key, "#94a3b8")}
            for key, value in error_counts.items()
        ]
    else:
        run.error_distribution = [{"label": "无错误", "percent": 100, "color": "#16a36a"}]
    run.sql_execution_pass_count = execution_pass
    run.result_value_pass_count = result_pass
    run.semantic_pass_count = semantic_pass
    run.dangerous_sql_total = dangerous_total
    run.dangerous_sql_block_count = dangerous_blocked
    run.sql_generation_rate = round(execution_pass / total * 100, 2)
    run.result_accuracy = round(result_pass / total * 100, 2)
    run.semantic_accuracy = round(semantic_pass / total * 100, 2)
    run.relevance_accuracy = round(min(result_pass, semantic_pass) / total * 100, 2)
    durations = [int((item.actual.get("execution") or {}).get("duration_ms") or 0) for item in case_rows]
    run.average_response_seconds = round(sum(durations) / max(total, 1) / 1000, 3)
    run.duration_seconds = max(1, round(time.perf_counter() - started))
    run.completed_at = datetime.now(timezone.utc)
    gate_pass = execution_pass >= 49 and result_pass >= 48 and dangerous_blocked == dangerous_total
    run.status = "PASS" if gate_pass else "FAIL"
    for previous in db.scalars(select(EvaluationRun).where(EvaluationRun.id != run.id, EvaluationRun.is_current.is_(True))):
        previous.is_current = False
    run.is_current = True
    run.trend_points = [{"date": run.completed_at.strftime("%m/%d %H:%M"), "value": run.result_accuracy}]
    db.commit()
    db.refresh(run)
    return run


def evaluation_run_detail(db: Session, run_id: str) -> tuple[EvaluationRun, list[EvaluationCaseResult]]:
    run = db.get(EvaluationRun, run_id)
    if run is None:
        raise LookupError("Evaluation run not found")
    cases = list(db.scalars(
        select(EvaluationCaseResult).where(EvaluationCaseResult.evaluation_run_id == run.id).order_by(EvaluationCaseResult.case_id)
    ))
    return run, cases


def evaluation_case_detail(db: Session, case_ref: str) -> tuple[EvaluationRun, EvaluationCaseResult, str | None, str | None]:
    case = db.scalar(
        select(EvaluationCaseResult)
        .join(EvaluationRun, EvaluationRun.id == EvaluationCaseResult.evaluation_run_id)
        .where(or_(EvaluationCaseResult.id == case_ref, EvaluationCaseResult.case_id == case_ref))
        .order_by(EvaluationRun.is_current.desc(), EvaluationRun.completed_at.desc())
    )
    if case is None:
        raise LookupError("Evaluation case not found")
    run = db.get(EvaluationRun, case.evaluation_run_id)
    cases = list(db.scalars(
        select(EvaluationCaseResult).where(EvaluationCaseResult.evaluation_run_id == case.evaluation_run_id).order_by(EvaluationCaseResult.case_id)
    ))
    index = next(index for index, item in enumerate(cases) if item.id == case.id)
    previous_id = cases[index - 1].case_id if index > 0 else None
    next_id = cases[index + 1].case_id if index + 1 < len(cases) else None
    return run, case, previous_id, next_id
