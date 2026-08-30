from __future__ import annotations

import json
from threading import Event, Thread

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import app.api.routes.chat as chat_route
import app.api.routes.analysis as analysis_route
import app.services.chat as chat_service_module
from chatbi_agent_contracts import ProgressStage, QuestionRoute
from app.core.access import Principal
from app.core.config import Settings
from app.integration.model_gateway import ModelGateway, ModelReply
from app.integration.contracts import AnalysisResponse
from app.main import app
from app.model_gateway.contracts import ModelCapability, ModelRequest, ModelResponse
from app.model_gateway.ledger import record_model_invocation
from app.models import AppUser, ChatMessage, Conversation, ModelInvocation, Workspace
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat import ChatService
from app.services.conversations import refresh_conversation_summary
from app.services.answer_presentation import AnswerPresentation
from app.streaming import REQUIRED_EVENTS, StreamCancelled, stream_registry


def _events(response_text: str) -> list[dict]:
    events = []
    for block in response_text.split("\n\n"):
        if not block.strip():
            continue
        lines = block.splitlines()
        event_name = next(line[7:] for line in lines if line.startswith("event: "))
        payload = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))
        assert event_name == payload["event_type"]
        events.append(payload)
    return events


def _record_test_presenter_invocation(kwargs) -> None:
    context = kwargs["request_context"]
    request = ModelRequest(
        capability=ModelCapability.GENERAL,
        messages=({"role": "user", "content": "test presentation request"},),
    )
    response = ModelResponse(
        content="test presentation response",
        requested_alias="auto",
        resolved_provider="mimo",
        resolved_model="mimo-v2.5",
        latency_ms=9,
    )
    record_model_invocation(
        context,
        request,
        response=response,
        provider="mimo",
        model="mimo-v2.5",
        status="SUCCEEDED",
        latency_ms=9,
    )


def test_run_started_cancel_window_sets_event_before_worker_submission(monkeypatch):
    lifecycle = stream_registry.register(
        "TRACE-CANCEL-PREEMPT-001",
        conversation_id="conversation-cancel-preempt",
        client_message_id="message-cancel-preempt",
        connection_open=False,
    )
    submitted = Event()

    class _Executor:
        @staticmethod
        def submit(_worker):
            assert lifecycle.cancel_event.is_set()
            submitted.set()

    monkeypatch.setattr(chat_route, "_CHAT_STREAM_EXECUTOR", _Executor())
    monkeypatch.setattr(chat_route, "_CHAT_CANCEL_PREEMPTION_WINDOW_SECONDS", 0.5)
    canceller = Thread(target=lambda: lifecycle.cancel_event.wait(0.01) or lifecycle.cancel())
    canceller.start()
    chat_route._submit_stream_worker_after_ack(lifecycle, lambda: None)
    canceller.join(timeout=1)
    assert submitted.is_set()
    stream_registry.connection_closed(lifecycle.trace_id)


class _StreamingGateway:
    def stream(self, **_kwargs):
        for content in (" 这是第一段。", "这是第二段，", "回答完成。 "):
            yield ModelReply(content=content, provider="test-provider", model="test-model")

    def complete(self, **_kwargs):
        raise AssertionError("streaming chat must not call non-streaming completion")


def _allow_stream(db_session) -> None:
    workspace = db_session.scalar(select(Workspace))
    user = db_session.scalar(select(AppUser).where(AppUser.email == "admin@chatbi.local"))
    principal = Principal(user.id, workspace.id, user.email, user.display_name, user.role)
    app.dependency_overrides[chat_route._stream_principal] = lambda: principal


