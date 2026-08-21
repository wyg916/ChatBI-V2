from __future__ import annotations

import hashlib
from threading import Event
from datetime import datetime, timezone
from uuid import uuid4

from chatbi_agent_contracts import (
    AgentExecutionContext,
    OrchestrationRequest,
    OrchestrationResult,
    QuestionRoute,
    ToolName,
)
from chatbi_agent_orchestrator import BoundedAgentOrchestrator
from chatbi_rag_adapter import CitationVerifierV1, LiveRagAdapter, RagAdapterError, UnavailableRagAdapter
from chatbi_rag_contracts import RagExecutionContext, RagRequest, RagResult
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access import Principal, has_resource_access, record_audit
from app.core.config import get_settings
from app.integration.contracts import AnalysisRequest, AnalysisResponse
from app.integration.feature_flags import decide
from app.integration.question_router import QuestionRouter
from app.integration.tool_executor import ChatBIToolExecutor
from app.model_gateway import BudgetMode, RequestContext
from app.models import (
    Citation as CitationRecord,
    DataSource,
    KnowledgeRetrievalRun,
    OrchestrationRun,
    OrchestrationProfile,
    OrchestrationStep,
    SemanticModel,
    PromptTemplate,
    PromptVersion,
    ToolCall,
)
from app.query.contracts import AskRequest
from app.query.service import QueryPipeline, query_response
from app.services.datasources import default_workspace


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AnalysisService:
    def __init__(self, *, router: QuestionRouter | None = None, rag_adapter=None) -> None:
        self.router = router or QuestionRouter()
        self._rag_adapter = rag_adapter
        self.verifier = CitationVerifierV1()
        self._runtime_context: RequestContext | None = None

    def execute(
        self,
        db: Session,
        request: AnalysisRequest,
        principal: Principal,
        *,
        progress_callback=None,
        cancellation_event: Event | None = None,
        request_context: RequestContext | None = None,
    ) -> AnalysisResponse:
        settings = get_settings()
        trace_id = request_context.trace_id if request_context else f"TRACE-{uuid4()}"
        self._runtime_context = request_context or RequestContext(
            request_id=request.idempotency_key or f"REQ-{uuid4()}",
            trace_id=trace_id,
            user_id=principal.user_id or principal.email,
            workspace_id=principal.workspace_id or "SYSTEM",
            datasource_id=request.datasource_id,
            roles=frozenset({principal.role}),
            permission_hash=hashlib.sha256(
                f"{principal.workspace_id}:{principal.user_id}:{principal.role}".encode("utf-8")
            ).hexdigest(),
            question=request.question,
            budget_mode=BudgetMode(settings.model_budget_mode),
        )
        route = self.router.classify(
            request.question, request.route, context=self._runtime_context,
        )
        if route == QuestionRoute.DATA_QUERY:
            primary = self._data(db, request, principal, cancellation_event=cancellation_event)
            self._audit_route(db, principal, route, trace_id, "SUCCESS", False)
            return self._response(route, trace_id, primary, settings=settings)

        rag_decision = decide(settings.rag_mode, trace_id)
        agent_decision = decide(settings.agent_mode, trace_id)
        if route == QuestionRoute.KNOWLEDGE_QUERY:
            return self._knowledge(db, request, principal, trace_id, rag_decision, cancellation_event=cancellation_event)
        if route == QuestionRoute.HYBRID_ANALYSIS:
            return self._hybrid(db, request, principal, trace_id, rag_decision, cancellation_event=cancellation_event)
        if route == QuestionRoute.COMPLEX_ANALYSIS:
            if route.value not in settings.agent_route_allowlist or not agent_decision.publish:
                if not settings.agent_fallback_enabled:
                    primary = {"status": "REFUSED", "error_code": "AGENT_ROUTE_DISABLED"}
                    self._audit_route(db, principal, route, trace_id, "REFUSED", False)
                    return self._response(route, trace_id, primary, settings=settings)
                primary = self._data(db, request, principal, cancellation_event=cancellation_event)
                self._audit_route(db, principal, route, trace_id, "FALLBACK", True)
                return self._response(route, trace_id, primary, fallback=True, settings=settings)
            return self._complex(
                db, request, principal, trace_id, rag_decision,
                progress_callback=progress_callback,
                cancellation_event=cancellation_event,
            )
        raise ValueError(f"unsupported route: {route}")

    def _knowledge(self, db, request, principal, trace_id, decision, *, cancellation_event=None) -> AnalysisResponse:
        settings = get_settings()
        shadow = None
        if decision.execute:
            try:
                result = self._rag(db, request, principal, trace_id, shadow=decision.shadow)
                if decision.publish and result.status == "SUCCEEDED":
                    primary = self._rag_primary(result)
                    self._audit_route(db, principal, QuestionRoute.KNOWLEDGE_QUERY, trace_id, "SUCCESS", False)
                    return self._response(QuestionRoute.KNOWLEDGE_QUERY, trace_id, primary, settings=settings)
                shadow = result.model_dump(mode="json")
            except RagAdapterError as exc:
                shadow = {"status": "FAILED", "error_code": "RAG_RUNTIME_FAILED", "error_type": type(exc).__name__}
        if not settings.rag_fallback_enabled:
            primary = {"status": "REFUSED", "error_code": "RAG_ROUTE_DISABLED"}
            self._audit_route(db, principal, QuestionRoute.KNOWLEDGE_QUERY, trace_id, "REFUSED", False)
            return self._response(QuestionRoute.KNOWLEDGE_QUERY, trace_id, primary, shadow=shadow, settings=settings)
        primary = self._data(db, request, principal, cancellation_event=cancellation_event)
        self._audit_route(db, principal, QuestionRoute.KNOWLEDGE_QUERY, trace_id, "FALLBACK", True)
        return self._response(
            QuestionRoute.KNOWLEDGE_QUERY, trace_id, primary, shadow=shadow, fallback=True, settings=settings
        )

    def _hybrid(self, db, request, principal, trace_id, decision, *, cancellation_event=None) -> AnalysisResponse:
        settings = get_settings()
        data = self._data(db, request, principal, cancellation_event=cancellation_event)
        if data.get("status") != "SUCCEEDED":
            self._audit_route(db, principal, QuestionRoute.HYBRID_ANALYSIS, trace_id, "DATA_FAILED", False)
            return self._response(QuestionRoute.HYBRID_ANALYSIS, trace_id, data, settings=settings)
        shadow = None
        if decision.execute:
            try:
                rag = self._rag(db, request, principal, trace_id, shadow=decision.shadow)
                if decision.publish and rag.status == "SUCCEEDED":
                    primary = {
                        "status": "SUCCEEDED",
                        "data": data,
                        "knowledge": self._rag_primary(rag),
                        "evidence_merge": "ORACLE_PASSED_AND_CITATIONS_VERIFIED",
                    }
                    self._audit_route(db, principal, QuestionRoute.HYBRID_ANALYSIS, trace_id, "SUCCESS", False)
                    return self._response(QuestionRoute.HYBRID_ANALYSIS, trace_id, primary, settings=settings)
                shadow = rag.model_dump(mode="json")
            except RagAdapterError as exc:
                shadow = {"status": "FAILED", "error_code": "RAG_RUNTIME_FAILED", "error_type": type(exc).__name__}
        self._audit_route(db, principal, QuestionRoute.HYBRID_ANALYSIS, trace_id, "FALLBACK", True)
        return self._response(
            QuestionRoute.HYBRID_ANALYSIS, trace_id, data, shadow=shadow, fallback=True, settings=settings
        )

    def _complex(
        self, db, request, principal, trace_id, rag_decision, *, progress_callback=None,
        cancellation_event=None,
    ) -> AnalysisResponse:
        settings = get_settings()
        context = self._agent_context(db, principal, trace_id)
        include_knowledge = rag_decision.publish and ToolName.RETRIEVE_KNOWLEDGE.value in context.allowed_tools
        idempotency_key = request.idempotency_key or f"analysis:{uuid4()}"
        existing = db.scalar(select(OrchestrationRun).where(
            OrchestrationRun.workspace_id == context.workspace_id,
            OrchestrationRun.idempotency_key == idempotency_key,
        ))
        if existing is not None and existing.result_payload:
            replay = OrchestrationResult.model_validate(existing.result_payload)
            return self._response(
                QuestionRoute.COMPLEX_ANALYSIS, trace_id, replay.model_dump(mode="json"), settings=settings
            )
        tool_executor = ChatBIToolExecutor(
            db, principal, self._rag_adapter_instance(), cancellation_event=cancellation_event,
        )
        result = BoundedAgentOrchestrator(
            tool_executor, progress_callback=progress_callback
        ).run(OrchestrationRequest(
            question=request.question,
            route=QuestionRoute.COMPLEX_ANALYSIS,
            context=context,
            datasource_id=request.datasource_id,
            semantic_model_id=request.semantic_model_id,
            include_knowledge=include_knowledge,
            idempotency_key=idempotency_key,
            prompt_versions=self._prompt_versions(db, context.workspace_id),
        ))
        self._record_orchestration(db, principal, request, result, idempotency_key)
        if result.status not in {"SUCCEEDED", "PARTIAL"} and settings.agent_fallback_enabled:
            try:
                fallback = self._data(db, request, principal, cancellation_event=cancellation_event)
            except (LookupError, ValueError):
                fallback = {
                    "status": "FAILED",
                    "error_code": "AGENT_FALLBACK_QUERY_FAILED",
                }
            self._audit_route(db, principal, QuestionRoute.COMPLEX_ANALYSIS, trace_id, "FALLBACK", True)
            return self._response(
                QuestionRoute.COMPLEX_ANALYSIS,
                trace_id,
                fallback,
                shadow=result.model_dump(mode="json"),
                fallback=True,
                settings=settings,
            )
        self._audit_route(db, principal, QuestionRoute.COMPLEX_ANALYSIS, trace_id, result.status, False)
        return self._response(
            QuestionRoute.COMPLEX_ANALYSIS, trace_id, result.model_dump(mode="json"), settings=settings
        )

    def _data(
        self, db: Session, request: AnalysisRequest, principal: Principal, *, cancellation_event=None,
    ) -> dict:
        run = QueryPipeline().execute(
            db,
            AskRequest(
                question=request.question,
                datasource_id=request.datasource_id,
                semantic_model_id=request.semantic_model_id,
                row_limit=request.row_limit,
            ),
            principal=principal,
            cancellation_event=cancellation_event,
            request_context=self._runtime_context,
        )
        return query_response(run).model_dump(mode="json")

    def _rag(self, db, request, principal, trace_id, *, shadow: bool) -> RagResult:
        context = self._rag_context(db, principal, trace_id)
        result = self._rag_adapter_instance().retrieve(RagRequest(
            query=request.question,
            scenario_id="charging_ops",
            context=context,
        ))
        verification = self.verifier.verify(request.question, result.citations)
        if result.status == "SUCCEEDED" and not verification.passed:
            result = result.model_copy(update={
                "status": "REFUSED",
                "refusal_reason": verification.reason or "CITATION_VERIFICATION_FAILED",
            })
        result = result.model_copy(update={"shadow": shadow})
        self._record_retrieval(db, principal, request.question, result, verification.passed)
        return result

    def _rag_adapter_instance(self):
        if self._rag_adapter is not None:
            return self._rag_adapter
        settings = get_settings()
        if not settings.legacy_rag_base_url:
            return UnavailableRagAdapter()
        return LiveRagAdapter(
            base_url=settings.legacy_rag_base_url,
            bearer_token=settings.legacy_rag_bearer_token.get_secret_value(),
            shared_secret=settings.rag_shared_secret.get_secret_value(),
            require_workspace_echo=settings.legacy_rag_require_workspace_echo,
            retry_count=settings.rag_retry_count,
        )

    @staticmethod
    def _allowed_resources(db: Session, principal: Principal) -> tuple[frozenset[str], frozenset[str]]:
        datasources = list(db.scalars(select(DataSource).where(DataSource.workspace_id == principal.workspace_id)))
        models = list(db.scalars(select(SemanticModel).where(SemanticModel.workspace_id == principal.workspace_id)))
        allowed_datasources = frozenset(
            item.id for item in datasources
            if has_resource_access(db, principal, resource_type="DATASOURCE", resource_id=item.id, query=True)
        )
        allowed_models = frozenset(
            item.id for item in models
            if has_resource_access(db, principal, resource_type="SEMANTIC_MODEL", resource_id=item.id, query=True)
        )
        return allowed_datasources, allowed_models

    def _rag_context(self, db: Session, principal: Principal, trace_id: str) -> RagExecutionContext:
        settings = get_settings()
        datasources, models = self._allowed_resources(db, principal)
        return RagExecutionContext(
            workspace_id=principal.workspace_id or default_workspace(db).id,
            user_id=principal.user_id or principal.email,
            roles=frozenset({principal.role}),
            allowed_datasources=datasources,
            allowed_semantic_models=models,
            allowed_tools=frozenset({ToolName.RETRIEVE_KNOWLEDGE.value}),
            trace_id=trace_id,
            timeout_ms=settings.agent_timeout_ms,
            max_steps=settings.agent_max_steps,
            token_budget=settings.agent_token_budget,
        )

    def _agent_context(self, db: Session, principal: Principal, trace_id: str) -> AgentExecutionContext:
        settings = get_settings()
        datasources, models = self._allowed_resources(db, principal)
        return AgentExecutionContext(
            workspace_id=principal.workspace_id or default_workspace(db).id,
            user_id=principal.user_id or principal.email,
            roles=frozenset({principal.role}),
            allowed_datasources=datasources,
            allowed_semantic_models=models,
            allowed_tools=frozenset(item.value for item in ToolName),
            trace_id=trace_id,
            timeout_ms=settings.agent_timeout_ms,
            max_steps=settings.agent_max_steps,
            max_tool_calls=settings.agent_max_tool_calls,
            max_replan=settings.agent_max_replan,
            max_agent_depth=settings.agent_max_depth,
            token_budget=settings.agent_token_budget,
        )

    @staticmethod
    def _prompt_versions(db: Session, workspace_id: str) -> dict[str, str]:
        rows = db.execute(
            select(PromptTemplate.code, PromptVersion.version, PromptVersion.checksum_sha256)
            .join(PromptVersion, PromptVersion.prompt_template_id == PromptTemplate.id)
            .where(
                PromptTemplate.workspace_id == workspace_id,
                PromptTemplate.status == "ACTIVE",
                PromptVersion.status == "ACTIVE",
            )
        ).all()
        return {
            code: f"v{version}:{checksum[:12]}"
            for code, version, checksum in rows
        }

    @staticmethod
    def _rag_primary(result: RagResult) -> dict:
        top = result.citations[0]
        return {
            "status": "SUCCEEDED",
            "summary": top.text[:600],
            "citations": [item.model_dump(mode="json") for item in result.citations],
            "retrieval_mode": result.retrieval_mode,
            "answer_guard": "PASSED",
        }

    @staticmethod
    def _record_retrieval(db, principal, query: str, result: RagResult, verified: bool) -> None:
        run = KnowledgeRetrievalRun(
            workspace_id=principal.workspace_id,
            user_id=principal.user_id,
            query_sha256=hashlib.sha256(query.encode("utf-8")).hexdigest(),
            status=result.status,
            retrieval_mode=result.retrieval_mode,
            trace_id=result.trace_id,
            citation_count=len(result.citations),
            details={"adapter": result.adapter, "verified": verified, "shadow": result.shadow},
        )
        db.add(run)
        db.flush()
        for item in result.citations:
            db.add(CitationRecord(
                retrieval_run_id=run.id,
                document_id=item.document_id or None,
                document_version_id=item.document_version_id or None,
                chunk_id=item.chunk_id or None,
                source=item.source,
                locator=item.locator,
                text_excerpt=item.text[:1000],
                score_millionths=round(item.score * 1_000_000),
            ))
        db.commit()

    @staticmethod
    def _record_orchestration(db, principal, request, result, idempotency_key) -> None:
        profile = db.scalar(select(OrchestrationProfile).where(
            OrchestrationProfile.workspace_id == principal.workspace_id,
            OrchestrationProfile.code == "chatbi-v1-complex-analysis",
        ))
        performance = result.performance
        run = OrchestrationRun(
            id=result.run_id.removeprefix("ORCH-")[:36],
            workspace_id=principal.workspace_id,
            profile_id=profile.id if profile else None,
            user_id=principal.user_id,
            route=result.route.value,
            status=result.status,
            trace_id=result.trace_id,
            idempotency_key=idempotency_key,
            request_payload={"question_sha256": hashlib.sha256(request.question.encode()).hexdigest()},
            result_payload=result.model_dump(mode="json"),
            error_code=result.error_code,
            ttft_ms=performance.get("ttft_ms", 0),
            total_latency_ms=performance.get("total_latency_ms", 0),
            tool_latency_ms=performance.get("tool_latency_ms", 0),
            trace_complete=result.trace_complete,
            finished_at=_now(),
        )
        db.add(run)
        db.flush()
        for step in result.steps:
            record = OrchestrationStep(
                orchestration_run_id=run.id,
                ordinal=step.ordinal,
                code=step.code,
                tool_name=step.tool_name,
                status=step.status,
                details={**step.detail, "agent_role": step.agent_role.value},
                duration_ms=step.duration_ms,
            )
            db.add(record)
            db.flush()
            if step.tool_name:
                db.add(ToolCall(
                    orchestration_run_id=run.id,
                    orchestration_step_id=record.id,
                    tool_name=step.tool_name,
                    idempotency_key=f"{idempotency_key}:{step.ordinal}",
                    status=step.status,
                    request_payload={"question_sha256": hashlib.sha256(request.question.encode()).hexdigest()},
                    response_payload=step.detail,
                    error_code=step.detail.get("error_code"),
                    duration_ms=step.duration_ms,
                ))
        db.commit()

    @staticmethod
    def _audit_route(db, principal, route, trace_id, status, fallback) -> None:
        record_audit(
            db,
            principal,
            action="ANALYSIS_ROUTE",
            resource_type="ANALYSIS",
            resource_id=trace_id,
            status=status,
            details={"route": route.value, "fallback_used": fallback},
        )
        db.commit()

    @staticmethod
    def _response(route, trace_id, primary, *, shadow=None, fallback=False, settings) -> AnalysisResponse:
        return AnalysisResponse(
            status=str(primary.get("status") or "FAILED"),
            route=route,
            trace_id=trace_id,
            primary=primary,
            shadow=shadow,
            fallback_used=fallback,
            feature_modes={"rag": settings.rag_mode, "agent": settings.agent_mode},
            security={
                "AGENT_DIRECT_DB_ACCESS": 0,
                "AGENT_SQL_GUARD_BYPASS": 0,
                "AGENT_RESULT_ORACLE_BYPASS": 0,
                "UNAUTHORIZED_TOOL_CALL": 0,
                "CROSS_WORKSPACE_LEAK": 0,
            },
        )
