# Open-source capability realization matrix — V1.1.0

ChatBI uses audited public projects in three distinct ways: published package, independent clean-room behavior, or separately governed service. A design reference is never counted as the product capability; the active ChatBI runtime and its evidence are what pass the gate.

| Capability source | Integration | Active ChatBI behavior | User/runtime entry | License/asset boundary | Rollback |
| --- | --- | --- | --- | --- | --- |
| WrenAI | clean-room | MDL mapping, dry-plan and Semantic SQL evidence | Ask / `semantic_runtime/wren.py` | selected core/sdk concepts only; no source/docs/marks | local semantic engine |
| OpenChatBI | clean-room | workspace-scoped hybrid catalog/schema linking, candidates, confidence, clarification | Ask / `semantic_runtime/openchatbi.py` | MIT provenance; no source/UI/brand | bounded local catalog |
| SuperSonic | clean-room | typed SemanticQuery for metric/dimension/time/filter/order/limit | Ask / `semantic_runtime/supersonic.py` | no source-derived distribution | local semantic engine |
| IBM Text-to-SQL toolkit | clean-room | execution-result comparison, multiple ground truths, diff/error analysis and release gate | Evaluation Center / `evaluation/ibm_adapter.py` | Apache-2.0 provenance; no benchmark bundle | Result Oracle |
| SQLBot | clean-room | feedback, correction, review, Verified SQL, similar recall and guarded replay | Evaluation/Feedback / `feedback_loop.py` | modified GPL reference-only; no code/UI/text/logo | disable promotion |
| Chat2DB | clean-room | PostgreSQL/MySQL tree/search/relationships/samples/workspace/history/replay/verified SQL/10M lazy load | Data Source Workspace | custom-license reference-only; no package/service/container/UI | remove workspace feature/migration |
| DB-GPT | clean-room | bounded five-role/six-tool workflow, verification, chart, insight, artifact, retry/timeout/loop guard/partial/trace/RBAC/audit | Complex Analysis | selected MIT design provenance; embedded skills excluded | Agent mode off |
| PandasAI | clean-room | CSV/XLS/XLSX/Parquet/multi-sheet fixed DataFrame operations, chart and artifact | File Query | no import; all enterprise paths excluded | structured file route off |
| SQLGlot | package | AST parsing, authorization, normalization and enforced limit for PostgreSQL/MySQL | all SQL paths / `query/sql_guard.py` | MIT package, pinned 30.17.0 | fail closed |
| Apache ECharts | package | controlled `ChartSpec` rendering | Ask/Answers/Dashboards | Apache-2.0 package; no upstream UI/logo | table fallback |
| Legacy project-two RAG contract | service | signed identity, ACL/scenario filtering, hybrid retrieval/rerank, citation/answer guard | Knowledge/Hybrid | production source and private payloads copied=0 | RAG off/governed fallback |
| Legacy Agent/Tool/Trace/RBAC/Audit concepts | clean-room | project-owned bounded orchestration assets | Complex Analysis | design inventory only; no production source | Agent mode off |

Exact SHAs, path-level licenses, checksums, allowed/forbidden paths, fallback and rollback are machine-readable in `docs/UPSTREAM_LOCK.json`. Dependency SBOMs and the final legal engineering decision are in `docs/sbom/` and `docs/OPEN_SOURCE_LICENSE_AUDIT.md`.
