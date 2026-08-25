from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Event, Thread

import pytest

from app.model_gateway.normalization import (
    ProviderResponseNormalizationError,
    normalize_chat_completion,
)
from app.query.contracts import SecurityPolicy
from app.query.nl2sql_response import (
    Nl2SqlResponseNormalizationError,
    normalize_nl2sql_response,
)
from app.query.sql_guard import SqlGuard
from app.streaming.lifecycle import StreamCancelled, StreamRegistry


FIXTURES = Path(__file__).parent / "fixtures" / "provider_responses"


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
