from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from app.model_gateway.normalization import (
    ProviderResponseNormalizationError,
    normalize_chat_completion,
)
from app.model_gateway.contracts import ModelResponse, ModelUsage, RequestContext
from app.model_gateway.service import ModelGateway
from app.integration.tool_executor import ChatBIToolExecutor
from app.integration import tool_executor as tool_executor_module
from chatbi_agent_contracts import AgentExecutionContext, AgentRole, ToolCall
from app.query.contracts import QueryContext, SecurityPolicy
from app.query.nl2sql import OpenAICompatibleProvider
from app.query.nl2sql_response import (
    Nl2SqlResponseNormalizationError,
    STRIP_SERVER_OWNED_MODEL_TRACE,
    normalize_nl2sql_response,
    normalize_nl2sql_response_with_metadata,
)
from app.query.sql_guard import SqlGuard
from app.streaming.lifecycle import StreamCancelled, StreamRegistry


FIXTURES = Path(__file__).parent / "fixtures" / "provider_responses"


def test_complex_query_tool_preserves_outer_paid_case_and_trace_identity(monkeypatch):
    captured: dict[str, object] = {}

    class _Run:
        id = "query-run"
        status = "SUCCEEDED"
        error_code = None

    class _Pipeline:
        def execute(self, _db, request, principal=None, **kwargs):
            del principal
            captured["question"] = request.question
            captured["request_context"] = kwargs.get("request_context")
            return _Run()

    class _Response:
        def model_dump(self, **_kwargs):
            return {
                "id": "query-run",
                "status": "SUCCEEDED",
                "guard": {"allowed": True},
                "oracle": {"status": "PASSED"},
                "execution": {"result_signature": "a" * 64},
            }

    monkeypatch.setattr(tool_executor_module, "QueryPipeline", _Pipeline)
    monkeypatch.setattr(tool_executor_module, "query_response", lambda _run: _Response())
    runtime = RequestContext(
        request_id="P5-P5C03-paid-case",
        trace_id="TRACE-P5C03-trusted",
        conversation_id="conversation-p5c03",
        route="COMPLEX_ANALYSIS",
        user_id="user-p5c03",
        workspace_id="workspace-p5c03",
        datasource_id="datasource-p5c03",
        roles=frozenset({"ADMIN"}),
        permission_hash="permission-p5c03",
        question="outer question",
    )
    executor = ChatBIToolExecutor(
        object(), object(), rag_adapter=None, request_context=runtime,
    )
    result = executor.execute(
        ToolCall(
            tool_name="QUERY_DATA",
            agent_role=AgentRole.DATA_ANALYST,
            arguments={
                "question": "tool question",
                "datasource_id": "datasource-p5c03",
                "semantic_model_id": "semantic-p5c03",
            },
            idempotency_key="tool-p5c03-identity",
        ),
        AgentExecutionContext(
            workspace_id="workspace-p5c03",
            user_id="user-p5c03",
            roles=frozenset({"ADMIN"}),
            allowed_datasources=frozenset({"datasource-p5c03"}),
            allowed_semantic_models=frozenset({"semantic-p5c03"}),
            allowed_tools=frozenset({"QUERY_DATA"}),
            trace_id="TRACE-P5C03-trusted",
            timeout_ms=30_000,
            token_budget=6_000,
        ),
    )
    bound = captured["request_context"]
    assert result.status == "SUCCEEDED"
    assert captured["question"] == "tool question"
    assert bound.request_id == "P5-P5C03-paid-case"
    assert bound.trace_id == "TRACE-P5C03-trusted"
    assert bound.datasource_id == "datasource-p5c03"
    assert bound.question == "tool question"


