from __future__ import annotations

from chatbi_agent_contracts import AgentExecutionContext, ToolCall, ToolResult
from chatbi_rag_adapter import CitationVerifierV1, RagAdapterError
from chatbi_rag_contracts import RagExecutionContext, RagRequest
from sqlalchemy.orm import Session

from app.core.access import Principal
from app.query.contracts import AskRequest
from app.query.service import QueryPipeline, query_response


class ChatBIToolExecutor:
    """The only Agent tool bridge; it intentionally exposes no connector or DB URL."""

    def __init__(self, db: Session, principal: Principal, rag_adapter) -> None:
        self.db = db
        self.principal = principal
        self.rag_adapter = rag_adapter
        self.citation_verifier = CitationVerifierV1()
        self.direct_db_access = False

    def execute(self, call: ToolCall, context: AgentExecutionContext) -> ToolResult:
        if call.tool_name not in context.allowed_tools:
            return ToolResult(tool_name=call.tool_name, status="REFUSED", error_code="UNAUTHORIZED_TOOL_CALL")
        if call.tool_name == "data.query":
            return self._data_query(call, context)
        if call.tool_name == "knowledge.retrieve":
            return self._knowledge_query(call, context)
        return ToolResult(tool_name=call.tool_name, status="REFUSED", error_code="UNAUTHORIZED_TOOL_CALL")

    def _data_query(self, call: ToolCall, context: AgentExecutionContext) -> ToolResult:
        datasource_id = call.arguments.get("datasource_id")
        semantic_model_id = call.arguments.get("semantic_model_id")
        if datasource_id and datasource_id not in context.allowed_datasources:
            return ToolResult(tool_name=call.tool_name, status="REFUSED", error_code="DATASOURCE_SCOPE_DENIED")
        if semantic_model_id and semantic_model_id not in context.allowed_semantic_models:
            return ToolResult(tool_name=call.tool_name, status="REFUSED", error_code="SEMANTIC_MODEL_SCOPE_DENIED")
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
        if run.status != "SUCCEEDED" or not guard_allowed or not oracle_passed:
            return ToolResult(
                tool_name=call.tool_name,
                status="FAILED" if run.status != "SECURITY_REJECTED" else "REFUSED",
                output={"query_id": run.id, "status": run.status},
                error_code=run.error_code or "RESULT_ORACLE_NOT_PASSED",
            )
        return ToolResult(tool_name=call.tool_name, status="SUCCEEDED", output=payload)

    def _knowledge_query(self, call: ToolCall, context: AgentExecutionContext) -> ToolResult:
        try:
            result = self.rag_adapter.retrieve(RagRequest(
                query=str(call.arguments.get("question") or ""),
                scenario_id=str(call.arguments.get("scenario_id") or "charging_ops"),
                context=RagExecutionContext(**context.model_dump()),
            ))
        except RagAdapterError:
            return ToolResult(tool_name=call.tool_name, status="FAILED", error_code="RAG_RUNTIME_FAILED")
        verification = self.citation_verifier.verify(str(call.arguments.get("question") or ""), result.citations)
        if result.status != "SUCCEEDED" or not verification.passed:
            return ToolResult(
                tool_name=call.tool_name,
                status="REFUSED" if result.status == "REFUSED" else "FAILED",
                error_code=result.refusal_reason or verification.reason or "CITATION_VERIFICATION_FAILED",
            )
        return ToolResult(tool_name=call.tool_name, status="SUCCEEDED", output=result.model_dump(mode="json"))
