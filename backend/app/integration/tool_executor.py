from __future__ import annotations

from time import perf_counter

from chatbi_agent_contracts import (
    AgentExecutionContext,
    AgentRole,
    ToolCall,
    ToolName,
    ToolResult,
)
from chatbi_rag_adapter import CitationVerifierV1, RagAdapterError
from chatbi_rag_contracts import Citation, RagExecutionContext, RagRequest
from sqlalchemy.orm import Session

from app.core.access import Principal
from app.query.contracts import AskRequest
from app.query.service import QueryPipeline, query_response


ROLE_TOOLS: dict[AgentRole, frozenset[ToolName]] = {
    AgentRole.DATA_ANALYST: frozenset({ToolName.QUERY_DATA}),
    AgentRole.KNOWLEDGE: frozenset({ToolName.RETRIEVE_KNOWLEDGE}),
    AgentRole.VERIFICATION: frozenset(
        {ToolName.VERIFY_RESULT, ToolName.VERIFY_CITATION}
    ),
    AgentRole.INSIGHT: frozenset(
        {ToolName.GENERATE_CHART, ToolName.GENERATE_INSIGHT}
    ),
}


class ChatBIToolExecutor:
    """The sole six-tool bridge; it exposes no connector, URL, SQL or file tool."""

    tool_catalogue = frozenset(ToolName)
    direct_db_access = False
    dynamic_tool_loading = False
    file_access = False
    network_access = False

    def __init__(self, db: Session, principal: Principal, rag_adapter) -> None:
        self.db = db
        self.principal = principal
        self.rag_adapter = rag_adapter
        self.citation_verifier = CitationVerifierV1()

    def execute(self, call: ToolCall, context: AgentExecutionContext) -> ToolResult:
        started = perf_counter()
        try:
            tool = ToolName(call.tool_name)
        except ValueError:
            return self._result(call.tool_name, started, "REFUSED", "UNAUTHORIZED_TOOL_CALL")
        if tool.value not in context.allowed_tools:
            return self._result(call.tool_name, started, "REFUSED", "UNAUTHORIZED_TOOL_CALL")
        if tool not in ROLE_TOOLS.get(call.agent_role, frozenset()):
            return self._result(call.tool_name, started, "REFUSED", "AGENT_ROLE_TOOL_DENIED")
        handlers = {
            ToolName.QUERY_DATA: self._query_data,
            ToolName.RETRIEVE_KNOWLEDGE: self._retrieve_knowledge,
            ToolName.VERIFY_RESULT: self._verify_result,
            ToolName.VERIFY_CITATION: self._verify_citation,
            ToolName.GENERATE_CHART: self._generate_chart,
            ToolName.GENERATE_INSIGHT: self._generate_insight,
        }
        try:
            status, output, error_code = handlers[tool](call, context)
        except Exception as exc:  # fail closed and never expose exception text
            return self._result(
                call.tool_name,
                started,
                "FAILED",
                f"TOOL_RUNTIME_{type(exc).__name__.upper()}",
            )
        return self._result(call.tool_name, started, status, error_code, output)

    def _query_data(self, call: ToolCall, context: AgentExecutionContext):
        datasource_id = call.arguments.get("datasource_id")
        semantic_model_id = call.arguments.get("semantic_model_id")
        if datasource_id and datasource_id not in context.allowed_datasources:
            return "REFUSED", {}, "DATASOURCE_SCOPE_DENIED"
        if semantic_model_id and semantic_model_id not in context.allowed_semantic_models:
            return "REFUSED", {}, "SEMANTIC_MODEL_SCOPE_DENIED"
        run = QueryPipeline().execute(
            self.db,
            AskRequest(
                question=str(call.arguments.get("question") or ""),
                datasource_id=datasource_id,
                semantic_model_id=semantic_model_id,
            ),
            principal=self.principal,
        )
        payload = query_response(run).model_dump(mode="json")
        guard_allowed = bool((payload.get("guard") or {}).get("allowed"))
        oracle_passed = (payload.get("oracle") or {}).get("status") == "PASSED"
        signature = (payload.get("execution") or {}).get("result_signature")
        if run.status != "SUCCEEDED" or not guard_allowed or not oracle_passed or not signature:
            status = "REFUSED" if run.status == "SECURITY_REJECTED" else "FAILED"
            return status, {"query_id": run.id, "status": run.status}, (
                run.error_code or "RESULT_ORACLE_NOT_PASSED"
            )
        return "SUCCEEDED", payload, None

    def _retrieve_knowledge(self, call: ToolCall, context: AgentExecutionContext):
        if self.rag_adapter is None:
            return "FAILED", {}, "RAG_RUNTIME_UNAVAILABLE"
        try:
            result = self.rag_adapter.retrieve(
                RagRequest(
                    query=str(call.arguments.get("question") or ""),
                    scenario_id="charging_ops",
                    context=RagExecutionContext(
                        workspace_id=context.workspace_id,
                        user_id=context.user_id,
                        roles=context.roles,
                        allowed_datasources=context.allowed_datasources,
                        allowed_semantic_models=context.allowed_semantic_models,
                        allowed_tools=frozenset({ToolName.RETRIEVE_KNOWLEDGE.value}),
                        trace_id=context.trace_id,
                        timeout_ms=context.timeout_ms,
                        max_steps=context.max_steps,
                        token_budget=context.token_budget,
                    ),
                )
            )
        except RagAdapterError:
            return "FAILED", {}, "RAG_RUNTIME_FAILED"
        if result.status != "SUCCEEDED":
            return (
                "REFUSED" if result.status == "REFUSED" else "FAILED",
                {},
                result.refusal_reason or "RAG_RUNTIME_FAILED",
            )
        return "SUCCEEDED", result.model_dump(mode="json"), None

    @staticmethod
    def _verify_result(call: ToolCall, _context: AgentExecutionContext):
        evidence = call.arguments.get("data_evidence") or {}
        verified = bool(
            evidence.get("status") == "SUCCEEDED"
            and (evidence.get("guard") or {}).get("allowed") is True
            and (evidence.get("oracle") or {}).get("status") == "PASSED"
            and (evidence.get("execution") or {}).get("result_signature")
        )
        return (
            "SUCCEEDED" if verified else "REFUSED",
            {
                "verified": verified,
                "query_id": evidence.get("id"),
                "result_signature": (evidence.get("execution") or {}).get("result_signature"),
            },
            None if verified else "RESULT_VERIFICATION_FAILED",
        )

    def _verify_citation(self, call: ToolCall, _context: AgentExecutionContext):
        evidence = call.arguments.get("knowledge_evidence") or {}
        try:
            citations = tuple(Citation.model_validate(item) for item in evidence.get("citations", []))
        except Exception:
            return "REFUSED", {"verified": False}, "INVALID_CITATION_PAYLOAD"
        verification = self.citation_verifier.verify(
            str(call.arguments.get("question") or ""), citations
        )
        return (
            "SUCCEEDED" if verification.passed else "REFUSED",
            {
                "verified": verification.passed,
                "verified_ids": list(verification.verified_ids),
            },
            verification.reason,
        )

    @staticmethod
    def _generate_chart(call: ToolCall, _context: AgentExecutionContext):
        evidence = call.arguments.get("data_evidence") or {}
        signature = (evidence.get("execution") or {}).get("result_signature")
        chart = evidence.get("chart_spec") or {}
        bound = bool(
            signature
            and chart.get("result_signature") == signature
            and chart.get("data_source_query_id") == evidence.get("id")
        )
        return (
            "SUCCEEDED" if bound else "REFUSED",
            {"verified": bound, "chart_spec": chart if bound else {}},
            None if bound else "CHART_EVIDENCE_BINDING_FAILED",
        )

    @staticmethod
    def _generate_insight(call: ToolCall, _context: AgentExecutionContext):
        if not call.arguments.get("result_verified"):
            return "REFUSED", {}, "UNVERIFIED_DATA_EVIDENCE"
        data = call.arguments.get("data_evidence") or {}
        knowledge = call.arguments.get("knowledge_evidence") or {}
        conclusion = str(data.get("summary") or "查询已完成并通过结果校验。").strip()
        citations = knowledge.get("citations") or []
        if citations and call.arguments.get("citation_verified"):
            titles = list(dict.fromkeys(str(item.get("title")) for item in citations if item.get("title")))
            if titles:
                conclusion += f" 相关业务口径已由《{'》《'.join(titles[:3])}》验证。"
        return (
            "SUCCEEDED",
            {
                "answer": conclusion,
                "query_id": data.get("id"),
                "result_signature": (data.get("execution") or {}).get("result_signature"),
                "citation_count": len(citations) if call.arguments.get("citation_verified") else 0,
            },
            None,
        )

    @staticmethod
    def _result(
        tool_name: str,
        started: float,
        status: str,
        error_code: str | None,
        output: dict | None = None,
    ) -> ToolResult:
        return ToolResult(
            tool_name=tool_name,
            status=status,
            output=output or {},
            error_code=error_code,
            duration_ms=max(0, int((perf_counter() - started) * 1000)),
        )
