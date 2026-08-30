from __future__ import annotations

import copy
import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.evaluation import DANGEROUS_SQL_CASES
from app.evaluation.ibm_adapter import ACCURACY_DIMENSIONS, IbmText2SqlEvaluationAdapter
from app.models import DataSource, EvaluationCaseResult, EvaluationRun, SemanticModel
from app.query.context_builder import ContextBuilder
from app.query.contracts import AskRequest, ExpectedResult
from app.core.access import Principal
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
GOLDEN_MANIFEST_SHA256 = "ff83e727331fb137cd8cc692aa780c3ba016c48adeec4246d4464874fbf7db1d"
SOURCE_GOLDEN_20_SHA256 = "741da55b7dd41046a6f8411522a3cf92afb45ca1ac38b90b202b49c87f8eef0e"
_MULTI_GROUND_TRUTH_CANDIDATES = (
    _SERVICE_FILE.parents[3] / "evaluation" / "golden" / "v2.1-multiple-ground-truth.json",
    _SERVICE_FILE.parents[2] / "evaluation" / "golden" / "v2.1-multiple-ground-truth.json",
)
MULTI_GROUND_TRUTH_PATH = next(
    (candidate for candidate in _MULTI_GROUND_TRUTH_CANDIDATES if candidate.is_file()),
    _MULTI_GROUND_TRUTH_CANDIDATES[-1],
)
MULTI_GROUND_TRUTH_SHA256 = "1e11b66f241f951e0265b3510310eaf856553ba2f2b4cea17854dc56aada4f36"
RELEASE_THRESHOLDS = {
    "golden_count": 50,
    "sql_execution_rate": 0.98,
    "result_value_accuracy": 0.95,
    "dangerous_sql_block_rate": 1.0,
}
DEFAULT_PROFILE = {
    "model": "deterministic",
    "prompt": "chatbi-eval-v2.1",
    "semantic_engine": "chatbi-semantic",
    "nl2sql_engine": "chatbi-nl2sql",
    "version": "v2.1",
}
COMPARISON_AXES = ["model", "prompt", "semantic_engine", "nl2sql_engine", "version"]


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


def load_multiple_ground_truth() -> dict[str, list[str]]:
    payload = MULTI_GROUND_TRUTH_PATH.read_bytes()
    canonical_payload = payload.replace(b"\r\n", b"\n")
    if hashlib.sha256(canonical_payload).hexdigest() != MULTI_GROUND_TRUTH_SHA256:
        raise RuntimeError("Multiple Ground Truth overlay SHA-256 is invalid")
    overlay = json.loads(canonical_payload)
    cases = overlay.get("cases") or {}
    if overlay.get("source_manifest_sha256") != GOLDEN_MANIFEST_SHA256 or not cases:
        raise RuntimeError("Multiple Ground Truth overlay does not match Golden 50")
    if any(not values or not all(str(sql).lstrip().upper().startswith(("SELECT", "WITH")) for sql in values) for values in cases.values()):
        raise RuntimeError("Multiple Ground Truth overlay contains an invalid SQL ground truth")
    return cases


def _profile_record(profile: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "evaluation_profile", "profile": {**DEFAULT_PROFILE, **profile}}


def _profile(run: EvaluationRun, cases: list[EvaluationCaseResult] | None = None) -> dict[str, Any]:
    for point in run.trend_points or []:
        if point.get("kind") == "evaluation_profile":
            return {**DEFAULT_PROFILE, **(point.get("profile") or {})}
    for case in cases or []:
        value = (case.actual or {}).get("evaluation_profile")
        if value:
            return {**DEFAULT_PROFILE, **value}
    return {**DEFAULT_PROFILE, "model": run.model_name or DEFAULT_PROFILE["model"]}


def _public_trend_points(run: EvaluationRun) -> list[dict[str, Any]]:
    return [point for point in (run.trend_points or []) if point.get("kind") != "evaluation_profile"]


