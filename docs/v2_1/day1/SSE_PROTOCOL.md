# Day 1 unified SSE protocol

Every authenticated question starts as SSE immediately; the backend does not execute a complete request before emitting `accepted`. The same envelope is used for DATA_QUERY, KNOWLEDGE_QUERY, HYBRID_ANALYSIS and COMPLEX_ANALYSIS.

Required envelope fields:

`trace_id`, `sequence`, `event`, `timestamp`, `elapsed_ms`, `capability`, `message`, `data`

Events:

`accepted`, `catalog_retrieving`, `schema_linked`, `semantic_parsing`, `semantic_compiling`, `sql_validating`, `sql_running`, `result_validating`, `knowledge_retrieving`, `agent_running`, `python_running`, `answer_delta`, `chart_ready`, `completed`, `error`, `cancelled`, `heartbeat`.

Lifecycle rules:

- `accepted` is the first event and is emitted before the worker result is available.
- A heartbeat is emitted after 2.5 seconds without another public event.
- Event sequence is monotonic within one trace. Events contain public stage evidence only, never private reasoning.
- Browser abort closes the connection, sets the cooperative cancellation flag, and the worker checks it at public progress boundaries.
- Aggregate diagnostics expose only active connection/task counts and trace IDs; request content is never exposed.
- `/api/v1/chat/stream` and `/api/v1/chat/stream/diagnostics` require `query.ask`; anonymous requests return 401.
- Cache, conversation, attachment and stream lifecycle state remains scoped by authenticated workspace/user/conversation boundaries.

Frontend behavior remains Phase 2 compatible: fixed-bottom Composer, independently scrolling messages, stop via `AbortController`, retry, return-to-latest, incremental stage display, chart readiness and explicit errors.

Rollback: revert the Day 1 streaming commit; no database migration is involved.
