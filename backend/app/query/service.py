from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    DataSource,
    QueryAuditEvent,
    QueryFeedback,
    QueryRun,
    SemanticModel,
    VerifiedAnswer,
)
from app.query.context_builder import ContextBuilder
from app.query.contracts import (
    AskRequest,
    ExecutionResult,
    ExpectedResult,
    FeedbackRequest,
    GuardResult,
    OracleResult,
    QueryResponse,
    SaveAnswerRequest,
)
from app.query.executor import QueryExecutor
from app.query.nl2sql import Nl2SqlRouter
from app.query.oracle import ResultOracle
from app.query.sql_guard import SqlGuard
from app.services.datasources import default_workspace


def _json(model) -> dict:
    return model.model_dump(mode="json")


def _audit(db: Session, run: QueryRun, event_type: str, status: str, details: dict | None = None) -> None:
    db.add(QueryAuditEvent(
        query_run_id=run.id,
        event_type=event_type,
        status=status,
        details=details or {},
    ))


def _select_runtime(db: Session, request: AskRequest) -> tuple[DataSource, SemanticModel]:
    if request.semantic_model_id:
        model = db.get(SemanticModel, request.semantic_model_id)
    elif request.datasource_id:
        model = db.scalar(
            select(SemanticModel)
            .where(SemanticModel.datasource_id == request.datasource_id)
            .order_by((SemanticModel.status == "PUBLISHED").desc(), SemanticModel.updated_at.desc())
        )
    else:
        model = db.scalar(
            select(SemanticModel)
            .join(DataSource, DataSource.id == SemanticModel.datasource_id)
            .where(DataSource.type == "postgresql")
            .order_by((SemanticModel.status == "PUBLISHED").desc(), SemanticModel.updated_at.desc())
        )
    if model is None:
        raise LookupError("No semantic model is available")
    datasource = db.get(DataSource, request.datasource_id or model.datasource_id)
    if datasource is None:
        raise LookupError("No datasource is available")
    if request.semantic_model_id and model.datasource_id != datasource.id:
        raise ValueError("Semantic model and datasource do not match")
    if datasource.type not in {"postgresql", "mysql"}:
        raise ValueError("Only PostgreSQL and MySQL are supported")
    return datasource, model


def _summary(run: QueryRun) -> tuple[str, list[dict], list[str]]:
    execution = run.execution_payload or {}
    rows = execution.get("rows") or []
    plan = run.plan_payload or {}
    metrics = plan.get("metrics") or []
    dimensions = plan.get("dimensions") or []
    if run.status == "SECURITY_REJECTED":
        return "查询被安全策略拒绝，未访问数据库。", [], ["请改用只读业务问题"]
    if run.status == "FAILED":
        return "查询未完成，请检查语义范围或数据源状态。", [], ["缩小时间范围后重试"]
    if run.status == "ORACLE_MISMATCH":
        return "查询已执行，但结果未通过完整校验，请勿据此决策。", [], ["查看查询依据", "提交结果问题反馈"]
    if not rows:
        return "查询已完成，当前条件下没有匹配数据。", [], ["放宽过滤条件", "查看最近 30 天"]
    kpis: list[dict] = []
    for metric in metrics[:4]:
        if metric in rows[0] and len(rows) == 1:
            kpis.append({"label": metric, "value": rows[0][metric], "unit": ""})
    if kpis:
        summary = f"查询完成，{metrics[0]} 为 {rows[0].get(metrics[0])}。"
    else:
        summary = f"查询完成，共返回 {len(rows)} 行按 {', '.join(dimensions) or '明细'} 汇总的结果。"
    recommended = [
        "按地区查看收入" if "region" not in dimensions else "查看各地区订单量",
        "查看最近30天趋势" if "month" not in dimensions else "对比收入与成本",
        "只看已支付订单",
    ]
    return summary, kpis, recommended


def query_response(run: QueryRun) -> QueryResponse:
    summary, kpis, recommendations = _summary(run)
    return QueryResponse(
        id=run.id,
        question=run.question,
        status=run.status,
        provider=run.provider,
        datasource_id=run.datasource_id,
        semantic_model_id=run.semantic_model_id,
        semantic_model_version=run.semantic_model_version,
        context=run.context_payload or {},
        plan=run.plan_payload or {},
        guard=run.guard_payload or {},
        execution=run.execution_payload or {},
        oracle=run.oracle_payload or {},
        summary=summary,
        kpis=kpis,
        recommended_questions=recommendations,
        error_code=run.error_code,
        error_message=run.error_message,
    )