def demo_evaluation_trend(end_at: datetime, *, latest_value: float = 100.0) -> list[dict[str, Any]]:
    """Return a deterministic 30-day showcase series suitable for DB persistence."""

    values = [
        87.8, 88.4, 88.1, 89.2, 89.0, 89.8, 90.4, 90.1, 91.0, 91.6,
        91.2, 92.0, 92.4, 92.1, 93.0, 93.7, 93.4, 94.2, 94.8, 94.5,
        95.2, 95.7, 95.4, 96.3, 96.8, 97.1, 97.8, 98.5, 99.2, latest_value,
    ]
    start = end_at - timedelta(days=len(values) - 1)
    return [
        {
            "date": (start + timedelta(days=index)).strftime("%m/%d"),
            "value": value,
            "source": "SHOWCASE_DEMO",
        }
        for index, value in enumerate(values)
    ]


def _next_trend_points(
    previous: EvaluationRun | None,
    *,
    completed_at: datetime,
    latest_value: float,
) -> list[dict[str, Any]]:
    history = [
        point
        for point in (_public_trend_points(previous) if previous is not None else [])
        if point.get("source") != "SHOWCASE_DEMO"
    ]
    return [
        *history,
        {"date": completed_at.strftime("%m/%d %H:%M"), "value": latest_value},
    ][-30:]


def _ground_truths(case: dict[str, Any], alternatives: dict[str, list[str]]) -> list[dict[str, Any]]:
    rows = case.get("expected_result") or []
    columns = list(rows[0]) if rows else [*(case.get("expected_dimensions") or []), *(case.get("expected_metrics") or [])]
    sql_values = [case.get("expected_sql"), *(alternatives.get(case["id"]) or [])]
    return [
        {
            "id": f"{case['id']}-GT{index + 1}",
            "sql": sql,
            "columns": columns,
            "rows": rows,
            "result_signature": case.get("expected_signature"),
            "order_independent": True,
        }
        for index, sql in enumerate(sql_values)
        if sql
    ]


def _semantic_accuracy(case: dict[str, Any], query) -> dict[str, bool]:
    plan = query.plan_payload or {}
    execution = query.execution_payload or {}
    chart = query.chart_spec_payload or {}
    narrative = query.narrative_payload or {}
    expected_filters = {(item["field"], str(item.get("value"))) for item in case.get("expected_filters", [])}
    actual_filters = {(item["field"], str(item.get("value"))) for item in plan.get("filters", [])}
    expected_time = case.get("expected_time_range")
    actual_time = plan.get("time_range")
    time_ok = (
        actual_time is None if expected_time is None
        else bool(actual_time and actual_time.get("start") == expected_time.get("start") and actual_time.get("end_exclusive") == expected_time.get("end_exclusive"))
    )
    expected_entities = set(case.get("expected_entities") or [])
    selected_entities = set(plan.get("selected_entities") or [])
    join_ok = expected_entities.issubset(selected_entities)
    if len(expected_entities) > 1:
        join_ok = join_ok and len(plan.get("joins") or []) >= len(expected_entities) - 1
    columns = list(execution.get("columns") or [])
    row_count = len(execution.get("rows") or [])
    chart_ok = bool(
        chart
        and chart.get("data_source_query_id") == query.id
        and chart.get("result_signature") == execution.get("result_signature")
        and set(chart.get("bound_columns") or []) == set(columns)
    )
    evidence_ok = all(
        all(isinstance(index, int) and 0 <= index < row_count for index in item.get("row_indexes", []))
        and set(item.get("fields", [])).issubset(set(columns))
        for item in narrative.get("evidence", [])
    )
    narrative_ok = bool(
        narrative
        and narrative.get("source_query_id") == query.id
        and narrative.get("result_signature") == execution.get("result_signature")
        and evidence_ok
    )
    return {
        "metric": set(plan.get("metrics") or []) == set(case.get("expected_metrics") or []),
        "dimension": set(plan.get("dimensions") or []) == set(case.get("expected_dimensions") or []),
        "time": time_ok,
        "filter": expected_filters == actual_filters,
        "join": join_ok,
        "chart": chart_ok,
        "narrative": narrative_ok,
    }


