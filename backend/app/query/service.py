from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy import select
from threading import Event
from time import perf_counter
from sqlalchemy.orm import Session

from app.core.access import Principal, ensure_resource_access, record_audit
from app.core.config import get_settings
from app.model_gateway.contracts import BudgetMode, RequestContext
from app.model_gateway.ledger import bind_model_invocation_session
from app.models import (
    AnswerVersion,
    DataSource,
    QueryAuditEvent,
    QueryFeedback,
    QueryRun,
    SemanticModel,
    VerifiedAnswer,
    Workspace,
)
from app.chart import ChartEngine
from app.insight import NarrativeEngine
from app.query.context_builder import ContextBuilder
from app.query.contracts import (
    AskRequest,
    ExecutionResult,
    ExpectedResult,
    FeedbackRequest,
    GuardResult,
    OracleCheck,
    OracleResult,
    QueryResponse,
    SaveAnswerRequest,
)
from app.query.executor import QueryExecutor
from app.query.explain_cost import ExplainCostGuard
from app.query.nl2sql import Nl2SqlRouter
from app.query.oracle import ResultOracle
from app.query.projection_contract import ProjectionContractError, ProjectionContractValidator
from app.query.sql_guard import SqlGuard
from app.query.verification import VerificationQueryRunner
from app.semantic_runtime import SemanticRuntimeError, default_semantic_runtime
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


def _select_runtime(db: Session, request: AskRequest, workspace_id: str | None = None) -> tuple[DataSource, SemanticModel]:
    if request.semantic_model_id:
        model = db.get(SemanticModel, request.semantic_model_id)
    elif request.datasource_id:
        model = db.scalar(
            select(SemanticModel)
            .where(SemanticModel.datasource_id == request.datasource_id)
            .order_by((SemanticModel.status == "PUBLISHED").desc(), SemanticModel.created_at.asc(), SemanticModel.id.asc())
        )
    else:
        statement = (
            select(SemanticModel)
            .join(DataSource, DataSource.id == SemanticModel.datasource_id)
            .where(DataSource.type == "postgresql")
            .order_by((SemanticModel.status == "PUBLISHED").desc(), SemanticModel.created_at.asc(), SemanticModel.id.asc())
        )
        if workspace_id:
            statement = statement.where(SemanticModel.workspace_id == workspace_id)
        model = db.scalar(statement)
    if model is None:
        raise LookupError("No semantic model is available")
    if workspace_id and model.workspace_id != workspace_id:
        raise PermissionError("Semantic model belongs to another workspace")
    datasource = db.get(DataSource, request.datasource_id or model.datasource_id)
    if datasource is None:
        raise LookupError("No datasource is available")
    if workspace_id and datasource.workspace_id != workspace_id:
        raise PermissionError("Datasource belongs to another workspace")
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


def _canonical_scope(plan: dict) -> str | None:
    time_range = plan.get("time_range") or {}
    start_raw = time_range.get("start")
    end_raw = time_range.get("end_exclusive")
    scope: str | None = None
    if start_raw and end_raw:
        try:
            start, end = date.fromisoformat(str(start_raw)), date.fromisoformat(str(end_raw))
        except ValueError:
            start = end = None
        if start is not None and end is not None:
            if (end - start).days == 1:
                scope = start.isoformat()
            elif start.day == 1 and start.month in {1, 4, 7, 10} and (end.month - start.month) % 12 == 3:
                scope = f"{start.year}Q{((start.month - 1) // 3) + 1}"
    suffixes: list[str] = []
    region_codes = {"华东": "EAST", "华南": "SOUTH", "华北": "NORTH", "华中": "CENTRAL", "西部": "WEST"}
    category_codes = {"充电设备": "CHARGING_CATEGORY"}
    for item in plan.get("filters") or []:
        field, value = str(item.get("field") or ""), item.get("value")
        if field == "orders.status" and str(value).upper() == "PAID":
            suffixes.append("PAID")
        elif field == "regions.region_name" and str(value) in region_codes:
            suffixes.append(region_codes[str(value)])
        elif field == "products.category" and str(value) in category_codes:
            suffixes.append(category_codes[str(value)])
    return "_".join([part for part in [scope, *suffixes] if part]) or None