def test_chat_stream_is_canonical_lossless_persisted_and_has_one_terminal(client, db_session, monkeypatch):
    conversation = client.post("/api/v1/conversations", json={"title": "Stream"}).json()
    _allow_stream(db_session)
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(chat_route, "SessionLocal", factory)
    monkeypatch.setattr(chat_route, "ChatService", lambda: ChatService(gateway=_StreamingGateway()))

    response = client.post("/api/v1/chat/stream", json={
        "conversation_id": conversation["id"],
        "client_message_id": "client-stream-contract-001",
        "content": "你好",
        "route": "GENERAL_CHAT",
    })
    assert response.status_code == 200
    events = _events(response.text)
    event_types = [item["event_type"] for item in events]
    assert set(event_types) <= set(REQUIRED_EVENTS)
    assert event_types[0] == "run.started"
    assert event_types[-1] == "run.completed"
    assert sum(item in {"run.completed", "run.failed", "run.cancelled"} for item in event_types) == 1
    assert [item["seq"] for item in events] == list(range(1, len(events) + 1))
    assert len({item["run_id"] for item in events}) == 1
    assert {item["conversation_id"] for item in events} == {conversation["id"]}
    assert {item["message_id"] for item in events} == {"client-stream-contract-001"}
    assert {item["request_id"] for item in events} == {"client-stream-contract-001"}
    assert {item["trace_id"] for item in events} == {events[0]["run_id"]}

    started_phases = [item["phase"] for item in events if item["event_type"] == "phase.started"]
    completed_phases = [item["phase"] for item in events if item["event_type"] == "phase.completed"]
    assert started_phases == completed_phases
    deltas = [item["delta"] for item in events if item["event_type"] == "answer.delta"]
    assert deltas == [" 这是第一段。", "这是第二段，", "回答完成。 "]
    terminal = events[-1]
    persisted_content = terminal["response"]["assistant_message"]["content"]
    assert "".join(deltas) == persisted_content
    assert terminal["result_semantic"] == "VALUE"
    assert terminal["message_parts"][0] == {"type": "text", "text": persisted_content, "role": "conclusion"}

    db_session.expire_all()
    persisted = db_session.scalar(select(ChatMessage).where(
        ChatMessage.conversation_id == conversation["id"],
        ChatMessage.role == "assistant",
    ))
    assert persisted.content == persisted_content
    assert persisted.response_payload["result_semantic"] == "VALUE"
    assert persisted.response_payload["message_parts"] == terminal["message_parts"]
    assert persisted.response_payload["presentation_status"] == "PRIMARY_MODEL_PRESENTED"
    assert persisted.response_payload["answer_presentation"]["mode"] == "PRIMARY_MODEL"
    assert persisted.trace_payload["presentation_status"] == "PRIMARY_MODEL_PRESENTED"
    assert persisted.trace_payload["answer_presentation"]["provider"] == "test-provider"


def test_verified_data_query_presents_then_streams_guarded_deltas_and_preserves_both_model_traces(client, db_session, monkeypatch):
    conversation = client.post("/api/v1/conversations", json={"title": "Verified data stream"}).json()
    _allow_stream(db_session)
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(chat_route, "SessionLocal", factory)

    query = _query_payload_for_analysis(42)
    query["plan"]["model_trace"] = {
        "resolved_provider": "deepseek",
        "resolved_model": "deepseek-v4-flash",
        "latency_ms": 7,
    }

    class _AnalysisService:
        def execute(self, _db, _data, _principal, *, progress_callback, cancellation_event, request_context):
            assert cancellation_event is not None
            progress_callback(ProgressStage.UNDERSTANDING, {})
            progress_callback(ProgressStage.QUERYING_DATA, {})
            progress_callback(ProgressStage.VERIFYING, {})
            return AnalysisResponse(
                status="SUCCEEDED",
                route=QuestionRoute.DATA_QUERY,
                trace_id=request_context.trace_id,
                primary=query,
                feature_modes={"rag": "on", "agent": "on"},
                security={"CROSS_WORKSPACE_LEAK": 0},
            )

    class _PresentationGateway:
        providers = {"mimo": object()}

        def complete(self, **kwargs):
            source = json.loads(kwargs["user"])["source_answer"]
            return ModelReply(
                content=json.dumps({"answer": f"先看结论：{source} 可以继续按区域下钻。"}, ensure_ascii=False),
                provider="mimo",
                model="mimo-v2.5",
                trace={
                    "resolved_provider": "mimo",
                    "resolved_model": "mimo-v2.5",
                    "latency_ms": 9,
                },
            )

        def stream(self, **_kwargs):
            raise AssertionError("verified data presentation must be guarded before public deltas")

    monkeypatch.setattr(chat_service_module, "AnalysisService", _AnalysisService)
    monkeypatch.setattr(chat_route, "ChatService", lambda: ChatService(gateway=_PresentationGateway()))

    response = client.post("/api/v1/chat/stream", json={
        "conversation_id": conversation["id"],
        "client_message_id": "client-verified-data-stream-001",
        "content": "今年收入是多少",
        "route": "DATA_QUERY",
    })

    assert response.status_code == 200
    events = _events(response.text)
    deltas = [item["delta"] for item in events if item["event_type"] == "answer.delta"]
    terminal = events[-1]
    assistant = terminal["response"]["assistant_message"]
    assert len(deltas) >= 2
    assert "查询完成，revenue 为 42。" in "".join(deltas)
    assert "".join(deltas) == assistant["content"]
    assert assistant["response_payload"]["answer_presentation"]["status"] == "APPLIED"
    model_call = assistant["trace_payload"]["model_call"]
    assert model_call["primary_model_call"]["resolved_provider"] == "deepseek"
    assert model_call["presentation_model_call"]["resolved_provider"] == "mimo"