def _case_rows(db: Session, run_id: str) -> list[EvaluationCaseResult]:
    return list(db.scalars(
        select(EvaluationCaseResult)
        .where(EvaluationCaseResult.evaluation_run_id == run_id)
        .order_by(EvaluationCaseResult.case_id)
    ))


def _run_view(run: EvaluationRun, cases: list[EvaluationCaseResult]) -> dict[str, Any]:
    adapter = IbmText2SqlEvaluationAdapter()
    summaries = [
        {
            "accuracy_checks": (case.actual or {}).get("accuracy_checks") or {},
            "error_analysis": (case.actual or {}).get("error_analysis") or {},
            "ground_truth_count": (case.actual or {}).get("ground_truth_count") or 1,
        }
        for case in cases
    ]
    summary = adapter.summarize(summaries)
    total = max(run.golden_set_count, 1)
    dangerous_rate = run.dangerous_sql_block_count / run.dangerous_sql_total if run.dangerous_sql_total else 0.0
    gate = {
        "status": "PASS" if (
            run.golden_set_count >= RELEASE_THRESHOLDS["golden_count"]
            and run.sql_execution_pass_count / total >= RELEASE_THRESHOLDS["sql_execution_rate"]
            and run.result_value_pass_count / total >= RELEASE_THRESHOLDS["result_value_accuracy"]
            and dangerous_rate == RELEASE_THRESHOLDS["dangerous_sql_block_rate"]
        ) else "FAIL",
        "thresholds": RELEASE_THRESHOLDS,
    }
    return {
        **{column.name: getattr(run, column.name) for column in run.__table__.columns},
        "trend_points": _public_trend_points(run),
        "profile": _profile(run, cases),
        "accuracy": summary["accuracy"],
        "release_gate": gate,
        "multiple_ground_truth": summary["multiple_ground_truth"],
    }


def evaluation_overview(db: Session, workspace_id: str) -> dict:
    comparisons = list(db.scalars(
        select(EvaluationRun)
        .where(EvaluationRun.workspace_id == workspace_id)
        .order_by(EvaluationRun.sort_order, EvaluationRun.completed_at.desc())
    ))
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
    return {
        "current": _run_view(current, _case_rows(db, current.id)),
        "metrics": metrics,
        "comparisons": [_run_view(run, _case_rows(db, run.id)) for run in comparisons],
    }


