# D runtime and security contract

Status: design contract only; must be refreshed against `DAY1_FINAL_SHA`.

## Route ownership

- `DATA_QUERY`: deterministic Day1 QueryPipeline only.
- `KNOWLEDGE_QUERY`: authenticated Live RagAdapter → ACL-before-materialization → ranking → CitationVerifier → Answer Guard.
- `HYBRID_ANALYSIS`: merge only Oracle-passed data and citation-verified knowledge.
- `COMPLEX_ANALYSIS`: existing fixed five roles and six tools; no dynamic tool, Skill or graph registration.
- `FILE_QUERY`: AttachmentParser for preview plus a separate bounded FileAnalysisAdapter when computation is required.
- `MULTIMODAL_QUERY`: retain Phase 2 Vision path; D file compute must not capture image requests implicitly.

## Identity envelope

Every RAG, Agent, File job and artifact carries immutable `workspace_id`, `user_id`, `conversation_id`, `message_id`, `attachment_ids`, `trace_id`, allowed datasource/model/tool sets and budget. The backend resolves these fields from the server session and stored resources; a client-provided ID is only a lookup key and must match ownership.

## RAG contract

Candidates are filtered by Workspace/role/approved source before their text is materialized. Ranking stages record algorithm/version/score without exposing unauthorized candidates. Citations include document, version, chunk, source and locator. Empty or failed verification yields `REFUSED` or an explicitly labelled verified-data-only `PARTIAL`; it never yields a citation-free knowledge claim.

The Chat UI renders citations as data, not interpolated HTML, and does not expose raw filesystem paths, secrets or private prompt content.

## Agent contract

Roles remain exactly Planner, Data Analyst, Knowledge, Verification and Insight. Tools remain exactly Query Data, Retrieve Knowledge, Verify Result, Verify Citation, Generate Chart and Generate Insight unless the fixed V1 contract is explicitly revised; a file executor is invoked by FILE_QUERY orchestration, not registered as arbitrary Python for agents.

Hard limits remain steps 8, tool calls 12, replans 2, depth 2 and total time 30 seconds. The Agent receives neither connectors nor database URLs. Query Data always executes the refreshed Day1 context/NL2SQL/Guard/Executor/Oracle chain.

## File sandbox contract

The Backend validates extension, MIME, signature, size, Workspace/user/conversation ownership and hash before staging an attachment. Compute runs in a disposable, non-root container with:

- no network and no Docker socket;
- read-only root filesystem and a per-job tmpfs/work directory;
- only selected attachment copies mounted read-only;
- no host environment, home directory, database/RAG/model credentials or shared attachment directory;
- one CPU, 512 MiB memory, 30-second wall clock, 10 MiB combined output, at most 100,000 rows and bounded chart/artifact count;
- process/file-descriptor limits and forced termination/cleanup.

Only an allowlisted project-owned dataframe plan may execute. Arbitrary imports, filesystem paths, shell/process calls, sockets, reflection/code loading and user-supplied Python are rejected.

## Persistence contract

Existing knowledge/orchestration/attachment tables remain authoritative. If D requires persistence, add only:

- `file_analysis_run`: identity envelope, plan hash, budgets, status, trace, input hashes, timestamps/errors.
- `file_analysis_artifact`: run/Workspace/user/conversation ownership, type, safe storage key, MIME, size, SHA-256, TTL.

Do not store raw credentials, host paths, generated Python, model private reasoning or whole source files in metadata JSON. Artifact download rechecks session and all scopes.

## Failure and rollback

Timeout, parser rejection, resource exhaustion, missing evidence and sandbox failure are typed failures. Verified partial data may be returned only when its own Oracle/guard passes. Incident flags may stop RAG/Agent/File traffic but an off state does not satisfy the release gate.

Rollback is a revert of the D integration unit plus safe removal of D-only job/artifact metadata after backup. Phase 2 attachment bytes, Conversation/Message, Knowledge/Citation and Orchestration history must not be overwritten.
