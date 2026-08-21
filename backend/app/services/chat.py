from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from time import perf_counter
from threading import Event
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from chatbi_agent_contracts import QuestionRoute
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access import Principal, record_audit
from app.core.config import get_settings
from app.integration.contracts import AnalysisRequest
from app.model_gateway import BudgetMode, ModelGateway, ModelUnavailable, RequestContext, VisionModelUnavailable
from app.integration.question_router import QuestionRouter, is_local_date_question
from app.integration.service import AnalysisService
from app.models import Attachment, ChatMessage, Conversation
from app.schemas.chat import ChatRequest, ChatResponse, ConversationRead, MessageRead
from app.services.answer_composer import AnswerComposer
from app.services.attachments import attachment_path, get_attachment
from app.services.conversations import (
    extract_slots,
    get_conversation,
    list_messages,
    merge_runtime_context,
    refresh_conversation_summary,
)
from app.services.file_analysis import analyze_structured
from app.streaming import phase_for_stage
from app.streaming.lifecycle import StreamCancelled, stream_registry


def _message(item: ChatMessage) -> MessageRead:
    return MessageRead.model_validate(item)


def _conversation(item: Conversation) -> ConversationRead:
    return ConversationRead.model_validate(item)


def _history(messages: list[ChatMessage]) -> list[dict[str, str]]:
    limit = get_settings().chat_recent_message_limit
    return [
        {"role": item.role, "content": item.content[:2_000]}
        for item in messages[-limit:]
        if item.role in {"user", "assistant"} and item.content.strip()
    ]


def _analysis_answer(route: QuestionRoute, primary: dict) -> str:
    if route == QuestionRoute.DATA_QUERY:
        return str(primary.get("summary") or primary.get("error_message") or "数据查询未返回可发布结论。")
    if route == QuestionRoute.KNOWLEDGE_QUERY:
        return str(primary.get("summary") or primary.get("error_code") or "没有找到可引用的授权知识证据。")
    if route == QuestionRoute.HYBRID_ANALYSIS:
        data = primary.get("data") if isinstance(primary.get("data"), dict) else primary
        knowledge = primary.get("knowledge") if isinstance(primary.get("knowledge"), dict) else {}
        parts = [str(data.get("summary") or "数据部分未形成可发布结论。")]
        if knowledge.get("summary"):
            parts.append(f"知识依据：{knowledge['summary']}")
        return "\n\n".join(parts)
    return str(primary.get("answer") or primary.get("summary") or primary.get("error_code") or "复杂分析未形成可发布结论。")


def _comparative_answer(question: str, answer: str, primary: dict) -> str:
    if not re.search(r"两者|相差|差距|最大", question):
        return answer
    rows = ((primary.get("execution") or {}).get("rows") or []) if isinstance(primary, dict) else []
    if len(rows) == 2 and "region" in rows[0]:
        metric = next((key for key in ("revenue", "profit", "cost", "order_count") if key in rows[0]), None)
        if metric:
            left, right = rows
            difference = abs(float(left[metric] or 0) - float(right[metric] or 0))
            return f"{left['region']}与{right['region']}的{metric}相差 {difference:,.2f}。"
    return answer