def test_correlation_scope_consumes_canonical_order_date_year_grain(monkeypatch):
    monkeypatch.setattr(
        tool_executor_module,
        "execute_selected_pandasai_runtime",
        lambda *_args, **_kwargs: SimpleNamespace(output={
            "status": "SUCCEEDED",
            "runtime_verified": True,
            "container_destroyed": True,
            "output": {"correlation": 1.0, "sample_size": 2},
        }),
    )
    executor = ChatBIToolExecutor(object(), object(), rag_adapter=None)
    payload, error = executor._correlation_result(
        {"execution": {"rows": [
            {"order_date": 2025, "revenue": 100.0, "cost": 80.0},
            {"order_date": 2026, "revenue": 120.0, "cost": 96.0},
        ]}},
        AgentExecutionContext(
            workspace_id="workspace",
            user_id="user",
            roles=frozenset({"ADMIN"}),
            allowed_datasources=frozenset(),
            allowed_semantic_models=frozenset(),
            allowed_tools=frozenset({"QUERY_DATA"}),
            trace_id="TRACE-CANONICAL-YEAR-SCOPE",
            timeout_ms=30_000,
            token_budget=6_000,
        ),
    )

    assert error is None
    assert payload["answer_claims"] == [{
        "metric": "correlation",
        "scope": "ANNUAL_REVENUE_COST_2025_2026",
        "value": 1.0,
    }]


def _generic_mimo_content() -> dict:
    fixture = json.loads((FIXTURES / "mimo_nl2sql_object.json").read_text(encoding="utf-8"))
    return deepcopy(fixture["response"]["choices"][0]["message"]["content"])


@pytest.mark.parametrize(
    "filename,provider",
    (
        ("mimo_nl2sql_object.json", "mimo"),
        ("deepseek_nl2sql_markdown.json", "deepseek"),
        ("kimi_nl2sql_wrapped_string.json", "kimi"),
    ),
)
def test_task_authorized_generic_provider_variant_normalizes_known_shapes(
    filename: str,
    provider: str,
) -> None:
    fixture = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
    assert fixture["provider"] == provider
    assert fixture["provenance"] == "TASK_AUTHORIZED_GENERIC_VARIANT_HISTORICAL_RAW_NOT_RETAINED"
    assert fixture["historical_evidence"] == {
        "error_class": "ValueError",
        "raw_response_available": False,
    }
    response = normalize_chat_completion(fixture["response"])
    plan = normalize_nl2sql_response(response.content)
    guard = SqlGuard().validate(
        plan.generated_sql,
        dialect=plan.dialect,
        policy=SecurityPolicy(
            allowed_tables=["orders"],
            allowed_columns={"orders": ["region", "revenue"]},
        ),
    )
    assert response.usage.exact is True
    assert plan.provider == provider
    assert guard.allowed is True


def test_recorded_real_mimo_model_trace_null_response_regression() -> None:
    fixture = json.loads(
        (FIXTURES / "mimo_nl2sql_recorded_real_model_trace_null.json").read_text(encoding="utf-8")
    )
    assert fixture["provenance"] == "RECORDED_REAL_SANITIZED_PROVIDER_RESPONSE_2026-08-25"
    assert fixture["source_evidence"] == {
        "candidate_sha": "e9e4cf899329c6909c017a293a413def7c0f2134",
        "case_id": "FINAL-NL2SQL-MIMO",
        "evidence_sha256": "8fc0874495b46bd947523c791a70e998f1979cfbf1f903c7af4fb2c15f2fb7b2",
        "raw_response_sha256": "e41afb37da9bf3fbe06ee794666282b4023929aefc9deddce692288fa3467d5a",
        "response_shape_fingerprint": "91a2e4919b7b51968745678d4ab8a60cc691cd77404201c92b5d3e9b256f1475",
        "sanitized": True,
    }
    response = normalize_chat_completion(fixture["response"])
    normalized = normalize_nl2sql_response_with_metadata(response.content)
    guard = SqlGuard().validate(
        normalized.plan.generated_sql,
        dialect=normalized.plan.dialect,
        policy=SecurityPolicy(
            allowed_tables=["orders"],
            allowed_columns={"orders": ["revenue"]},
        ),
    )
    assert response.resolved_model == "mimo-v2.5"
    assert response.usage == ModelUsage(
        input_tokens=5785,
        cached_input_tokens=0,
        output_tokens=220,
        total_tokens=6005,
        exact=True,
    )
    assert normalized.normalization_actions == (STRIP_SERVER_OWNED_MODEL_TRACE,)
    assert normalized.plan.model_trace == {}
    assert guard.allowed is True


