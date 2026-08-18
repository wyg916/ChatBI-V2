import json
from threading import Thread
from time import sleep

import pytest

from app.streaming import REQUIRED_EVENTS, StreamCancelled, StreamEventFactory, event_for_stage, format_sse, stream_registry


def test_v21_stream_protocol_declares_every_required_event():
    assert set(REQUIRED_EVENTS) == {
        "accepted", "catalog_retrieving", "schema_linked", "semantic_parsing", "semantic_compiling",
        "sql_validating", "sql_running", "result_validating", "knowledge_retrieving", "agent_running",
        "python_running", "answer_delta", "chart_ready", "completed", "error", "cancelled", "heartbeat",
    }


def test_stream_event_envelope_is_monotonic_traceable_and_public():
    factory = StreamEventFactory("STREAM-test-trace")
    accepted = factory.create("accepted", capability="router", data={"route": "DATA_QUERY"})
    heartbeat = factory.create("heartbeat")
    assert accepted["trace_id"] == heartbeat["trace_id"] == "STREAM-test-trace"
    assert (accepted["sequence"], heartbeat["sequence"]) == (1, 2)
    assert accepted["elapsed_ms"] <= heartbeat["elapsed_ms"]
    assert set(accepted) == {"trace_id", "sequence", "timestamp", "elapsed_ms", "event", "capability", "message", "data"}
    assert "reasoning" not in json.dumps(accepted).lower()
    rendered = format_sse("accepted", accepted)
    assert rendered.startswith("event: accepted\ndata: ")
    assert rendered.endswith("\n\n")


@pytest.mark.parametrize(
    ("stage", "event"),
    [
        ("UNDERSTANDING", "catalog_retrieving"),
        ("SCHEMA_LINKED", "schema_linked"),
        ("SEMANTIC_PARSING", "semantic_parsing"),
        ("SEMANTIC_COMPILING", "semantic_compiling"),
        ("SQL_VALIDATING", "sql_validating"),
        ("QUERYING_DATA", "sql_running"),
        ("VERIFYING", "result_validating"),
        ("RETRIEVING_KNOWLEDGE", "knowledge_retrieving"),
        ("AGENT_RUNNING", "agent_running"),
        ("PYTHON_RUNNING", "python_running"),
        ("GENERATING_INSIGHT", "answer_delta"),
        ("CHART_READY", "chart_ready"),
    ],
)
def test_phase2_stages_map_to_v21_public_protocol(stage, event):
    assert event_for_stage(stage) == event


def test_unknown_or_private_stage_is_not_exposed():
    assert event_for_stage("CHAIN_OF_THOUGHT") is None
    with pytest.raises(ValueError):
        StreamEventFactory("STREAM-test").create("private_reasoning")


def test_stream_lifecycle_prunes_connection_and_task_after_cancel():
    trace_id = "STREAM-lifecycle-test"
    lifecycle = stream_registry.register(trace_id)
    stream_registry.task_started(trace_id)
    observed: list[str] = []

    def worker() -> None:
        while True:
            try:
                lifecycle.checkpoint()
            except StreamCancelled:
                observed.append("cancelled")
                break
            sleep(0.005)
        stream_registry.task_finished(trace_id)

    thread = Thread(target=worker)
    thread.start()
    stream_registry.connection_closed(trace_id)
    thread.join(timeout=1)
    assert observed == ["cancelled"]
    assert stream_registry.snapshot() == {"active_connections": 0, "active_tasks": 0, "trace_ids": []}
