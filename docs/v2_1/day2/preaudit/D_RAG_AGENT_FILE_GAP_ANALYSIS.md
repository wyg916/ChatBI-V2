# D RAG / Agent / File gap analysis

Scope: read-only audit of ChatBI Phase 2, the old-project frozen commit `b6be894a7153f7ce8d31dfc65da7222bd7af1b5f`, and the empty local D placeholder branch. No D business code was changed.

The existing `codex/v2.1-rag-agent-file` branch is clean at Phase 2 SHA and contains no D delta. It is not a formal input and is the wrong base for future Day 2 work.

## RAG

| Capability | CURRENT_CAPABILITY | REUSABLE_ASSET | MISSING_CAPABILITY | UPSTREAM_OPTION / LICENSE_PATH | CLEAN_ROOM_REQUIRED | TARGET_USER/RUNTIME_ENTRY | FROZEN_ZONE_INTERSECTION | MIGRATION_REQUIRED | SECURITY_RISK / TEST_REQUIRED |
|---|---|---|---|---|---|---|---|---|---|
| Parser/chunker | ChatBI has attachment document parsers and seeded knowledge chunks, not a governed RAG ingestion product | Old project parser/chunker behavior at frozen commit | Approved-source-only ingestion entry and lifecycle | Old repo has no root license | YES | Ask attachment/approved knowledge ingestion → RAG adapter | attachments, RAG service, models | Existing knowledge tables may suffice | Zip/PDF bombs, injection; parser corpus |
| ACL | PRESENT | ChatBI `knowledge_acl`, HMAC identity, Workspace mapping | Optional scenario dimension without creating generic KB platform | ChatBI-owned | No | `KNOWLEDGE_QUERY` live bridge | RAG contracts/runtime/service | Maybe additive scenario field | unauthorized retrieval 0 |
| BM25 | MISSING in ChatBI runtime (`token_rank_v1`) | Old project `equivalent_bm25_v1` design | Real named lexical scorer and evidence | Old repo unlicensed | YES | RagAdapter internal | RAG service/contracts | Index metadata may need revision | Golden 120 recall |
| Vector | MISSING in ChatBI runtime (`NOT_REQUIRED_DETERMINISTIC_V1`) | Old feature-hash vector is design reference, not pgvector | Decide deterministic vector vs approved embedding provider | Old repo unlicensed; published provider terms separate | YES for old code | RagAdapter internal | config/requirements/runtime | likely index columns/table | embedding version/isolation |
| RRF/Rerank | MISSING in ChatBI runtime | Old hybrid RRF/reranker behavior | ChatBI-owned deterministic fusion/rerank | Old repo unlicensed | YES | RagAdapter internal | RAG service/contracts | run evidence fields may extend | stable ranking tests |
| Citation/Answer Guard | PRESENT | ChatBI citation verifier, locator identity, answer guard | User-visible citations are not explicitly rendered in Chat UI | ChatBI-owned | No | Ask answer citation panel | Ask UI/types/chat service | No | citation accuracy ≥0.95 |
| Knowledge Golden | PRESENT historical/current evidence | Golden 120 runner and provenance-only old fixtures | Rerun on Day1+D SHA | Old payload not redistributable | YES for fixtures/content | Evaluation gate | scripts/evidence | No | 120 cases, unauthorized 0 |
| Prompt injection | PRESENT basic regex/ingestion guard | Old governance tests as design | Structured adversarial corpus and parser-layer quarantine | Old repo unlicensed | YES | ingestion + retrieval + verifier | RAG adapter/runtime | audit fields maybe existing | injection publish count 0 |
| Workspace isolation | PRESENT | Signed Workspace/user/role context and ACL-before-materialization | Refresh against Auth/Conversation changes | ChatBI-owned | No | all RAG routes | auth/rag/chat frozen files | No | cross-workspace leak 0 |
| Scenario isolation | UNKNOWN/MISSING explicit ChatBI field | Old scenario isolation design | Only if required for approved business domains; avoid generic scenarios platform | Old repo unlicensed | YES | controlled knowledge profile | knowledge models/runtime | Possibly | cross-scenario leak 0 |
| Failure fallback | PRESENT | Fail closed or verified-data partial fallback | UI must label partial/no evidence consistently | ChatBI-owned | No | Chat response | integration/chat/UI | No | no fabricated citation |
| Frontend citations | MISSING product rendering | Chat message response already carries evidence | Citation card with document/version/chunk/locator and verification | ChatBI-owned | No | Ask answer below conclusion | AskExperience/types/chat | No | browser citation assertions |

