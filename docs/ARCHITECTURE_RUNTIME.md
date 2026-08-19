# V1.1.0 runtime architecture

## Deployed processes

Docker Compose starts exactly three containers and no database container or database volume:

| Process | Container | Responsibility | Health |
| --- | --- | --- | --- |
| Web | `frontend` | React/Vite-built static UI; talks only to Backend API | HTTP health |
| Product API | `backend` | FastAPI, authentication, conversations, routing, semantic/NL2SQL, SQL safety/execution/Oracle, file analysis, bounded Agent, evaluation, audit | `/health` |
| Governed knowledge runtime | `rag-runtime` | HMAC identity verification, ACL/scenario filtering, hybrid retrieval/rerank and governed citations | `/health` on internal port 8001 |

PostgreSQL and MySQL are user-local services. PostgreSQL stores ChatBI metadata and is the primary development/test business source; MySQL is the compatibility source. Browsers never receive database credentials and never connect directly.

`AGENT_RUNTIME` and `SANDBOX` are intentional in-process runtimes inside `backend`, not missing containers. The Agent is a bounded state machine with five fixed roles and six fixed tools. The file “sandbox” is a non-executable fixed-operation interpreter; it has no shell, generated Python, host filesystem, provider secret, database credential, or network surface. `/api/v1/chat/stream/diagnostics` exposes active SSE, background, Agent, and file-analysis task counters for leakage gates.

## Request and evidence flow

1. An HttpOnly server session resolves a persisted user, workspace, role, and resource grants.
2. `Conversation` and `Message` persist the request and bounded short-term context. A server-generated Trace ID is returned on every API response and all SSE envelopes.
3. `QuestionRouter` chooses `GENERAL_CHAT`, `DATA_QUERY`, `KNOWLEDGE_QUERY`, `HYBRID_ANALYSIS`, `COMPLEX_ANALYSIS`, `FILE_QUERY`, `MULTIMODAL_QUERY`, `SQL_WORKSPACE`, `EVALUATION`, `FEEDBACK`, `CLARIFICATION`, or `UNSUPPORTED`.
4. Route-specific execution creates public evidence only; private model reasoning is never persisted or displayed.
5. Results, citations, charts, insights, artifacts, answers, dashboard cards, evaluation cases, and audit events bind back to the Trace ID and governed source identifiers.

## Mandatory data path

`DATA_QUERY` always uses:

```text
workspace/role-scoped OpenChatBI-compatible catalog and schema linking
→ SuperSonic-compatible SemanticQuery
→ Wren-compatible MDL/dry-plan/Semantic SQL
→ SQLGlot AST Guard and authorization
→ read-only QueryExecutor with timeout/row/concurrency/cancel limits
→ Result Oracle
→ IBM-compatible evaluation evidence
```

The semantic cache is bounded and its key includes workspace, role, semantic version, knowledge version, data version, and input signature. `LocalSemanticEngine` is an explicit incident rollback only; it is not the default/shadow release path.

## Knowledge, hybrid, and complex paths

- `KNOWLEDGE_QUERY`: signed Live RAG bridge → workspace/user/role/scenario ACL → hybrid BM25/vector/RRF/rerank → document/version/chunk/locator citation → Answer Guard.
- `HYBRID_ANALYSIS`: bounded planner → the same guarded data path → governed RAG → result/citation verification → evidence merge.
- `COMPLEX_ANALYSIS`: Planner, DataAnalyst, Knowledge, Verification, and Insight roles; only `QUERY_DATA`, `RETRIEVE_KNOWLEDGE`, `VERIFY_RESULT`, `VERIFY_CITATION`, `GENERATE_CHART`, and `GENERATE_INSIGHT`; budgets 8 steps/12 calls/2 replans/depth 2/30 seconds. The ToolExecutor has no direct connector.

## File and multimodal path

Uploads are authenticated and scoped by workspace, user, and conversation. Extension, signature/MIME, size, emptiness, archive integrity, filename, prompt-injection, and image decode checks fail closed. Structured files use whitelisted filter/aggregate/join/segment/trend/TopN operations against capped extracted data. Documents and images use their governed route, and artifacts remain authenticated. Deleted or foreign attachment IDs cannot be reused.

## Streaming and cancellation

The SSE sequence is `accepted → stage/progress/heartbeat* → completed/result | error | cancelled → stream close`. Token/user and conversation ownership are checked by one joined metadata read in FastAPI's bounded synchronous worker pool. The response body uses a thread-safe queue and Starlette's reusable synchronous-stream workers, while a separate bounded pool permits at most 6 CPU/DB-heavy business jobs. Every request still checks token hash, revocation, expiry, user status, workspace, role, and conversation owner—there is no authentication-result cache. Idle streams emit a heartbeat every 0.5 seconds, and the Backend HTTP keep-alive is 30 seconds to prevent stale-connection races for normal reused clients. `accepted` is flushed before worker execution, heartbeat gaps are bounded, disconnect state propagates through integration, Agent tools, QueryPipeline, and PostgreSQL cancellation. Stop/retry create auditable requests and all lifecycle counters must return to zero.

## Rollback boundaries

- Semantic incident: `CHATBI_SEMANTIC_RUNTIME_MODE=local`.
- Knowledge incident: `CHATBI_RAG_MODE=off` or governed fallback.
- Complex Agent incident: `CHATBI_AGENT_MODE=off`; deterministic `DATA_QUERY` remains available.
- Parser/file incident: disable only the affected file route; never enable code execution.
- Schema release incident: follow `docs/releases/V1_1_0_ROLLBACK.md`; metadata migrations are downgraded explicitly and business demonstration schemas are recreated only from the fixed seed.