def test_chat_stream_keeps_full_analysis_but_only_repeats_twenty_table_rows(client, db_session, monkeypatch):
    conversation = client.post("/api/v1/conversations", json={"title": "Large table"}).json()
    _allow_stream(db_session)
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(chat_route, "SessionLocal", factory)
    rows = [
        {f"column_{column}": f"row-{index}-" + "x" * 100 for column in range(10)}
        for index in range(500)
    ]
    analysis = {
        "status": "SUCCEEDED",
        "route": "DATA_QUERY",
        "trace_id": "TRACE-large-table",
        "primary": {
            "id": "query-large-table",
            "execution": {
                "status": "SUCCEEDED",
                "columns": list(rows[0]),
                "rows": rows,
                "row_count": 500,
                "result_signature": "large-result-signature",
            },
        },
    }
    table = {
        "type": "table",
        "columns": list(rows[0]),
        "rows": rows[:20],
        "row_count": 500,
        "result_signature": "large-result-signature",
    }
    message_parts = [{"type": "text", "text": "查询返回 500 行。", "role": "conclusion"}, table]

    class _LargeResultService:
        def execute(self, _worker_db, data, _principal, **kwargs):
            kwargs["progress"]("UNDERSTANDING", {"route": "DATA_QUERY"})
            kwargs["answer_delta"]("查询返回 500 行。")
            timestamp = conversation["created_at"]
            return ChatResponse.model_validate({
                "conversation": conversation,
                "user_message": {
                    "id": "user-large-table", "conversation_id": conversation["id"],
                    "parent_message_id": None, "role": "user", "content": data.content,
                    "route": "DATA_QUERY", "status": "COMPLETED", "attachment_ids": [],
                    "context_payload": {}, "response_payload": {}, "trace_payload": {},
                    "error_code": None, "created_at": timestamp,
                },
                "assistant_message": {
                    "id": "assistant-large-table", "conversation_id": conversation["id"],
                    "parent_message_id": "user-large-table", "role": "assistant",
                    "content": "查询返回 500 行。", "route": "DATA_QUERY", "status": "SUCCEEDED",
                    "attachment_ids": [], "context_payload": {},
                    "response_payload": {
                        "analysis": analysis, "message_parts": message_parts, "result_semantic": "VALUE",
                    },
                    "trace_payload": {}, "error_code": None, "created_at": timestamp,
                },
                "message_parts": message_parts,
                "result_semantic": "VALUE",
            })

    monkeypatch.setattr(chat_route, "ChatService", _LargeResultService)
    response = client.post("/api/v1/chat/stream", json={
        "conversation_id": conversation["id"],
        "client_message_id": "client-large-table-001",
        "content": "返回宽表",
        "route": "DATA_QUERY",
    })
    events = _events(response.text)
    artifact = next(item for item in events if item["event_type"] == "artifact.ready" and item["artifact_type"] == "table")
    terminal = events[-1]
    terminal_table = next(item for item in terminal["message_parts"] if item["type"] == "table")
    response_table = next(item for item in terminal["response"]["message_parts"] if item["type"] == "table")
    persisted_table = next(
        item for item in terminal["response"]["assistant_message"]["response_payload"]["message_parts"]
        if item["type"] == "table"
    )
    for item in (artifact["artifact"], terminal_table, response_table, persisted_table):
        assert len(item["rows"]) == 20
        assert item["row_count"] == 500
        assert item["result_signature"] == "large-result-signature"
    full_execution = terminal["response"]["assistant_message"]["response_payload"]["analysis"]["primary"]["execution"]
    assert len(full_execution["rows"]) == full_execution["row_count"] == 500
    analysis_bytes = len(json.dumps(analysis, ensure_ascii=False).encode("utf-8"))
    terminal_bytes = len(json.dumps(terminal, ensure_ascii=False).encode("utf-8"))
    assert terminal_bytes < analysis_bytes * 1.5


