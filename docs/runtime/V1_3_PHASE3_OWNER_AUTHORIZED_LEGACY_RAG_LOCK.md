# V1.3.0 Phase 3 owner-authorized Legacy RAG lock

## Decision

- Source project: `E:\新能源企业经营分析智能平台`
- Source commit: `b2573a9dc1881a54581c5c556fb4a8c34046f9c3`
- Ownership: `OWNER_ATTESTED_PASS`
- External provenance audit: `NOT_REQUIRED`
- Integration mode: `SELECTED_SOURCE_INTERNAL_PACKAGE`
- Direct reuse state: `PASS_OWNER_AUTHORIZED_INTERNAL_REUSE`

The source project contains a complete modular-monolith knowledge subsystem, but its API and retrieval service depend on the old project's identity, governance and database schema. It is not a stable standalone service that can be reused without importing those second control planes. ChatBI therefore directly reuses only the minimum deterministic ranking and injection-detection source modules. The byte-identical Git blobs are stored below `backend/vendor/legacy_energy_rag/b2573a9d...`; `LOCK.json` is verified before import, and a mismatch fails closed.

## Actual path map

| Capability | Legacy implementation | Integration decision |
| --- | --- | --- |
| Retriever/runtime | `backend/app/knowledge/retrieval.py`, `backend/app/knowledge/api.py` | Audited, not copied; coupled to the old Session, audit tables and identity context |
| ACL | `backend/app/knowledge/authorization.py` | Audited, not copied; ChatBI keeps its own signed Workspace/RBAC and `KnowledgeAcl` SQL predicate |
| BM25/vector/index | `backend/app/knowledge/indexer.py` | Byte-identical selected source, real runtime calls |
| RRF/rerank | `backend/app/knowledge/reranker.py` | Byte-identical selected source, real runtime calls |
| Prompt injection | `backend/app/knowledge/security.py` | Byte-identical selected source, real runtime calls before ranking |
| Query rewrite | `backend/app/knowledge/query_rewrite.py` | Audited, not selected; its scenario glossary is old-product-specific |
| Citation | `backend/app/knowledge/citation.py` | Audited; ChatBI adapter emits its existing Citation contract and version/chunk identity |
| Answer Guard | `backend/app/knowledge/answer_guard.py` | Audited; ChatBI keeps the stricter citation-per-factual-line Answer Guard after its one Model Gateway |
| Chunk/document/index models | `backend/app/models/knowledge.py` | Audited, not copied; ChatBI remains the data owner and supplies authorized adapter objects |
| Tests | `backend/tests/test_rag_hybrid_unit.py`, `test_rag_hybrid_120.py`, `test_rag_golden_60.py` | Behavior mapped to ChatBI Knowledge20, Citation, isolation and injection gates |

## Selected file lock

| Source path | Git blob | Vendored SHA-256 |
| --- | --- | --- |
| `backend/app/knowledge/indexer.py` | `cba723f77dc5809d2689a04770ba44c62f552727` | `11cfa0775041adef174fc548f49e11d31d7ba6f0006915f040e69887b02323b6` |
| `backend/app/knowledge/reranker.py` | `0b2891ba51d6eaac9270b58d476a8a5d784a43a1` | `c299d3d64919d908963562e289aa950be9f8107ee33db76fae164b713753f738` |
| `backend/app/knowledge/security.py` | `3a59166e7669f79fcb7c713376022a7997979f2a` | `9c85db5c157c8345b63f7fb5ed9b73da094baef4ec96ca759cc37a01494df4f4` |

The Git blob IDs match the source commit exactly. SHA-256 values are calculated from the canonical LF blob bytes distributed in ChatBI; the Windows source checkout uses CRLF working-tree bytes and is not the distribution identity.

## Dependency, secret and data closure

- External dependency closure for the three selected files at runtime: Python standard library only. SQLAlchemy model names are type/import surfaces; the loader provides non-persistent adapter structures and never calls the old `index_for_chunk` database constructor.
- Secret references: none. The selected code contains no credential loading, environment-variable access, HTTP client, Provider key, authorization header or database connection.
- Data dependency: only ChatBI `KnowledgeDocument`, active version, chunk and source rows that already passed signed Workspace/user/role validation, `KnowledgeAcl`, source status and `scenario_id` filtering.
- Data isolation: the adapter does not receive datasource credentials, SQL, Conversation state, attachments, model secrets or host paths.
- Interface: `LegacyCandidate[] → legacy indexer → legacy BM25/vector/RRF/rerank → ChatBI Citation`.

## Formal runtime and rollback

`Question → ChatBI Workspace/RBAC → LiveRagAdapter/HMAC Bridge → ChatBI ACL/scenario filter → selected-source BM25 + deterministic vector → selected-source RRF/rerank → Citation → single ChatBI ModelGateway → Answer Guard → AnswerEnvelope → ChatBI SSE`.

The selected source never answers database business numbers and never creates Auth, Workspace, Conversation, Model Gateway, SQL Executor or SSE. Rollback is a normal revert of the Phase 3 successor commit; there is no schema migration or data rewrite. If lock verification or source loading fails, RAG fails closed and the existing verified QueryPipeline fallback policy remains in control.

## Deferred risks

- Sandbox Controller Docker socket: `OPEN_TECHNICAL_DEBT`; evaluate a rootless daemon or restricted socket proxy before Final Release.
- Image pre-model OCR: `NOT_IMPLEMENTED`.
- Trace granularity: `COMPLETION_RECEIPT_LEVEL`.
- ECharts chunk warning: `555.48KB`, non-blocking.