def create_evaluation(db: Session, *, workspace_id: str, name: str, profile: dict[str, Any]) -> EvaluationRun:
    manifest = load_golden_manifest()
    resolved_profile = {**DEFAULT_PROFILE, **profile}
    run = EvaluationRun(
        workspace_id=workspace_id,
        release_name=name,
        model_name=resolved_profile["model"],
        status="CREATED",
        is_current=False,
        golden_set_count=len(manifest["cases"]),
        manifest_sha256=manifest["manifest_sha256"],
        completed_at=datetime.now(timezone.utc),
        sort_order=0,
        trend_points=[_profile_record(resolved_profile)],
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _runtime(db: Session, dialect: str, workspace_id: str) -> tuple[DataSource, SemanticModel]:
    datasource = db.scalar(select(DataSource).where(DataSource.type == dialect, DataSource.workspace_id == workspace_id).order_by(DataSource.created_at))
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


def _security_regression(db: Session, workspace_id: str) -> tuple[int, int]:
    workspace = default_workspace(db)
    if workspace.id != workspace_id:
        from app.models import Workspace
        workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise LookupError("Workspace not found")
    policies = {}
    for dialect in {item[0] for item in DANGEROUS_SQL_CASES}:
        datasource, model = _runtime(db, dialect, workspace_id)
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


def run_golden_evaluation(
    db: Session,
    principal: Principal,
    *,
    run_id: str | None = None,
    profile: dict[str, Any] | None = None,
) -> EvaluationRun:
    manifest = load_golden_manifest()
    workspace_id = principal.workspace_id
    datasource, model = _runtime(db, "postgresql", workspace_id)
    started = time.perf_counter()
    if run_id:
        run, _ = evaluation_run_detail(db, run_id, workspace_id)
        if run.status != "CREATED":
            raise ValueError("Only a CREATED evaluation can be executed")
        resolved_profile = _profile(run)
        run.status = "RUNNING"
    else:
        resolved_profile = {**DEFAULT_PROFILE, **(profile or {})}
        run = EvaluationRun(
            workspace_id=workspace_id, release_name="ChatBI V2.1 Golden 50",
            model_name=resolved_profile["model"], status="RUNNING", is_current=False,
            golden_set_count=len(manifest["cases"]), manifest_sha256=manifest["manifest_sha256"],
            completed_at=datetime.now(timezone.utc), sort_order=0,
            trend_points=[_profile_record(resolved_profile)],
        )
        db.add(run)
    db.flush()
    pipeline = QueryPipeline()
    resolved_profile["model"] = str(pipeline.router.capabilities().get("provider") or resolved_profile["model"])
    run.model_name = resolved_profile["model"]
    adapter = IbmText2SqlEvaluationAdapter()
    alternatives = load_multiple_ground_truth()
    case_rows: list[EvaluationCaseResult] = []
    for case in manifest["cases"]:
        query = pipeline.execute(db, AskRequest(
            question=case["question"], datasource_id=datasource.id,
            semantic_model_id=model.id, row_limit=500,
        ), principal=principal)
        plan = query.plan_payload or {}
        execution = query.execution_payload or {}
        execution_ok = execution.get("status") == "SUCCEEDED"
        ground_truths = _ground_truths(case, alternatives)
        result_compare = adapter.compare_results(actual=execution, ground_truths=ground_truths) if execution_ok else {
            "passed": False, "matched_ground_truth_id": None, "attempts": [], "result_diff": [],
        }
        result_ok = bool(result_compare["passed"])
        if execution_ok:
            matched = next(
                (truth for truth in ground_truths if truth["id"] == result_compare["matched_ground_truth_id"]),
                ground_truths[0],
            )
            query = pipeline.verify(db, query, ExpectedResult(
                columns=matched["columns"],
                rows=matched["rows"], tolerance=0.0001, order_independent=True,
                metric_names=case.get("expected_metrics") or [], dimension_names=case.get("expected_dimensions") or [],
                expected_signature=matched.get("result_signature"),
            ))
            result_ok = result_ok and (query.oracle_payload or {}).get("status") == "PASSED"
        accuracy_checks = _semantic_accuracy(case, query)
        accuracy_checks["result_value"] = result_ok
        semantic_ok = all(accuracy_checks[key] for key in ("metric", "dimension", "time", "filter", "join"))
        _, semantic_reasons = _semantic_match(case, plan)
        error_analysis = adapter.error_analysis(
            execution_ok=execution_ok,
            guard_allowed=bool((query.guard_payload or {}).get("allowed")),
            checks=accuracy_checks,
            error_code=query.error_code,
        )
        case_passed = execution_ok and all(accuracy_checks.values())
        item = EvaluationCaseResult(
            evaluation_run_id=run.id, case_id=case["id"], category=case["category"],
            question=case["question"], status="PASS" if case_passed else "FAIL",
            execution_ok=execution_ok, result_ok=result_ok, semantic_ok=semantic_ok,
            expected={
                "metrics": case.get("expected_metrics") or [], "dimensions": case.get("expected_dimensions") or [],
                "filters": case.get("expected_filters") or [], "time_range": case.get("expected_time_range"),
                "rows": case.get("expected_result") or [], "result_signature": case.get("expected_signature"),
                "sql": case.get("expected_sql"), "ground_truths": ground_truths,
            },
            actual={
                "plan": plan,
                "execution": execution,
                "oracle": query.oracle_payload or {},
                "chart": query.chart_spec_payload or {},
                "narrative": query.narrative_payload or {},
                "semantic_reasons": semantic_reasons,
                "accuracy_checks": accuracy_checks,
                "result_compare": result_compare,
                "error_analysis": error_analysis,
                "ground_truth_count": len(ground_truths),
                "evaluation_profile": resolved_profile,
                "evaluation_adapter": adapter.adapter_id,
            },
            generated_sql=query.normalized_sql or query.generated_sql,
            result_diff=result_compare["result_diff"], error_category=error_analysis["primary"], query_run_id=query.id,
        )
        db.add(item)
        case_rows.append(item)
    dangerous_total, dangerous_blocked = _security_regression(db, workspace_id)
    execution_pass = sum(item.execution_ok for item in case_rows)
    result_pass = sum(item.result_ok for item in case_rows)
    semantic_pass = sum(item.semantic_ok for item in case_rows)
    total = len(case_rows)
    error_counts = Counter(item.error_category for item in case_rows if item.error_category)
    colors = {"SQL_EXECUTION": "#f04444", "RESULT_VALUE_ACCURACY": "#f59e0b", "METRIC_ACCURACY": "#2f80ed", "SQL_GUARD": "#7c3aed"}
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
    previous_runs = list(db.scalars(select(EvaluationRun).where(
        EvaluationRun.workspace_id == workspace_id,
        EvaluationRun.id != run.id,
        EvaluationRun.is_current.is_(True),
    ).order_by(EvaluationRun.completed_at.desc())))
    for previous in previous_runs:
        previous.is_current = False
    run.is_current = True
    run.trend_points = [
        _profile_record(resolved_profile),
        *_next_trend_points(
            previous_runs[0] if previous_runs else None,
            completed_at=run.completed_at,
            latest_value=run.result_accuracy,
        ),
    ]
    db.commit()
    db.refresh(run)
    return run


def evaluation_run_detail(db: Session, run_id: str, workspace_id: str) -> tuple[EvaluationRun, list[EvaluationCaseResult]]:
    run = db.get(EvaluationRun, run_id)
    if run is None or run.workspace_id != workspace_id:
        raise LookupError("Evaluation run not found")
    cases = list(db.scalars(
        select(EvaluationCaseResult).where(EvaluationCaseResult.evaluation_run_id == run.id).order_by(EvaluationCaseResult.case_id)
    ))
    return run, cases


def evaluation_run_view(run: EvaluationRun, cases: list[EvaluationCaseResult]) -> dict[str, Any]:
    return _run_view(run, cases)


def compare_evaluation_runs(db: Session, run_ids: list[str], workspace_id: str) -> dict[str, Any]:
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("Evaluation comparison contains duplicate run IDs")
    rows: list[tuple[EvaluationRun, list[EvaluationCaseResult], dict[str, Any]]] = []
    for run_id in run_ids:
        run, cases = evaluation_run_detail(db, run_id, workspace_id)
        if run.status not in {"PASS", "FAIL"}:
            raise ValueError("Only completed evaluation runs can be compared")
        rows.append((run, cases, _run_view(run, cases)))
    metrics: list[dict[str, Any]] = []
    for key in ("sql_generation_rate", "result_accuracy", "semantic_accuracy", "average_response_seconds"):
        metrics.append({
            "key": key,
            "values": [{"run_id": run.id, "value": view[key]} for run, _, view in rows],
        })
    for dimension in ACCURACY_DIMENSIONS:
        metrics.append({
            "key": f"{dimension}_accuracy",
            "values": [{"run_id": run.id, "value": view["accuracy"].get(dimension, 0.0)} for run, _, view in rows],
        })
    winner = max(rows, key=lambda item: (
        item[2]["result_accuracy"],
        item[2]["sql_generation_rate"],
        item[2]["semantic_accuracy"],
        -item[2]["average_response_seconds"],
    ))[0]
    return {
        "axes": COMPARISON_AXES,
        "runs": [view for _, _, view in rows],
        "metrics": metrics,
        "winner_run_id": winner.id,
    }


def release_gate(db: Session, run_id: str, workspace_id: str) -> dict[str, Any]:
    run, _ = evaluation_run_detail(db, run_id, workspace_id)
    total = max(run.golden_set_count, 1)
    metrics = {
        "golden_count": float(run.golden_set_count),
        "sql_execution_rate": round(run.sql_execution_pass_count / total, 4),
        "result_value_accuracy": round(run.result_value_pass_count / total, 4),
        "dangerous_sql_block_rate": round(run.dangerous_sql_block_count / run.dangerous_sql_total, 4) if run.dangerous_sql_total else 0.0,
    }
    checks = [
        {"key": "golden_count", "passed": metrics["golden_count"] >= RELEASE_THRESHOLDS["golden_count"]},
        {"key": "sql_execution_rate", "passed": metrics["sql_execution_rate"] >= RELEASE_THRESHOLDS["sql_execution_rate"]},
        {"key": "result_value_accuracy", "passed": metrics["result_value_accuracy"] >= RELEASE_THRESHOLDS["result_value_accuracy"]},
        {"key": "dangerous_sql_block_rate", "passed": metrics["dangerous_sql_block_rate"] == RELEASE_THRESHOLDS["dangerous_sql_block_rate"]},
    ]
    return {
        "run_id": run.id,
        "status": "PASS" if all(item["passed"] for item in checks) else "FAIL",
        "thresholds": RELEASE_THRESHOLDS,
        "metrics": metrics,
        "checks": checks,
    }


def evaluation_dashboard(db: Session, workspace_id: str, run_id: str | None = None) -> dict[str, Any]:
    if run_id:
        run, cases = evaluation_run_detail(db, run_id, workspace_id)
    else:
        run = db.scalar(
            select(EvaluationRun)
            .where(EvaluationRun.workspace_id == workspace_id, EvaluationRun.is_current.is_(True))
            .order_by(EvaluationRun.completed_at.desc())
        )
        if run is None:
            raise LookupError("No current evaluation run is available")
        cases = _case_rows(db, run.id)
    view = _run_view(run, cases)
    error_counts = Counter(
        category
        for case in cases
        for category in (((case.actual or {}).get("error_analysis") or {}).get("categories") or [])
    )
    return {
        "current": view,
        "accuracy_cards": [
            {
                "key": dimension,
                "label": dimension.replace("_", " ").title(),
                "value": view["accuracy"].get(dimension, 0.0),
                "passed": view["accuracy"].get(dimension, 0.0) >= RELEASE_THRESHOLDS["result_value_accuracy"],
            }
            for dimension in ACCURACY_DIMENSIONS
        ],
        "error_analysis": [{"category": key, "count": value} for key, value in sorted(error_counts.items())],
        "release_gate": release_gate(db, run.id, workspace_id),
        "comparison_axes": COMPARISON_AXES,
    }


def evaluation_case_detail(db: Session, case_ref: str, workspace_id: str) -> tuple[EvaluationRun, EvaluationCaseResult, str | None, str | None]:
    case = db.scalar(
        select(EvaluationCaseResult)
        .join(EvaluationRun, EvaluationRun.id == EvaluationCaseResult.evaluation_run_id)
        .where(EvaluationRun.workspace_id == workspace_id, or_(EvaluationCaseResult.id == case_ref, EvaluationCaseResult.case_id == case_ref))
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