def test_chat_stream_exception_and_cancel_each_emit_one_terminal(client, db_session, monkeypatch):
    conversation = client.post("/api/v1/conversations", json={"title": "Terminal"}).json()
    _allow_stream(db_session)
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(chat_route, "SessionLocal", factory)

    class _FailedService:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("private provider detail")

    monkeypatch.setattr(chat_route, "ChatService", _FailedService)
    failed = client.post("/api/v1/chat/stream", json={
        "conversation_id": conversation["id"],
        "client_message_id": "client-stream-failed-001",
        "content": "你好",
    })
    failed_events = _events(failed.text)
    assert [item["event_type"] for item in failed_events] == ["run.started", "run.failed"]
    assert "private provider detail" not in failed.text

    class _CancelledService:
        def execute(self, worker_db, data, principal, **_kwargs):
            worker_db.add(ChatMessage(
                conversation_id=data.conversation_id,
                workspace_id=principal.workspace_id,
                user_id=principal.user_id,
                client_message_id=data.client_message_id,
                role="user",
                content=data.content,
                status="COMPLETED",
            ))
            worker_db.commit()
            raise StreamCancelled("cancelled")

    monkeypatch.setattr(chat_route, "ChatService", _CancelledService)
    cancelled = client.post("/api/v1/chat/stream", json={
        "conversation_id": conversation["id"],
        "client_message_id": "client-stream-cancelled-001",
        "content": "你好",
    })
    cancelled_events = _events(cancelled.text)
    assert [item["event_type"] for item in cancelled_events] == ["run.started", "run.cancelled"]
    assert cancelled_events[-1]["code"] == "RUN_CANCELLED"
    db_session.expire_all()
    assert db_session.scalar(select(ChatMessage).where(
        ChatMessage.client_message_id == "client-stream-cancelled-001",
    )) is None


def test_pre_cancelled_chat_does_not_persist_messages(client, db_session):
    conversation = client.post("/api/v1/conversations", json={"title": "Cancel"}).json()
    workspace = db_session.scalar(select(Workspace))
    user = db_session.scalar(select(AppUser).where(AppUser.email == "admin@chatbi.local"))
    principal = Principal(user.id, workspace.id, user.email, user.display_name, user.role)
    cancelled = Event()
    cancelled.set()
    with pytest.raises(StreamCancelled):
        ChatService(gateway=_StreamingGateway()).execute(
            db_session,
            ChatRequest(
                conversation_id=conversation["id"],
                content="你好",
                client_message_id="client-pre-cancelled-001",
                route="GENERAL_CHAT",
            ),
            principal,
            cancellation_event=cancelled,
            answer_delta=lambda _delta: None,
        )
    db_session.rollback()
    assert list(db_session.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conversation["id"]))) == []


def test_explicit_chat_cancel_is_conversation_scoped(client, db_session, monkeypatch):
    conversation = client.post("/api/v1/conversations", json={"title": "Cancel"}).json()
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(chat_route, "SessionLocal", factory)
    lifecycle = stream_registry.register(
        "STREAM-explicit-route-cancel",
        conversation_id=conversation["id"],
        client_message_id="client-explicit-cancel-001",
    )
    stream_registry.task_started("STREAM-explicit-route-cancel")

    def commit_inside_the_cancel_window() -> None:
        assert lifecycle.cancel_event.wait(timeout=1)
        with chat_route.SessionLocal() as late_db:
            conversation_row = late_db.get(Conversation, conversation["id"])
            assert conversation_row is not None
            user = ChatMessage(
                conversation_id=conversation["id"],
                workspace_id=conversation_row.workspace_id,
                user_id=conversation_row.user_id,
                client_message_id="client-explicit-cancel-001",
                role="user",
                content="cancel me",
                status="COMPLETED",
            )
            late_db.add(user)
            late_db.flush()
            late_db.add(ChatMessage(
                conversation_id=conversation["id"],
                workspace_id=conversation_row.workspace_id,
                user_id=conversation_row.user_id,
                parent_message_id=user.id,
                role="assistant",
                content="must be removed",
                status="SUCCEEDED",
            ))
            late_db.commit()
        stream_registry.task_finished("STREAM-explicit-route-cancel")

    thread = Thread(target=commit_inside_the_cancel_window)
    thread.start()
    try:
        response = client.post("/api/v1/chat/stream/cancel", json={
            "conversation_id": conversation["id"],
            "client_message_id": "client-explicit-cancel-001",
        })
        assert response.status_code == 202
        assert response.json() == {"cancelled": True}
        assert lifecycle.cancel_event.is_set()
        assert lifecycle.task_done.is_set()
        thread.join(timeout=1)
        assert not thread.is_alive()
        with chat_route.SessionLocal() as check_db:
            assert list(check_db.scalars(select(ChatMessage).where(
                ChatMessage.conversation_id == conversation["id"],
            ))) == []
    finally:
        lifecycle.cancel()
        thread.join(timeout=1)
        stream_registry.task_finished("STREAM-explicit-route-cancel")
        stream_registry.connection_closed("STREAM-explicit-route-cancel")