def _verified_answer_claims(run: QueryRun) -> list[dict]:
    plan = run.plan_payload or {}
    execution = run.execution_payload or {}
    if (run.oracle_payload or {}).get("status") != "PASSED":
        return []
    rows = list(execution.get("rows") or [])
    metrics = [item for item in plan.get("metrics") or [] if rows and item in rows[0]]
    dimensions = [item for item in plan.get("dimensions") or [] if rows and item in rows[0]]
    if not rows or not metrics:
        return []
    time_kind = str((plan.get("time_range") or {}).get("kind") or "").upper()
    if "profit" in metrics:
        metric = "profit"
    elif "DAY" in time_kind and "order_count" in metrics:
        metric = "order_count"
    elif "revenue" in metrics:
        metric = "revenue"
    else:
        metric = metrics[0]
    comparable = [row for row in rows if isinstance(row.get(metric), (int, float))]
    selected = max(comparable, key=lambda row: row[metric]) if comparable else rows[0]
    claim: dict = {"metric": metric, "value": selected.get(metric)}
    dimension_fields = {
        "region": "regions.region_name",
        "category": "products.category",
        "product": "products.product_name",
        "customer": "customers.customer_name",
        "customer_type": "customers.customer_type",
        "status": "orders.status",
    }
    constrained_fields = {
        str(item.get("field") or "")
        for item in plan.get("filters") or []
        if str(item.get("operator") or "=").upper() in {"=", "IN"}
    }
    dimension = next(
        (item for item in dimensions if dimension_fields.get(item) not in constrained_fields),
        None,
    )
    if dimension:
        claim.update({"dimension": dimension, "dimension_value": selected.get(dimension)})
    else:
        scope = _canonical_scope(plan)
        if scope:
            claim["scope"] = scope
    return [claim]


def _claim_summary(run: QueryRun, claims: list[dict], fallback: str) -> str:
    rows = list((run.execution_payload or {}).get("rows") or [])
    if not rows and run.status == "SUCCEEDED":
        return "查询已完成，当前条件下没有数据，未生成业务结论。"
    if not claims:
        return fallback
    claim = claims[0]
    label = f"{claim['dimension_value']}的" if claim.get("dimension_value") is not None else ""
    return f"{label}{claim['metric']} 为 {claim['value']}。"