## Agent / DB-GPT / legacy assets

| Capability | CURRENT_CAPABILITY | REUSABLE_ASSET | MISSING_CAPABILITY | UPSTREAM_OPTION / LICENSE_PATH | CLEAN_ROOM_REQUIRED | TARGET_ENTRY | FROZEN_ZONE_INTERSECTION | MIGRATION_REQUIRED | SECURITY_RISK / TEST_REQUIRED |
|---|---|---|---|---|---|---|---|---|---|
| Planner/workflow/graph state | PRESENT as finite ChatBI state machine | Fixed five roles and deterministic assignments | No generic graph, dynamic planner or autonomous loop is allowed | DB-GPT MIT root only as later path-level reference; old repo lacks full runtime | YES for any copied idea | `COMPLEX_ANALYSIS` only | agent contracts/runtime/service | Existing orchestration tables | steps≤8, trace 100% |
| Tool/Skill | PRESENT six fixed tools; no Skill market | Existing ToolExecutor and old allowlist design | Dynamic tool/skill registration prohibited | DB-GPT/old paths reference-only | YES | ToolExecutor internal | tool executor/contracts | Existing tool tables | unauthorized calls 0 |
| SQL tool | PRESENT | QueryPipeline through Guard/Executor/Oracle | None beyond Day1 semantic refresh | ChatBI-owned | No | `QUERY_DATA` | QueryPipeline frozen paths | No | bypass 0 |
| Python tool | MISSING and not generally allowed | None safe in ChatBI | File-only sandbox executor if D file product requires it; never arbitrary Agent Python | PandasAI community MIT paths only; `ee/**` forbidden | YES | `FILE_QUERY`, not general Agent | attachments/chat/compose | likely analysis job/artifact | sandbox escape corpus |
| Sandbox | MISSING for dataframe execution | Attachment validation/TTL is not a compute sandbox | Dedicated disposable container, no network/host mounts/credentials | Do not copy PandasAI enterprise; Docker runtime project-owned | YES | FileAnalysisAdapter | compose/requirements/attachments | likely | escape/resource limits |
| Trace/RBAC/Audit | PRESENT | Orchestration run/step/tool call tables and Phase 2 principal | File-analysis trace/artifact linkage | ChatBI-owned | No | analysis and file routes | models/service/chat | likely additive link | trace 100%, IDOR 0 |
| Retry/timeout/loop guard | PRESENT for RAG/Agent budgets | 1 retry, 30s, step/tool/replan/depth bounds | Sandbox-specific CPU/RAM/output bounds | ChatBI-owned | No | runtime executors | config/runtime | No | timeout/leak tests |
| Partial result | PRESENT verified-data-only fallback | Existing `PARTIAL` semantics | Unified UI wording and artifact status | ChatBI-owned | No | Chat response | chat/UI/types | No | unverified claim 0 |
| Report/artifact | Chart/narrative exists; file artifact lifecycle MISSING | Existing ChartSpec/VerifiedAnswer | Workspace-scoped downloadable artifact with TTL/hash/provenance | ChatBI-owned | No | File answer/artifact card | chart/content/attachments/UI | YES likely | artifact IDOR/download leak 0 |

## File / PandasAI