def test_model_gateway_normalizes_provider_sse_chunks():
    def handler(request: httpx.Request):
        assert json.loads(request.content)["stream"] is True
        body = (
            'data: {"choices":[{"delta":{"content":"第一段"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"第二段"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    gateway = ModelGateway(Settings(
        kimi_api_key="kimi-test",
        mimo_api_key="",
        deepseek_api_key="",
        general_model_provider="kimi",
    ), transport=httpx.MockTransport(handler))
    chunks = list(gateway.stream(system="system", user="hello", json_mode=False))
    assert [item.content for item in chunks] == ["第一段", "第二段"]
    assert {item.provider for item in chunks} == {"kimi"}


def test_conversation_patch_renames_with_workspace_user_scope_and_cleans_title(client):
    conversation = client.post("/api/v1/conversations", json={"title": "新会话"}).json()
    renamed = client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"title": "  华东收入\n分析   "},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "华东收入 分析"
    detail = client.get(f"/api/v1/conversations/{conversation['id']}").json()
    assert detail["title"] == "华东收入 分析"
    assert client.patch(
        f"/api/v1/conversations/{conversation['id']}", json={"title": "\n\t"},
    ).status_code == 422


def test_automatic_conversation_title_removes_newlines_and_is_bounded():
    conversation = type("ConversationStub", (), {
        "title": "新会话", "summary": "", "slot_state": {}, "updated_at": None,
    })()
    refresh_conversation_summary(conversation, "第一行\n" + "很长的业务问题" * 20, {})
    assert "\n" not in conversation.title
    assert 1 <= len(conversation.title) <= 40


def test_analysis_sync_uses_guarded_final_presenter(client, db_session, monkeypatch):
    query = _query_payload_for_analysis(42)

    class _AnalysisService:
        def execute(self, _db, _data, _principal):
            return AnalysisResponse(
                status="SUCCEEDED",
                route=QuestionRoute.DATA_QUERY,
                trace_id="TRACE-analysis-sync-presentation",
                primary=query,
                feature_modes={"rag": "on", "agent": "on"},
                security={"CROSS_WORKSPACE_LEAK": 0},
            )

    class _Presenter:
        def present(self, **kwargs):
            _record_test_presenter_invocation(kwargs)
            source = kwargs["answer"]
            assert kwargs["response_payload"]["analysis"]["primary"]["guard"]["allowed"] is True
            assert kwargs["request_context"].route == "DATA_QUERY"
            return AnswerPresentation(
                f"下面是核验后的结果：\n{source}",
                "APPLIED",
                applied=True,
                source_verified=True,
                provider="mimo",
                model="mimo-v2.5",
                trace={"resolved_provider": "mimo", "resolved_model": "mimo-v2.5"},
            )

    monkeypatch.setattr(analysis_route, "AnalysisService", _AnalysisService)
    monkeypatch.setattr(analysis_route, "AnswerPresenter", _Presenter)
    response = client.post("/api/v1/analysis", json={
        "question": "今年收入是多少",
        "route": "DATA_QUERY",
        "idempotency_key": "analysis-sync-presentation-001",
    })
    assert response.status_code == 201
    envelope = response.json()["answer_envelope"]
    assert envelope["markdown"].startswith("下面是核验后的结果：")
    assert envelope["provider"] == "mimo"
    assert envelope["model"] == "mimo-v2.5"
    db_session.expire_all()
    invocation = db_session.scalar(select(ModelInvocation).where(
        ModelInvocation.trace_id == "TRACE-analysis-sync-presentation",
        ModelInvocation.provider == "mimo",
    ))
    assert invocation is not None
    assert invocation.status == "SUCCEEDED"