class ChatService:
    def __init__(self, gateway: ModelGateway | None = None):
        self.gateway = gateway or ModelGateway()
        self.router = QuestionRouter(self.gateway)
        self.composer = AnswerComposer()

    def execute(
        self,
        db: Session,
        request: ChatRequest,
        principal: Principal,
        progress: Callable[[str, dict], None] | None = None,
        cancellation_event: Event | None = None,
        answer_delta: Callable[[str], None] | None = None,
        trace_id: str | None = None,
    ) -> ChatResponse:
        started = perf_counter()
        public_phases: list[str] = []

        def checkpoint() -> None:
            if cancellation_event is not None and cancellation_event.is_set():
                raise StreamCancelled("chat run cancelled")

        def report(stage: str, detail: dict | None = None) -> None:
            checkpoint()
            phase = phase_for_stage(stage)
            if phase and phase not in public_phases:
                public_phases.append(phase)
            if progress:
                progress(stage, detail or {})

        conversation = get_conversation(db, request.conversation_id, principal)
        duplicate = db.scalar(select(ChatMessage).where(
            ChatMessage.conversation_id == conversation.id,
            ChatMessage.client_message_id == request.client_message_id,
        ))
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="DUPLICATE_MESSAGE")
        if request.parent_message_id:
            parent = db.get(ChatMessage, request.parent_message_id)
            if parent is None or parent.conversation_id != conversation.id:
                raise HTTPException(status_code=422, detail="Invalid parent message")

        attachments: list[Attachment] = []
        attachment_ids = list(dict.fromkeys(request.attachment_ids or conversation.active_attachment_ids))
        for attachment_id in attachment_ids:
            item = get_attachment(db, attachment_id, principal)
            if item.conversation_id != conversation.id:
                raise HTTPException(status_code=403, detail="Attachment belongs to another conversation")
            if item.status != "READY":
                raise HTTPException(status_code=422, detail=item.error_code or "ATTACHMENT_NOT_READY")
            attachments.append(item)

        prior_messages = list_messages(db, conversation.id)
        content = request.content.strip() or "请分析当前附件。"
        slots, resolved_question = extract_slots(content, conversation.slot_state)
        if request.datasource_id:
            slots["datasource"] = request.datasource_id
        if request.semantic_model_id:
            slots["semantic_model"] = request.semantic_model_id
        trace_id = trace_id or f"TRACE-{uuid4()}"
        permission_hash = hashlib.sha256(
            f"{principal.workspace_id}:{principal.user_id}:{principal.role}".encode("utf-8")
        ).hexdigest()
        request_context = RequestContext(
            request_id=request.client_message_id,
            trace_id=trace_id,
            conversation_id=conversation.id,
            user_id=principal.user_id or principal.email,
            workspace_id=principal.workspace_id or conversation.workspace_id,
            datasource_id=request.datasource_id,
            roles=frozenset({principal.role}),
            permission_hash=permission_hash,
            question=resolved_question,
            attachment_ids=tuple(item.id for item in attachments),
            context_hash=hashlib.sha256(
                f"{conversation.id}:{conversation.summary}:{slots}".encode("utf-8")
            ).hexdigest(),
            budget_mode=BudgetMode(get_settings().model_budget_mode),
        )
        router_decision = self.router.decide(
            resolved_question,
            request.route,
            history_summary=conversation.summary,
            attachment_kinds={item.kind for item in attachments},
            context=request_context,
        )
        route = router_decision.route
        report("UNDERSTANDING", {"route": route.value})
        if route in {QuestionRoute.DATA_QUERY, QuestionRoute.HYBRID_ANALYSIS, QuestionRoute.COMPLEX_ANALYSIS}:
            report("SCHEMA_LINKED", {"route": route.value})
            report("SEMANTIC_PARSING", {"route": route.value})
            report("SEMANTIC_COMPILING", {"route": route.value})
            report("SQL_VALIDATING", {"route": route.value})

        user_message = ChatMessage(
            conversation_id=conversation.id,
            workspace_id=principal.workspace_id,
            user_id=principal.user_id,
            parent_message_id=request.parent_message_id,
            client_message_id=request.client_message_id,
            role="user",
            content=content,
            route=route.value,
            attachment_ids=[item.id for item in attachments],
            context_payload={
                "resolved_question": resolved_question,
                "slots": slots,
                "request_context": request_context.model_dump(mode="json", exclude={"question"}),
                "router_decision": router_decision.model_dump(mode="json"),
            },
            status="COMPLETED",
        )
        db.add(user_message)
        db.flush()

        status = "SUCCEEDED"
        error_code = None
        response_payload: dict = {}
        model_provider = None
        model_name = None
        model_trace: dict = {}
        query_run_id = None
        retrieved_sources: list[dict] = []
        tool_calls: list[dict] = []
        sql_execution: dict = {}
        fallback_reason = None
        answer_streamed = False
        try:
            if route in {
                QuestionRoute.DATA_QUERY,
                QuestionRoute.KNOWLEDGE_QUERY,
                QuestionRoute.HYBRID_ANALYSIS,
                QuestionRoute.COMPLEX_ANALYSIS,
            }:
                report("QUERYING_DATA" if route == QuestionRoute.DATA_QUERY else "RETRIEVING_KNOWLEDGE", {})
                workload = "agent" if route == QuestionRoute.COMPLEX_ANALYSIS else None
                with stream_registry.workload(workload):
                    result = AnalysisService().execute(
                        db,
                        AnalysisRequest(
                            question=resolved_question,
                            route=route,
                            datasource_id=request.datasource_id,
                            semantic_model_id=request.semantic_model_id,
                            idempotency_key=request.client_message_id,
                        ),
                        principal,
                        progress_callback=(lambda stage, detail: report(stage.value, detail)),
                        cancellation_event=cancellation_event,
                        request_context=request_context,
                    )
                response_payload = {"analysis": result.model_dump(mode="json")}
                status = result.status
                primary = result.primary
                answer = _comparative_answer(resolved_question, _analysis_answer(route, primary), primary)
                data_payload = primary.get("data", primary) if isinstance(primary, dict) else {}
                query_run_id = data_payload.get("id") if isinstance(data_payload, dict) else None
                model_provider = data_payload.get("provider") if isinstance(data_payload, dict) else None
                model_trace = ((data_payload.get("plan") or {}).get("model_trace") or {}) if isinstance(data_payload, dict) else {}
                model_name = model_trace.get("resolved_model")
                sql_execution = data_payload.get("execution", {}) if isinstance(data_payload, dict) else {}
                knowledge = primary.get("knowledge", primary) if isinstance(primary, dict) else {}
                retrieved_sources = knowledge.get("citations", []) if isinstance(knowledge, dict) else []
                tool_calls = primary.get("steps", []) if isinstance(primary, dict) else []
                fallback_reason = "CONTROLLED_RUNTIME_FALLBACK" if result.fallback_used else None
                report("RESULT_VALIDATING", {"route": route.value, "status": status})
                if status not in {"SUCCEEDED", "PARTIAL"}:
                    error_code = str(primary.get("error_code") or status)
            elif route == QuestionRoute.GENERAL_CHAT:
                report("GENERATING_INSIGHT", {"route": route.value})
                if router_decision.reason == "DATE_TIME_L0" and is_local_date_question(resolved_question):
                    local_now = datetime.now(ZoneInfo(request_context.timezone))
                    weekdays = "一二三四五六日"
                    answer = f"当前日期是{local_now:%Y年%m月%d日}，星期{weekdays[local_now.weekday()]}。"
                    model_provider, model_name = "none", "none"
                else:
                    answer, model_provider, model_name, answer_streamed, model_trace = self._model_answer(
                        system=(
                            "You are ChatBI Studio. Answer ordinary product or conversational questions concisely. "
                            "Never invent company data or internal policy. Direct business-data requests back to verified ChatBI analysis."
                        ),
                        user=content,
                        history=_history(prior_messages),
                        answer_delta=answer_delta,
                        cancellation_event=cancellation_event,
                        request_context=request_context,
                        complexity_score=router_decision.complexity_score,
                    )
                response_payload = {"answer": answer}
            elif route == QuestionRoute.FILE_QUERY:
                with stream_registry.workload("sandbox"):
                    answer, model_provider, model_name, retrieved_sources, file_analysis, answer_streamed, model_trace = self._file_answer(
                        content, attachments, prior_messages, answer_delta=answer_delta,
                        cancellation_event=cancellation_event,
                        request_context=request_context,
                        complexity_score=router_decision.complexity_score,
                    )
                response_payload = {"answer": answer, "citations": retrieved_sources, "file_analysis": file_analysis}
            elif route == QuestionRoute.MULTIMODAL_QUERY:
                answer, model_provider, model_name, answer_streamed, model_trace = self._vision_answer(
                    content, attachments, prior_messages, answer_delta=answer_delta,
                    cancellation_event=cancellation_event,
                    request_context=request_context,
                    complexity_score=router_decision.complexity_score,
                )
                response_payload = {"answer": answer}
            elif route == QuestionRoute.CLARIFICATION:
                answer = "请补充要分析的指标、时间范围、区域或数据源。例如：今年华东区销售额是多少？"
                response_payload = {"answer": answer, "required_slots": ["metric", "time", "region_or_datasource"]}
            else:
                status, error_code = "REFUSED", "UNSUPPORTED"
                answer = "该请求不在只读 ChatBI 分析范围内，或当前账号没有执行权限。"
                response_payload = {"answer": answer}
        except VisionModelUnavailable:
            status, error_code, answer = "FAILED", "VISION_MODEL_UNAVAILABLE", "当前没有可用的图片理解模型，请配置受支持的多模态模型后重试。"
            response_payload = {"answer": answer}
        except ModelUnavailable:
            status, error_code, answer = "FAILED", "MODEL_UNAVAILABLE", "当前没有可用的外部模型，无法生成真实模型回答。"
            response_payload = {"answer": answer}

        report("GENERATING_INSIGHT", {"route": route.value})
        composed = self.composer.compose(
            answer=answer,
            status=status,
            response_payload=response_payload,
            error_code=error_code,
            phases=public_phases,
        )
        if status in {"SUCCEEDED", "PARTIAL"} and answer_delta and not answer_streamed:
            for delta in composed.deltas():
                checkpoint()
                answer_delta(delta)
        checkpoint()
        answer = composed.content
        response_payload = {
            **response_payload,
            "message_parts": composed.message_parts,
            "result_semantic": composed.result_semantic.value,
        }

        elapsed_ms = round((perf_counter() - started) * 1000)
        trace = {
            "trace_id": trace_id,
            "request_id": request.client_message_id,
            "conversation_id": conversation.id,
            "message_id": user_message.id,
            "workspace_id": principal.workspace_id,
            "user_id": principal.user_id,
            "route": route.value,
            "model_provider": model_provider,
            "model_name": model_name,
            "model_call": model_trace,
            "router_decision": router_decision.model_dump(mode="json"),
            "request_cache_key": request_context.cache_key("chat-response"),
            "prompt_version": "v1.3-runtime-control-plane-v1",
            "semantic_model_version": (response_payload.get("analysis", {}).get("primary", {}) or {}).get("semantic_model_version"),
            "retrieved_sources": retrieved_sources,
            "tool_calls": tool_calls,
            "sql_execution": sql_execution,
            "fallback_reason": fallback_reason,
            "file_analysis": response_payload.get("file_analysis"),
            "elapsed_ms": elapsed_ms,
        }
        assistant = ChatMessage(
            conversation_id=conversation.id,
            workspace_id=principal.workspace_id,
            user_id=principal.user_id,
            parent_message_id=user_message.id,
            role="assistant",
            content=answer,
            route=route.value,
            status=status,
            attachment_ids=[item.id for item in attachments],
            response_payload=response_payload,
            trace_payload=trace,
            query_run_id=query_run_id,
            error_code=error_code,
        )
        db.add(assistant)
        conversation.active_attachment_ids = [item.id for item in attachments]
        slots = merge_runtime_context(
            slots,
            datasource_id=request.datasource_id,
            semantic_model_id=request.semantic_model_id,
            response_payload=response_payload,
            retrieved_sources=retrieved_sources,
            attachments=attachments,
        )
        user_message.context_payload = {
            "resolved_question": resolved_question,
            "slots": slots,
            "request_context": request_context.model_dump(mode="json", exclude={"question"}),
            "router_decision": router_decision.model_dump(mode="json"),
        }
        refresh_conversation_summary(conversation, content, slots)
        record_audit(
            db,
            principal,
            action="CHAT_MESSAGE",
            resource_type="CONVERSATION",
            resource_id=conversation.id,
            status="SUCCESS" if status in {"SUCCEEDED", "PARTIAL"} else status,
            details={"route": route.value, "error_code": error_code, "elapsed_ms": elapsed_ms},
        )
        db.commit()
        db.refresh(user_message)
        db.refresh(assistant)
        db.refresh(conversation)
        if progress:
            progress("COMPLETED", {"status": status, "elapsed_ms": elapsed_ms})
        return ChatResponse(
            conversation=_conversation(conversation),
            user_message=_message(user_message),
            assistant_message=_message(assistant),
            message_parts=composed.message_parts,
            result_semantic=composed.result_semantic,
        )

    def _model_answer(
        self,
        *,
        system: str,
        user: str,
        history: list[dict[str, str]] | None = None,
        image_data_urls: list[str] | None = None,
        vision: bool = False,
        answer_delta: Callable[[str], None] | None = None,
        cancellation_event: Event | None = None,
        request_context: RequestContext | None = None,
        complexity_score: int = 25,
    ) -> tuple[str, str, str, bool, dict]:
        stream = getattr(self.gateway, "stream", None)
        if answer_delta is not None and callable(stream):
            chunks: list[str] = []
            provider = model = ""
            for reply in stream(
                system=system,
                user=user,
                history=history,
                image_data_urls=image_data_urls,
                vision=vision,
                context=request_context,
                complexity_score=complexity_score,
                cancellation_event=cancellation_event,
            ):
                if cancellation_event is not None and cancellation_event.is_set():
                    raise StreamCancelled("chat run cancelled")
                if reply.content:
                    chunks.append(reply.content)
                    provider, model = reply.provider, reply.model
                    answer_delta(reply.content)
            if not chunks:
                raise VisionModelUnavailable("Vision model returned no content") if vision else ModelUnavailable("Model returned no content")
            final_response = getattr(self.gateway, "last_response", None)
            model_trace = final_response.trace_payload() if final_response is not None else {}
            return "".join(chunks), provider, model, True, model_trace
        reply = self.gateway.complete(
            system=system,
            user=user,
            history=history,
            image_data_urls=image_data_urls,
            vision=vision,
            context=request_context,
            complexity_score=complexity_score,
            cancellation_event=cancellation_event,
        )
        return reply.content, reply.provider, reply.model, False, (reply.trace or {})

    def _file_answer(
        self, question: str, attachments: list[Attachment], messages: list[ChatMessage], *,
        answer_delta: Callable[[str], None] | None = None,
        cancellation_event: Event | None = None,
        request_context: RequestContext | None = None,
        complexity_score: int = 25,
    ):
        if not attachments:
            raise HTTPException(status_code=422, detail="FILE_QUERY_REQUIRES_ATTACHMENT")
        sources = [{"attachment_id": item.id, "filename": item.filename, "kind": item.kind} for item in attachments]
        if attachments and all(item.kind == "STRUCTURED" for item in attachments):
            analysis = analyze_structured(question, attachments)
            return analysis["answer"], "chatbi-safe-dataframe", "fixed-operation-v1", sources, analysis, False, {}
        context = []
        for item in attachments:
            payload = item.extracted_payload or {}
            if item.kind == "STRUCTURED":
                context.append({"attachment_id": item.id, "filename": item.filename, **payload})
            elif item.kind == "DOCUMENT":
                context.append({"attachment_id": item.id, "filename": item.filename, "text": str(payload.get("text", ""))[:60_000]})
        answer, provider, model, streamed, model_trace = self._model_answer(
            system=(
                "Answer only from the supplied temporary attachment evidence. For tabular files, calculate only from provided profile/preview and state limits. "
                "For documents, cite claims as [attachment:<id>]. If evidence is absent, say so; never use general knowledge as company evidence."
            ),
            user=json.dumps({"question": question, "attachments": context}, ensure_ascii=False),
            history=_history(messages),
            answer_delta=answer_delta,
            cancellation_event=cancellation_event,
            request_context=request_context,
            complexity_score=complexity_score,
        )
        return answer, provider, model, sources, None, streamed, model_trace

    def _vision_answer(
        self, question: str, attachments: list[Attachment], messages: list[ChatMessage], *,
        answer_delta: Callable[[str], None] | None = None,
        cancellation_event: Event | None = None,
        request_context: RequestContext | None = None,
        complexity_score: int = 25,
    ):
        images = [item for item in attachments if item.kind == "IMAGE"]
        if not images:
            raise HTTPException(status_code=422, detail="MULTIMODAL_QUERY_REQUIRES_IMAGE")
        data_urls = [
            f"data:{item.mime_type};base64,{base64.b64encode(attachment_path(item).read_bytes()).decode('ascii')}"
            for item in images
        ]
        answer, provider, model, streamed, model_trace = self._model_answer(
            system=(
                "Analyze the supplied images for the user's ChatBI question. Describe only visible evidence. "
                "Do not infer confidential business facts that are not visible."
            ),
            user=question,
            history=_history(messages),
            image_data_urls=data_urls,
            vision=True,
            answer_delta=answer_delta,
            cancellation_event=cancellation_event,
            request_context=request_context,
            complexity_score=complexity_score,
        )
        return answer, provider, model, streamed, model_trace