@pytest.mark.parametrize(
    "variant,value,expected_actions",
    (
        ("absent", None, ()),
        ("null", None, (STRIP_SERVER_OWNED_MODEL_TRACE,)),
        ("object", {"trace_id": "provider-fake"}, (STRIP_SERVER_OWNED_MODEL_TRACE,)),
        ("string", "provider-fake", (STRIP_SERVER_OWNED_MODEL_TRACE,)),
        ("list", ["provider-fake"], (STRIP_SERVER_OWNED_MODEL_TRACE,)),
    ),
)
def test_server_owned_model_trace_variants_are_stripped(
    variant: str,
    value: object,
    expected_actions: tuple[str, ...],
) -> None:
    content = _generic_mimo_content()
    if variant == "absent":
        content.pop("model_trace", None)
    else:
        content["model_trace"] = value
    normalized = normalize_nl2sql_response_with_metadata(content)
    assert normalized.normalization_actions == expected_actions
    assert normalized.plan.model_trace == {}


@pytest.mark.parametrize("variant", ("unknown_field", "missing_required", "wrong_type"))
def test_business_payload_remains_strict_and_fail_closed(variant: str) -> None:
    content = _generic_mimo_content()
    if variant == "unknown_field":
        content["provider_defined_business_mode"] = "unsafe"
    elif variant == "missing_required":
        content.pop("selected_tables")
    else:
        content["selected_tables"] = "orders"
    with pytest.raises(Nl2SqlResponseNormalizationError, match="NL2SQL_RESPONSE_SCHEMA_INVALID"):
        normalize_nl2sql_response(content)


def test_provider_trace_spoof_cannot_replace_server_runtime_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    provider_payload = _generic_mimo_content()
    provider_payload["model_trace"] = {
        "workspace_id": "other-workspace",
        "trace_id": "provider-fake-trace",
        "request_id": "provider-fake-request",
        "cost_cny": 999,
    }
    captured: dict[str, object] = {}

    def fake_execute(self, request, context, *, cancellation_event=None):
        captured["context"] = context
        return ModelResponse(
            content=json.dumps(provider_payload, ensure_ascii=False),
            requested_alias="mimo",
            resolved_provider="mimo",
            resolved_model="mimo-v2.5",
            usage=ModelUsage(input_tokens=5, output_tokens=3, total_tokens=8, exact=True),
            cost_cny=0.001,
            latency_ms=12,
            pricing_version="test-pricing",
        )

    monkeypatch.setattr(ModelGateway, "execute", fake_execute)
    provider = OpenAICompatibleProvider(
        provider_name="mimo",
        display_name="MiMo",
        base_url="https://provider.invalid/v1",
        api_key="test-only-key",
        model_name="mimo-v2.5",
    )
    context = QueryContext(
        request_id="trusted-request",
        trace_id="trusted-trace-0001",
        route="DATA_QUERY",
        user_id="trusted-user",
        conversation_id="trusted-conversation",
        permission_hash="trusted-permission",
        workspace_id="trusted-workspace",
        workspace_name="Trusted Workspace",
        datasource_id="trusted-datasource",
        datasource_name="Demo MySQL",
        dialect="mysql",
        semantic_model_id="trusted-semantic-model",
        semantic_model_name="Demo Model",
        semantic_model_version=7,
        entities=[],
        candidate_tables=[],
        candidate_columns=[],
        metrics=[],
        dimensions=[],
        relationships=[],
        business_terms=[],
        now=datetime(2026, 8, 25, tzinfo=timezone.utc),
        row_limit=500,
        token_budget=4096,
        estimated_tokens=256,
        security_policy=SecurityPolicy(
            allowed_tables=["orders"],
            allowed_columns={"orders": ["revenue"]},
        ),
    )
    plan = provider.generate(question="trusted question", context=context)
    runtime_context = captured["context"]
    assert runtime_context.workspace_id == "trusted-workspace"
    assert runtime_context.trace_id == "trusted-trace-0001"
    assert runtime_context.request_id == "trusted-request"
    assert plan.question == "trusted question"
    assert plan.provider == "mimo"
    assert plan.semantic_model_id == "trusted-semantic-model"
    assert plan.semantic_model_version == 7
    assert plan.model_trace["resolved_provider"] == "mimo"
    assert plan.model_trace["resolved_model"] == "mimo-v2.5"
    assert plan.model_trace["cost_cny"] == 0.001
    assert plan.model_trace["provider_response_normalization_actions"] == [
        STRIP_SERVER_OWNED_MODEL_TRACE
    ]
    assert "workspace_id" not in plan.model_trace
    assert "trace_id" not in plan.model_trace
    assert "request_id" not in plan.model_trace