def test_analysis_stream_uses_same_canonical_contract(client, db_session, monkeypatch):
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(analysis_route, "SessionLocal", factory)
    query = _query_payload_for_analysis(42)

    class _AnalysisService:
        def execute(self, _db, _data, _principal, *, progress_callback, cancellation_event, request_context):
            assert cancellation_event is not None
            assert request_context.trace_id.startswith("TRACE-")
            progress_callback(ProgressStage.UNDERSTANDING, {})
            progress_callback(ProgressStage.QUERYING_DATA, {})
            progress_callback(ProgressStage.VERIFYING, {})
            return AnalysisResponse(
                status="SUCCEEDED",
                route=QuestionRoute.DATA_QUERY,
                trace_id=request_context.trace_id,
                primary=query,
                feature_modes={"rag": "on", "agent": "on"},
                security={"CROSS_WORKSPACE_LEAK": 0},
            )

    class _Presenter:
        def present(self, **kwargs):
            _record_test_presenter_invocation(kwargs)
            source = kwargs["answer"]
            assert kwargs["route"] == "DATA_QUERY"
            assert kwargs["request_context"].route == "DATA_QUERY"
            assert kwargs["response_payload"]["analysis"]["primary"]["oracle"]["status"] == "PASSED"
            return AnswerPresentation(
                f"先看结论：\n{source}",
                "APPLIED",
                applied=True,
                source_verified=True,
                provider="mimo",
                model="mimo-v2.5",
                trace={"resolved_provider": "mimo", "resolved_model": "mimo-v2.5"},
            )

    monkeypatch.setattr(analysis_route, "AnalysisService", _AnalysisService)
    monkeypatch.setattr(analysis_route, "AnswerPresenter", _Presenter)
    response = client.post("/api/v1/analysis/stream", json={
        "question": "今年收入是多少",
        "route": "DATA_QUERY",
        "idempotency_key": "analysis-stream-contract-001",
    })
    assert response.status_code == 200
    events = _events(response.text)
    event_types = [item["event_type"] for item in events]
    assert set(event_types) <= set(REQUIRED_EVENTS)
    assert event_types[0] == "run.started" and event_types[-1] == "run.completed"
    assert all(item not in {"accepted", "progress", "result", "completed"} for item in event_types)
    assert [item["phase"] for item in events if item["event_type"] == "phase.started"] == [
        item["phase"] for item in events if item["event_type"] == "phase.completed"
    ]
    deltas = [item["delta"] for item in events if item["event_type"] == "answer.delta"]
    terminal = events[-1]
    response_payload = terminal["response"]
    assert ChatResponse.model_validate(response_payload).assistant_message.content == "".join(deltas)
    assert {"conversation", "user_message", "assistant_message"} <= set(response_payload)
    conversation = response_payload["conversation"]
    user_message = response_payload["user_message"]
    assistant_message = response_payload["assistant_message"]
    workspace = db_session.scalar(select(Workspace))
    assert conversation["id"] == terminal["conversation_id"]
    assert conversation["title"] == "今年收入是多少"
    assert user_message["id"] == "analysis-user-analysis-stream-contract-001"
    assert user_message["conversation_id"] == conversation["id"]
    assert user_message["content"] == "今年收入是多少"
    assert user_message["context_payload"] == {
        "workspace_id": workspace.id,
        "analysis_request_id": "analysis-stream-contract-001",
    }
    assert assistant_message["conversation_id"] == conversation["id"]
    assert assistant_message["parent_message_id"] == user_message["id"]
    assert assistant_message["response_payload"]["analysis"]["primary"]["id"] == "query-analysis"
    assert assistant_message["response_payload"]["analysis"]["presentation_status"] == "APPLIED"
    assert assistant_message["trace_payload"]["presentation_status"] == "APPLIED"
    assert assistant_message["trace_payload"]["answer_presentation"]["provider"] == "mimo"
    assert assistant_message["response_payload"]["answer_envelope"]["provider"] == "mimo"
    assert assistant_message["response_payload"]["answer_envelope"]["model"] == "mimo-v2.5"
    assert assistant_message["response_payload"]["message_parts"] == terminal["message_parts"]
    assert "".join(deltas) == assistant_message["content"]
    assert assistant_message["content"].startswith("先看结论：")
    assert terminal["result_semantic"] == response_payload["result_semantic"] == "VALUE"
    db_session.expire_all()
    invocation = db_session.scalar(select(ModelInvocation).where(
        ModelInvocation.trace_id == assistant_message["trace_payload"]["trace_id"],
        ModelInvocation.provider == "mimo",
    ))
    assert invocation is not None
    assert invocation.status == "SUCCEEDED"