def query_response(run: QueryRun) -> QueryResponse:
    fallback_summary, fallback_kpis, fallback_recommendations = _summary(run)
    narrative = run.narrative_payload or {}
    claims = _verified_answer_claims(run)
    summary = _claim_summary(run, claims, narrative.get("conclusion") or fallback_summary)
    kpis = narrative.get("key_metrics") or fallback_kpis
    recommendations = run.follow_up_payload or narrative.get("recommended_questions") or fallback_recommendations
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
        chart_spec=run.chart_spec_payload or {},
        narrative=narrative,
        result_evidence={
            "metrics": list((run.plan_payload or {}).get("metrics") or []),
            "dimensions": list((run.plan_payload or {}).get("dimensions") or []),
            "row_count": len((run.execution_payload or {}).get("rows") or []),
            "rows": list((run.execution_payload or {}).get("rows") or []),
            "result_signature": (run.execution_payload or {}).get("result_signature"),
            "oracle_status": (run.oracle_payload or {}).get("status"),
        },
        answer_claims=claims,
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
        self.semantic_runtime = default_semantic_runtime()
        self.guard = SqlGuard()
        self.executor = QueryExecutor()
        self.explain_cost_guard = ExplainCostGuard()
        self.verification_runner = VerificationQueryRunner(guard=self.guard, executor=self.executor)
        self.oracle = ResultOracle()
        self.chart_engine = ChartEngine()
        self.narrative_engine = NarrativeEngine()

    def _build_presentation(self, run: QueryRun) -> None:
        if not run.plan_payload or not run.execution_payload:
            return
        chart = self.chart_engine.plan(query_id=run.id, plan=run.plan_payload, execution=run.execution_payload)
        narrative = self.narrative_engine.generate(
            query_id=run.id,
            semantic_model_version=run.semantic_model_version,
            plan=run.plan_payload,
            execution=run.execution_payload,
            oracle=run.oracle_payload or {},
            chart_spec=chart,
        )
        run.chart_spec_payload = _json(chart)
        run.narrative_payload = _json(narrative)
        run.follow_up_payload = narrative.recommended_questions

    def execute(
        self, db: Session, request: AskRequest, principal: Principal | None = None,
        *, cancellation_event: Event | None = None, request_context: RequestContext | None = None,
    ) -> QueryRun:
        with bind_model_invocation_session(db):
            return self._execute(
                db, request, principal,
                cancellation_event=cancellation_event,
                request_context=request_context,
            )

    def _execute(
        self, db: Session, request: AskRequest, principal: Principal | None = None,
        *, cancellation_event: Event | None = None, request_context: RequestContext | None = None,
    ) -> QueryRun:
        settings = get_settings()
        workspace = db.get(Workspace, principal.workspace_id) if principal and principal.workspace_id else default_workspace(db)
        if workspace is None:
            raise PermissionError("Workspace is unavailable")
        if principal is not None and request.datasource_id:
            ensure_resource_access(db, principal, resource_type="DATASOURCE", resource_id=request.datasource_id, query=True)
        if principal is not None and request.semantic_model_id:
            ensure_resource_access(db, principal, resource_type="SEMANTIC_MODEL", resource_id=request.semantic_model_id, query=True)
        datasource, model = _select_runtime(db, request, workspace.id)
        if principal is not None:
            ensure_resource_access(db, principal, resource_type="DATASOURCE", resource_id=datasource.id, query=True)
            ensure_resource_access(db, principal, resource_type="SEMANTIC_MODEL", resource_id=model.id, query=True)
        row_limit = min(request.row_limit or settings.query_row_limit, settings.query_row_limit)
        run = QueryRun(
            workspace_id=workspace.id,
            datasource_id=datasource.id,
            semantic_model_id=model.id,
            semantic_model_version=model.version,
            question=request.question,
            status="PLANNING",
            provider=(
                "wrenai-upstream-runtime"
                if settings.semantic_runtime_mode == "wren" and settings.semantic_upstream_reuse_mode == "selected_source"
                else "wren-clean-room-runtime"
                if settings.semantic_runtime_mode == "wren"
                else self.router.capabilities()["provider"]
            ),
        )
        db.add(run)
        db.flush()
        runtime_context = request_context or RequestContext(
            request_id=run.id,
            trace_id=f"TRACE-{run.id}",
            route="DATA_QUERY",
            user_id=(principal.user_id or principal.email) if principal is not None else "SYSTEM",
            workspace_id=workspace.id,
            datasource_id=datasource.id,
            roles=frozenset({principal.role}) if principal is not None else frozenset({"SYSTEM"}),
            permission_hash=hashlib.sha256(
                f"{workspace.id}:{principal.user_id if principal else 'SYSTEM'}:{principal.role if principal else 'SYSTEM'}".encode("utf-8")
            ).hexdigest(),
            question=request.question,
            budget_mode=BudgetMode(settings.model_budget_mode),
        )
        _audit(db, run, "QUERY_RECEIVED", "PASS", {"question_length": len(request.question)})
        try:
            context = self.context_builder.build(
                db, question=request.question, workspace=workspace, datasource=datasource,
                semantic_model=model, row_limit=row_limit,
                cache_role=principal.role if principal is not None else "SYSTEM",
                request_context=runtime_context,
            )
            run.context_payload = {
                **_json(context),
                "request_context": runtime_context.model_dump(
                    mode="json", exclude={"question"},
                ),
            }
            _audit(db, run, "CONTEXT_BUILT", "PASS", {
                "link_count": len(context.linking_trace),
                "estimated_tokens": context.estimated_tokens,
                "truncated": context.truncated,
            })
            plan, semantic_trace = self.semantic_runtime.plan(question=request.question, context=context)
            run.provider = plan.provider
            trace_payload = _json(semantic_trace)
            run.context_payload = {
                **_json(context),
                "request_context": runtime_context.model_dump(mode="json", exclude={"question"}),
                "semantic_runtime": trace_payload,
            }
            run.plan_payload = {
                **_json(plan),
                "semantic_query": trace_payload.get("semantic_query"),
                "wren_dry_plan": trace_payload.get("wren_dry_plan"),
                "runtime_call_chain": trace_payload.get("call_chain", []),
            }
            run.generated_sql = plan.generated_sql
            if semantic_trace.openchatbi_called:
                _audit(db, run, "OPENCHATBI_SCHEMA_LINKING", "PASS", {
                    "confidence": semantic_trace.schema_linking.confidence if semantic_trace.schema_linking else 0,
                    "elapsed_ms": semantic_trace.stage_latency_ms.get("openchatbi", 0),
                    "workspace_cache_scope": semantic_trace.schema_linking.cache_scope if semantic_trace.schema_linking else None,
                })
            if semantic_trace.supersonic_called:
                _audit(db, run, "SUPERSONIC_SEMANTIC_QUERY", "PASS", {
                    "confidence": semantic_trace.semantic_query.confidence if semantic_trace.semantic_query else 0,
                    "elapsed_ms": semantic_trace.stage_latency_ms.get("supersonic", 0),
                })
            if semantic_trace.wren_called:
                _audit(db, run, "WREN_DRY_PLAN", "PASS", {
                    "mapping_coverage": semantic_trace.wren_mdl.mapping_coverage if semantic_trace.wren_mdl else 0,
                    "dry_plan_status": semantic_trace.wren_dry_plan.status if semantic_trace.wren_dry_plan else None,
                    "elapsed_ms": semantic_trace.stage_latency_ms.get("wren", 0),
                })
            _audit(db, run, "SQL_PLAN_GENERATED", "PASS", {
                "provider": plan.provider, "confidence": plan.confidence, "repair_count": plan.repair_count,
            })
            try:
                projection_contract = ProjectionContractValidator().validate_and_normalize(
                    plan=plan,
                    context=context,
                )
            except ProjectionContractError as exc:
                run.status = "FAILED"
                run.error_code = exc.code
                run.error_message = exc.code
                run.plan_payload = {
                    **(run.plan_payload or {}),
                    "projection_contract_error": {"code": exc.code, "details": exc.details},
                }
                run.oracle_payload = _json(OracleResult(status="NOT_RUN", confidence=0))
                _audit(db, run, "PROJECTION_CONTRACT", "REJECTED", {
                    "code": exc.code,
                    "details": exc.details,
                })
                db.commit()
                db.refresh(run)
                if principal is not None:
                    record_audit(
                        db, principal, action="QUERY_RUN", resource_type="QUERY_RUN", resource_id=run.id,
                        status="FAILED", details={"error_code": run.error_code},
                    )
                    db.commit()
                return run
            plan = projection_contract.plan
            run.plan_payload = {
                **_json(plan),
                "semantic_query": trace_payload.get("semantic_query"),
                "wren_dry_plan": trace_payload.get("wren_dry_plan"),
                "runtime_call_chain": trace_payload.get("call_chain", []),
            }
            run.generated_sql = plan.generated_sql
            _audit(db, run, "PROJECTION_CONTRACT", "PASS", {
                "status": projection_contract.status,
                "dimensions": [item.canonical_name for item in plan.canonical_output_schema.dimensions],
                "metrics": [item.canonical_name for item in plan.canonical_output_schema.metrics],
                "auxiliary": [item.canonical_name for item in plan.canonical_output_schema.auxiliary],
                "normalization_action_count": len(projection_contract.normalization_actions),
            })
            if projection_contract.normalization_actions:
                _audit(db, run, "PROJECTION_NORMALIZATION_ACTION", "PASS", {
                    "actions": list(projection_contract.normalization_actions),
                })
            guard = self.guard.validate(plan.generated_sql, dialect=context.dialect, policy=context.security_policy)
            run.guard_payload = _json(guard)
            _audit(db, run, "SQL_GUARD", "PASS" if guard.allowed else "REJECTED", {
                "statement_type": guard.statement_type,
                "issue_codes": [item.code for item in guard.issues],
                "normalization_actions": guard.normalization_actions,
            })
            if not guard.allowed:
                run.status = "SECURITY_REJECTED"
                run.error_code = guard.issues[0].code if guard.issues else "SQL_GUARD_REJECTED"
                run.error_message = guard.issues[0].message if guard.issues else "SQL rejected"
                run.oracle_payload = _json(OracleResult(status="NOT_RUN", confidence=0))
                db.commit()
                db.refresh(run)
                if principal is not None:
                    record_audit(
                        db, principal, action="QUERY_RUN", resource_type="QUERY_RUN", resource_id=run.id,
                        status=run.status, details={"error_code": run.error_code},
                    )
                    db.commit()
                return run

            run.normalized_sql = guard.normalized_sql
            explain = self.executor.explain(
                datasource=datasource,
                normalized_sql=guard.normalized_sql or "",
                timeout_ms=context.security_policy.timeout_ms,
            )
            cost_assessment = self.explain_cost_guard.assess(
                explain,
                maximum_cost=settings.query_max_estimated_cost,
            )
            run.guard_payload = {
                **(run.guard_payload or {}),
                "explain_cost": _json(cost_assessment),
            }
            run.context_payload = {
                **(run.context_payload or {}),
                "query_performance": {
                    **((run.context_payload or {}).get("query_performance") or {}),
                    "explain_ms": explain.duration_ms,
                    "estimated_cost": cost_assessment.estimated_cost,
                },
            }
            _audit(db, run, "EXPLAIN_COST_GUARD", cost_assessment.status, {
                "estimated_cost": cost_assessment.estimated_cost,
                "maximum_cost": cost_assessment.maximum_cost,
                "duration_ms": cost_assessment.explain_duration_ms,
                "reason": cost_assessment.reason,
            })
            if cost_assessment.status != "PASS":
                run.status = "SECURITY_REJECTED"
                run.error_code = (
                    "QUERY_COST_LIMIT" if cost_assessment.status == "BLOCKED" else "QUERY_EXPLAIN_REQUIRED"
                )
                run.error_message = cost_assessment.reason
                run.oracle_payload = _json(OracleResult(status="NOT_RUN", confidence=0))
                db.commit()
                db.refresh(run)
                if principal is not None:
                    record_audit(
                        db, principal, action="QUERY_RUN", resource_type="QUERY_RUN", resource_id=run.id,
                        status=run.status, details={"error_code": run.error_code},
                    )
                    db.commit()
                return run

            executor_arguments = dict(
                datasource=datasource,
                normalized_sql=guard.normalized_sql or "",
                row_limit=guard.applied_limit or row_limit,
                timeout_ms=context.security_policy.timeout_ms,
            )
            if cancellation_event is not None:
                executor_arguments["cancellation_event"] = cancellation_event
            execution = self.executor.execute(**executor_arguments)
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
                oracle_started = perf_counter()
                oracle = self.oracle.verify(plan=plan, guard=guard, execution=execution)
                verification = self.verification_runner.run(
                    plan=plan,
                    datasource=datasource,
                    normalized_sql=guard.normalized_sql or "",
                    primary=execution,
                    policy=context.security_policy,
                    row_limit=guard.applied_limit or row_limit,
                    timeout_ms=context.security_policy.timeout_ms,
                    cancellation_event=cancellation_event,
                ) if settings.verification_query_enabled else None
                if verification is not None:
                    run.context_payload = {
                        **(run.context_payload or {}),
                        "verification_query": _json(verification),
                    }
                    _audit(
                        db,
                        run,
                        "VERIFICATION_QUERY",
                        "PASS" if verification.passed else "FAIL",
                        {
                            "required": verification.required,
                            "executed": verification.executed,
                            "kind": verification.kind,
                            "duration_ms": verification.duration_ms,
                            "query_sha256": verification.query_sha256,
                            "error_code": verification.error_code,
                        },
                    )
                    if verification.required:
                        oracle.checks.append(OracleCheck(
                            name="verification_query",
                            passed=verification.passed,
                            message=(
                                "Second guarded read-only query matched the primary result signature"
                                if verification.passed else "Verification query did not match the primary result"
                            ),
                        ))
                        if not verification.passed:
                            oracle.status = "MISMATCH"
                            oracle.mismatch_count += 1
                        oracle.confidence = round(
                            sum(1 for check in oracle.checks if check.passed) / len(oracle.checks),
                            4,
                        )
                oracle_duration_ms = round((perf_counter() - oracle_started) * 1000, 3)
                run.oracle_payload = _json(oracle)
                run.context_payload = {
                    **(run.context_payload or {}),
                    "query_performance": {
                        **((run.context_payload or {}).get("query_performance") or {}),
                        "oracle_ms": oracle_duration_ms,
                    },
                }
                self._build_presentation(run)
                oracle = self.oracle.verify_presentation(
                    oracle=oracle,
                    query_id=run.id,
                    execution=execution,
                    chart_spec=run.chart_spec_payload or {},
                    narrative=run.narrative_payload or {},
                )
                run.oracle_payload = _json(oracle)
                run.status = "SUCCEEDED" if oracle.status == "PASSED" else "ORACLE_MISMATCH"
                _audit(db, run, "RESULT_ORACLE", oracle.status, {
                    "confidence": oracle.confidence, "mismatch_count": oracle.mismatch_count,
                    "duration_ms": oracle_duration_ms,
                })
            db.commit()
            db.refresh(run)
            if principal is not None:
                record_audit(
                    db, principal, action="QUERY_RUN", resource_type="QUERY_RUN", resource_id=run.id,
                    status="SUCCESS" if run.status == "SUCCEEDED" else run.status,
                    details={"datasource_id": run.datasource_id, "semantic_model_id": run.semantic_model_id},
                )
                db.commit()
            return run
        except Exception as exc:
            run.status = "FAILED"
            if isinstance(exc, SemanticRuntimeError):
                run.error_code = str(exc.payload["code"])
                run.plan_payload = {**(run.plan_payload or {}), "structured_error": exc.payload}
                if exc.trace is not None:
                    run.context_payload = {**(run.context_payload or {}), "semantic_runtime": _json(exc.trace)}
            else:
                run.error_code = "QUERY_PIPELINE_ERROR"
            run.error_message = str(exc)[:1000]
            _audit(db, run, "QUERY_PIPELINE", "FAIL", {
                "error_type": type(exc).__name__,
                "structured_error": exc.payload if isinstance(exc, SemanticRuntimeError) else None,
            })
            db.commit()
            db.refresh(run)
            if principal is not None:
                record_audit(
                    db, principal, action="QUERY_RUN", resource_type="QUERY_RUN", resource_id=run.id,
                    status="FAILED", details={"error_code": run.error_code},
                )
                db.commit()
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
        self._build_presentation(run)
        oracle = self.oracle.verify_presentation(
            oracle=oracle,
            query_id=run.id,
            execution=execution,
            chart_spec=run.chart_spec_payload or {},
            narrative=run.narrative_payload or {},
        )
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
    helpful = db.scalar(select(QueryFeedback).where(
        QueryFeedback.query_run_id == run.id,
        QueryFeedback.feedback_type == "HELPFUL",
    ))
    if data.status == "VERIFIED" and helpful is None:
        raise ValueError("A positive user verification is required before saving a VERIFIED answer")
    sort_order = len(list(db.scalars(select(VerifiedAnswer.id)))) + 1
    semantic_intent = {
        "intent": (run.plan_payload or {}).get("intent"),
        "entities": (run.plan_payload or {}).get("selected_entities", []),
        "metrics": (run.plan_payload or {}).get("metrics", []),
        "dimensions": (run.plan_payload or {}).get("dimensions", []),
        "filters": (run.plan_payload or {}).get("filters", []),
        "time_range": (run.plan_payload or {}).get("time_range"),
    }
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
        semantic_intent=semantic_intent,
        sql_plan=run.plan_payload or {},
        result_snapshot=run.execution_payload or {},
        chart_spec=run.chart_spec_payload or {},
        narrative=run.narrative_payload or {},
        semantic_model_id=run.semantic_model_id,
        datasource_id=run.datasource_id,
        oracle_status=(run.oracle_payload or {}).get("status"),
        feedback={"type": "HELPFUL", "comment": helpful.comment if helpful else None},
    )
    db.add(answer)
    db.flush()
    db.add(AnswerVersion(
        answer_id=answer.id,
        version=1,
        snapshot={
            "question": answer.question,
            "semantic_intent": semantic_intent,
            "sql_plan": run.plan_payload or {},
            "sql": run.normalized_sql,
            "result_snapshot": run.execution_payload or {},
            "chart_spec": run.chart_spec_payload or {},
            "narrative": run.narrative_payload or {},
            "oracle_status": (run.oracle_payload or {}).get("status"),
        },
    ))
    _audit(db, run, "ANSWER_SAVED", "PASS", {"answer_status": data.status})
    db.commit()
    db.refresh(answer)
    return answer