@pytest.mark.parametrize(
    "payload,error",
    (
        ("", "NL2SQL_RESPONSE_EMPTY_OR_TOO_LARGE"),
        ("not-json SELECT * FROM orders", "NL2SQL_RESPONSE_JSON_INVALID"),
        ("prefix {\"generated_sql\":\"SELECT 1\"}", "NL2SQL_RESPONSE_JSON_INVALID"),
        ("[]", "NL2SQL_RESPONSE_OBJECT_REQUIRED"),
        ("{\"generated_sql\":\"SELECT 1\"}", "NL2SQL_RESPONSE_SCHEMA_INVALID"),
        ("{\"data\":{},\"result\":{}}", "NL2SQL_RESPONSE_WRAPPER_AMBIGUOUS"),
    ),
)
def test_unknown_or_invalid_nl2sql_variants_fail_closed(payload: str, error: str) -> None:
    with pytest.raises(Nl2SqlResponseNormalizationError, match=error):
        normalize_nl2sql_response(payload)


def test_normalization_never_bypasses_sql_guard() -> None:
    fixture = json.loads((FIXTURES / "mimo_nl2sql_object.json").read_text(encoding="utf-8"))
    content = fixture["response"]["choices"][0]["message"]["content"]
    content["generated_sql"] = "DELETE FROM orders"
    plan = normalize_nl2sql_response(content)
    guard = SqlGuard().validate(
        plan.generated_sql,
        dialect=plan.dialect,
        policy=SecurityPolicy(
            allowed_tables=["orders"],
            allowed_columns={"orders": ["region", "revenue"]},
        ),
    )
    assert guard.allowed is False


@pytest.mark.parametrize(
    "content",
    (
        [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}],
        ["plain-string-part"],
        42,
    ),
)
def test_unknown_provider_content_shapes_fail_closed(content: object) -> None:
    with pytest.raises(ProviderResponseNormalizationError):
        normalize_chat_completion({
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        })


def test_timeout_cancel_cleanup_race_stress_100_is_terminal_before_parent_delete(tmp_path: Path) -> None:
    database = tmp_path / "cleanup-race.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("CREATE TABLE conversation (id TEXT PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE message (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversation(id))"
        )

    fk_violations = 0
    late_writes = 0
    for index in range(100):
        registry = StreamRegistry()
        conversation_id = f"conversation-{index}"
        trace_id = f"TRACE-RACE-{index}"
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("INSERT INTO conversation (id) VALUES (?)", (conversation_id,))
        lifecycle = registry.register(
            trace_id,
            conversation_id=conversation_id,
            client_message_id=f"message-{index}",
            connection_open=False,
        )
        started = Event()

        def worker() -> None:
            nonlocal fk_violations, late_writes
            registry.task_started(trace_id)
            started.set()
            try:
                lifecycle.cancel_event.wait(timeout=1)
                lifecycle.checkpoint()
                late_writes += 1
                with sqlite3.connect(database) as connection:
                    connection.execute("PRAGMA foreign_keys=ON")
                    connection.execute(
                        "INSERT INTO message (id, conversation_id) VALUES (?, ?)",
                        (f"late-{index}", conversation_id),
                    )
            except StreamCancelled:
                pass
            except sqlite3.IntegrityError:
                fk_violations += 1
            finally:
                registry.task_finished(trace_id)

        thread = Thread(target=worker, name=f"cleanup-race-{index}")
        thread.start()
        assert started.wait(timeout=1)
        active = registry.cancel_conversation(conversation_id)
        assert len(active) == 1
        assert registry.wait_for_terminal(active, timeout_seconds=1)
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("DELETE FROM conversation WHERE id = ?", (conversation_id,))
            connection.execute("DELETE FROM conversation WHERE id = ?", (conversation_id,))
        thread.join(timeout=1)
        assert not thread.is_alive()
        assert registry.cancel_conversation(conversation_id) == ()
        assert registry.snapshot()["active_tasks"] == 0

    with sqlite3.connect(database) as connection:
        residue = connection.execute("SELECT COUNT(*) FROM conversation").fetchone()[0]
        residue += connection.execute("SELECT COUNT(*) FROM message").fetchone()[0]
    assert fk_violations == 0
    assert late_writes == 0
    assert residue == 0