def test_analysis_presenter_rejection_keeps_primary_model_attribution(client, monkeypatch):
    query = _query_payload_for_analysis(42)
    query["plan"]["model_trace"] = {
        "resolved_provider": "deepseek",
        "resolved_model": "deepseek-v4-flash",
        "latency_ms": 7,
    }

    class _AnalysisService:
        def execute(self, _db, _data, _principal):
            return AnalysisResponse(
                status="SUCCEEDED",
                route=QuestionRoute.DATA_QUERY,
                trace_id="TRACE-analysis-presenter-rejected",
                primary=query,
                feature_modes={"rag": "on", "agent": "on"},
                security={"CROSS_WORKSPACE_LEAK": 0},
            )

    class _RejectedPresenter:
        def present(self, **kwargs):
            return AnswerPresentation(
                kwargs["answer"],
                "FALLBACK_PRESENTATION_GUARD_REJECTED",
                applied=False,
                source_verified=True,
                provider="kimi",
                model="kimi-k2.5",
                trace={"resolved_provider": "kimi", "resolved_model": "kimi-k2.5"},
            )

    monkeypatch.setattr(analysis_route, "AnalysisService", _AnalysisService)
    monkeypatch.setattr(analysis_route, "AnswerPresenter", _RejectedPresenter)
    response = client.post("/api/v1/analysis", json={
        "question": "今年收入是多少",
        "route": "DATA_QUERY",
        "idempotency_key": "analysis-presenter-rejected-001",
    })
    assert response.status_code == 201
    envelope = response.json()["answer_envelope"]
    assert envelope["provider"] == "deepseek"
    assert envelope["model"] == "deepseek-v4-flash"
    assert envelope["provider"] != "kimi"


def test_analysis_presentation_ledger_commit_failure_does_not_replace_result(
    client, db_session, monkeypatch,
):
    query = _query_payload_for_analysis(42)

    class _AnalysisService:
        def execute(self, _db, _data, _principal):
            return AnalysisResponse(
                status="SUCCEEDED",
                route=QuestionRoute.DATA_QUERY,
                trace_id="TRACE-analysis-ledger-failure",
                primary=query,
                feature_modes={"rag": "on", "agent": "on"},
                security={"CROSS_WORKSPACE_LEAK": 0},
            )

    class _Presenter:
        def present(self, **kwargs):
            return AnswerPresentation(kwargs["answer"], "FALLBACK_NO_AVAILABLE_PROVIDER")

    def _commit_failure():
        raise RuntimeError("simulated ledger outage")

    monkeypatch.setattr(analysis_route, "AnalysisService", _AnalysisService)
    monkeypatch.setattr(analysis_route, "AnswerPresenter", _Presenter)
    monkeypatch.setattr(db_session, "commit", _commit_failure)
    response = client.post("/api/v1/analysis", json={
        "question": "今年收入是多少",
        "route": "DATA_QUERY",
        "idempotency_key": "analysis-ledger-failure-001",
    })
    assert response.status_code == 201
    assert response.json()["answer_envelope"]["markdown"] == "查询完成，revenue 为 42。"