class QueryPipeline:
    def __init__(self):
        self.context_builder = ContextBuilder()
        self.router = Nl2SqlRouter()
        self.guard = SqlGuard()
        self.executor = QueryExecutor()
        self.oracle = ResultOracle()

    def execute(self, db: Session, request: AskRequest) -> QueryRun:
        settings = get_settings()
        workspace = default_workspace(db)
        datasource, model = _select_runtime(db, request)
        row_limit = min(request.row_limit or settings.query_row_limit, settings.query_row_limit)
        run = QueryRun(
            workspace_id=workspace.id,
            datasource_id=datasource.id,
            semantic_model_id=model.id,
            semantic_model_version=model.version,
            question=request.question,
            status="PLANNING",
            provider=self.router.capabilities()["provider"],
        )
        db.add(run)
        db.flush()
        _audit(db, run, "QUERY_RECEIVED", "PASS", {"question_length": len(request.question)})
        try:
            context = self.context_builder.build(
                db, question=request.question, workspace=workspace, datasource=datasource,
                semantic_model=model, row_limit=row_limit,
            )
            run.context_payload = _json(context)
            _audit(db, run, "CONTEXT_BUILT", "PASS", {
                "link_count": len(context.linking_trace),
                "estimated_tokens": context.estimated_tokens,
                "truncated": context.truncated,
            })
            plan = self.router.plan(question=request.question, context=context)
            run.provider = plan.provider
            run.plan_payload = _json(plan)
            run.generated_sql = plan.generated_sql
            _audit(db, run, "SQL_PLAN_GENERATED", "PASS", {
                "provider": plan.provider, "confidence": plan.confidence, "repair_count": plan.repair_count,
            })
            guard = self.guard.validate(plan.generated_sql, dialect=context.dialect, policy=context.security_policy)
            run.guard_payload = _json(guard)
            _audit(db, run, "SQL_GUARD", "PASS" if guard.allowed else "REJECTED", {
                "statement_type": guard.statement_type,
                "issue_codes": [item.code for item in guard.issues],
            })
            if not guard.allowed:
                run.status = "SECURITY_REJECTED"
                run.error_code = guard.issues[0].code if guard.issues else "SQL_GUARD_REJECTED"
                run.error_message = guard.issues[0].message if guard.issues else "SQL rejected"
                run.oracle_payload = _json(OracleResult(status="NOT_RUN", confidence=0))
                db.commit()
                db.refresh(run)
                return run

            run.normalized_sql = guard.normalized_sql
            execution = self.executor.execute(
                datasource=datasource,
                normalized_sql=guard.normalized_sql or "",
                row_limit=guard.applied_limit or row_limit,
                timeout_ms=context.security_policy.timeout_ms,
            )
            run.execution_payload = _json(execution)
            run.duration_ms = execution.duration_ms
            run.result_signature = execution.result_signature
            _audit(db, run, "QUERY_EXECUTED", "PASS" if execution.status == "SUCCEEDED" else "FAIL", {
                "status": execution.status, "row_count": execution.row_count,
                "duration_ms": execution.duration_ms, "truncated": execution.truncated,
            })
            if execution.status != "SUCCEEDED":
                run.status = "FAILED"
                run.error_code = execution.error_code
                run.error_message = execution.error_message
                run.oracle_payload = _json(OracleResult(status="NOT_RUN", confidence=0))
            else:
                oracle = self.oracle.verify(plan=plan, guard=guard, execution=execution)
                run.oracle_payload = _json(oracle)
                run.status = "SUCCEEDED" if oracle.status == "PASSED" else "ORACLE_MISMATCH"
                _audit(db, run, "RESULT_ORACLE", oracle.status, {
                    "confidence": oracle.confidence, "mismatch_count": oracle.mismatch_count,
                })
            db.commit()
            db.refresh(run)
            return run
        except Exception as exc:
            run.status = "FAILED"
            run.error_code = "QUERY_PIPELINE_ERROR"
            run.error_message = str(exc)[:1000]
            _audit(db, run, "QUERY_PIPELINE", "FAIL", {"error_type": type(exc).__name__})
            db.commit()
            db.refresh(run)
            return run

    def verify(self, db: Session, run: QueryRun, expected: ExpectedResult) -> QueryRun:
        if not run.plan_payload or not run.guard_payload or not run.execution_payload:
            raise ValueError("Query has no executable result")
        from app.query.contracts import SQLPlan

        plan = SQLPlan.model_validate(run.plan_payload)
        guard = GuardResult.model_validate(run.guard_payload)
        execution = ExecutionResult.model_validate(run.execution_payload)
        oracle = self.oracle.verify(plan=plan, guard=guard, execution=execution, expected=expected)
        run.oracle_payload = _json(oracle)
        run.status = "SUCCEEDED" if oracle.status == "PASSED" else "ORACLE_MISMATCH"
        _audit(db, run, "RESULT_ORACLE_REVERIFY", oracle.status, {
            "confidence": oracle.confidence, "mismatch_count": oracle.mismatch_count,
        })
        db.commit()
        db.refresh(run)
        return run


def save_feedback(db: Session, run: QueryRun, data: FeedbackRequest) -> QueryFeedback:
    feedback = db.scalar(select(QueryFeedback).where(
        QueryFeedback.query_run_id == run.id,
        QueryFeedback.feedback_type == data.feedback_type,
    ))
    if feedback is None:
        feedback = QueryFeedback(query_run_id=run.id, **data.model_dump())
        db.add(feedback)
    else:
        feedback.comment = data.comment
    _audit(db, run, "USER_FEEDBACK", "RECORDED", {"feedback_type": data.feedback_type})
    db.commit()
    db.refresh(feedback)
    return feedback


def save_verified_answer(db: Session, run: QueryRun, data: SaveAnswerRequest) -> VerifiedAnswer:
    if run.status != "SUCCEEDED":
        raise ValueError("Only an Oracle-passed query can be saved as an answer")
    sort_order = len(list(db.scalars(select(VerifiedAnswer.id)))) + 1
    answer = VerifiedAnswer(
        workspace_id=run.workspace_id,
        question=run.question,
        module="问数据",
        sql_synced=True,
        model_name=f"Semantic v{run.semantic_model_version}",
        owner_name=data.owner_name,
        status=data.status,
        accuracy_percent=round(float((run.oracle_payload or {}).get("confidence", 0)) * 100, 2),
        sort_order=sort_order,
        query_run_id=run.id,
        sql_text=run.normalized_sql,
        result_signature=run.result_signature,
        semantic_model_version=run.semantic_model_version,
    )
    db.add(answer)
    _audit(db, run, "ANSWER_SAVED", "PASS", {"answer_status": data.status})
    db.commit()
    db.refresh(answer)
    return answer