| Capability | CURRENT_CAPABILITY | REUSABLE_ASSET | MISSING_CAPABILITY | UPSTREAM_OPTION / LICENSE_PATH | CLEAN_ROOM_REQUIRED | TARGET_ENTRY | FROZEN_ZONE_INTERSECTION | MIGRATION_REQUIRED | SECURITY_RISK / TEST_REQUIRED |
|---|---|---|---|---|---|---|---|---|---|
| CSV/XLS/XLSX/Parquet | PRESENT upload/parse/preview/describe | Phase 2 11-type attachment path | Large-file streaming and sandbox transfer | Pandas/published parsers existing; PandasAI only reference | YES for PandasAI behavior | Chat composer → FILE_QUERY | attachments/chat/requirements | Maybe job table | file signature/size tests |
| DataFrame/statistics | PRESENT basic describe | Extracted payload | Governed operations, reproducible code/plan and result verification | PandasAI community MIT candidate; no `ee/**` | YES | FileAnalysisAdapter | services/chat | YES | formula/code injection |
| Multiple sheets | MISSING (default first sheet only) | Old project XLSX sheet listing design | Explicit sheet selection and per-sheet schema | Old repo unlicensed; openpyxl existing | YES for old code | Attachment detail / follow-up | attachments/UI/types | payload extension | sheet isolation tests |
| Join | MISSING | Query/semantic join concepts | Attachment-to-attachment join only with explicit keys and budgets | Project-owned | No | FILE_QUERY | chat/service | job plan | Cartesian explosion |
| Chart/artifact | Query chart present; file chart/artifact MISSING | ECharts ChartSpec and content models | File-result ChartSpec + downloadable CSV/PNG/JSON | Project-owned | No | Chat result | chart/UI/content | artifact table likely | content-type/IDOR |
| Docker sandbox | MISSING | Compose has service isolation patterns | Disposable no-network worker, read-only root, tmpfs, non-root | Project-owned | Yes | File executor | compose/env/requirements | No metadata revision by itself | escape tests |
| CPU/RAM/time/output limits | MISSING | Agent time limit only | Suggested hard caps: 1 CPU, 512 MiB, 30s, 10 MiB output, 100k rows | Project-owned | No | sandbox policy | config/compose | policy metadata optional | resource bomb tests |
| Network and credential isolation | MISSING explicit file sandbox | Agent ToolExecutor declares no network/direct DB | Sandbox network none; no host env, DB/RAG/model secrets or Docker socket | Project-owned | No | sandbox runtime | compose/env | No | egress/secret probe 0 |
| Workspace file isolation | PRESENT for upload/storage | Attachment Workspace+user+conversation IDs and TTL | Extend through jobs/artifacts and sandbox staging | ChatBI-owned | No | Attachment/Artifact APIs | attachments/models/chat | YES for job/artifact | cross-user/workspace/conversation leak 0 |

## Phase 2 protection and implementation order

Protected capabilities: Conversation, Short-term Memory, Attachment, Document Query, Image Query, Multimodal, SSE, Authentication, Session, Workspace and Chat UI. Likely HIGH_CONFLICT surfaces include `services/attachments.py`, `services/chat.py`, chat/attachment schemas/models/routes, `AskExperience.tsx`, `api/chat.ts`, `types/api.ts`, RAG/Agent packages, `integration/service.py`, `tool_executor.py`, `docker-compose.yml`, `.env.example` and `backend/requirements.txt`.

`IMPLEMENTATION_ORDER`: Day1 refresh → protect Chat/Attachment contract tests → user-visible citation rendering → controlled RAG ranking gaps only if Golden requires them → file job/artifact metadata → sandbox boundary → multi-sheet/statistics/join/chart → Agent integration only through fixed File route/tool policy → targeted/Golden/security → Phase 2 full regression.

`ROLLBACK`: record `PRE_D_SHA`; disable new D traffic only for incident containment (not a releaseable state), revert D integration commit, stop/remove disposable sandbox service, preserve existing Attachment/Conversation/Knowledge/Orchestration records, and downgrade only D-owned job/artifact tables after backup.

`D_CODE_CHANGED=NO`