def test_analysis_sync_presenter_exception_falls_back_to_primary_answer(client, monkeypatch):
    query = _query_payload_for_analysis(42)
    query["plan"]["model_trace"] = {
        "resolved_provider": "deepseek",
        "resolved_model": "deepseek-v4-flash",
    }

    class _AnalysisService:
        def execute(self, _db, _data, _principal):
            return AnalysisResponse(
                status="SUCCEEDED",
                route=QuestionRoute.DATA_QUERY,
                trace_id="TRACE-analysis-presenter-exception",
                primary=query,
                feature_modes={"rag": "on", "agent": "on"},
                security={"CROSS_WORKSPACE_LEAK": 0},
            )

    class _BrokenPresenter:
        def __init__(self):
            raise RuntimeError("simulated presenter construction failure")

    monkeypatch.setattr(analysis_route, "AnalysisService", _AnalysisService)
    monkeypatch.setattr(analysis_route, "AnswerPresenter", _BrokenPresenter)
    response = client.post("/api/v1/analysis", json={
        "question": "今年收入是多少",
        "route": "DATA_QUERY",
        "idempotency_key": "analysis-presenter-exception-001",
    })
    assert response.status_code == 201
    envelope = response.json()["answer_envelope"]
    assert envelope["markdown"] == "查询完成，revenue 为 42。"
    assert envelope["provider"] == "deepseek"
    assert envelope["model"] == "deepseek-v4-flash"


def test_analysis_stream_presenter_exception_still_completes(client, db_session, monkeypatch):
    factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(analysis_route, "SessionLocal", factory)
    query = _query_payload_for_analysis(42)
    query["plan"]["model_trace"] = {
        "resolved_provider": "deepseek",
        "resolved_model": "deepseek-v4-flash",
    }

    class _AnalysisService:
        def execute(self, _db, _data, _principal, **kwargs):
            kwargs["progress_callback"](ProgressStage.VERIFYING, {})
            return AnalysisResponse(
                status="SUCCEEDED",
                route=QuestionRoute.DATA_QUERY,
                trace_id=kwargs["request_context"].trace_id,
                primary=query,
                feature_modes={"rag": "on", "agent": "on"},
                security={"CROSS_WORKSPACE_LEAK": 0},
            )

    class _BrokenPresenter:
        def __init__(self):
            raise RuntimeError("simulated presenter construction failure")

    monkeypatch.setattr(analysis_route, "AnalysisService", _AnalysisService)
    monkeypatch.setattr(analysis_route, "AnswerPresenter", _BrokenPresenter)
    response = client.post("/api/v1/analysis/stream", json={
        "question": "今年收入是多少",
        "route": "DATA_QUERY",
        "idempotency_key": "analysis-stream-presenter-exception-001",
    })
    assert response.status_code == 200
    events = _events(response.text)
    assert events[-1]["event_type"] == "run.completed"
    assistant = events[-1]["response"]["assistant_message"]
    assert assistant["content"] == "查询完成，revenue 为 42。"
    assert assistant["trace_payload"]["presentation_status"] == "FALLBACK_PRESENTATION_ERROR"
    assert assistant["response_payload"]["answer_envelope"]["provider"] == "deepseek"
    assert assistant["response_payload"]["answer_envelope"]["model"] == "deepseek-v4-flash"


def test_analysis_sync_and_stream_source_humanize_internal_failure_codes():
    payload = {
        "status": "TIMEOUT",
        "route": "COMPLEX_ANALYSIS",
        "primary": {
            "error_code": "DBGPT_RUNTIME_TIMEOUT",
            "error_message": "DBGPT_RUNTIME_TIMEOUT",
        },
    }

    visible = analysis_route._answer_text(payload)

    assert "受控时限内完成" in visible
    assert "没有发布不完整的结论" in visible
    assert "DBGPT_RUNTIME_TIMEOUT" not in visible


def _query_payload_for_analysis(value):
    return {
        "id": "query-analysis",
        "status": "SUCCEEDED",
        "summary": f"查询完成，revenue 为 {value}。",
        "plan": {"metrics": ["revenue"], "dimensions": []},
        "guard": {"allowed": True, "normalized_sql": "SELECT revenue FROM orders"},
        "execution": {
            "status": "SUCCEEDED", "columns": ["revenue"], "rows": [{"revenue": value}],
            "row_count": 1, "result_signature": "signature-analysis",
        },
        "oracle": {"status": "PASSED"},
        "chart_spec": {"data_source_query_id": "query-analysis", "result_signature": "signature-analysis"},
        "kpis": [{"label": "revenue", "value": value, "unit": "元"}],
        "recommended_questions": [],
    }
