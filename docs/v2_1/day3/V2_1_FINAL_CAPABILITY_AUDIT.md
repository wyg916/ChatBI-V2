# V2.1 final capability PRODUCT_PASS audit

This audit applies the Day 3 rule that code presence, design references, mocks, shadow routes, unit-only evidence, or historical Day 1/2 status are insufficient. The authoritative row-level record is `V2_1_FINAL_CAPABILITY_MATRIX.json`; final truth is the raw evidence manifest created under `artifacts/v2_1/final/<tested_sha>/` after the candidate SHA is frozen.

## Audit result for the release candidate

- Required capability rows: **18**.
- Default/runtime call coverage: **18/18** mapped to active product paths.
- Design-only, mock-only, demo-only, shadow-only, document-only, unit-only, no-user-entry, or no-runtime-trace rows: **0**.
- Third-party restricted source/UI/logo/brand/model/benchmark bundles copied: **0**.
- Final release decision: only the final-SHA manifest may resolve these candidate rows to release PASS. A failing final retest overrides this document and blocks release.

## Product routes

| Route | Mandatory runtime chain |
| --- | --- |
| `DATA_QUERY` | OpenChatBI-compatible catalog → SuperSonic-compatible SemanticQuery → Wren-compatible compile → SQLGlot Guard → read-only executor → Result Oracle → IBM-compatible evidence |
| `KNOWLEDGE_QUERY` | governed business definition → signed Live RAG → ACL/scenario filter → hybrid retrieval/rerank → citation and Answer Guard |
| `HYBRID_ANALYSIS` | bounded planner → guarded query → governed RAG → verified evidence merge |
| `COMPLEX_ANALYSIS` | fixed five-role/six-tool orchestration → guarded SQL → non-executable fixed file analysis where needed → RAG → verification → chart/insight/artifact |
| `FILE_QUERY` | attachment validation/isolation → fixed-operation interpreter → validated table/chart/artifact |
| `SQL_WORKSPACE` | catalog → SQLGlot Guard → explain/execute → user/workspace history → guarded verified SQL |
| `EVALUATION` | IBM-compatible result comparison → persisted diff/error analysis → dashboard/CI gate |
| `FEEDBACK` | feedback → correction → review → verified SQL → similar recall → guarded regression replay |

Every route above is exercised by the final open-question set or the 20×15-minute mixed load and must report `RUNTIME_CALL_RATE=1.0` where that metric applies.

## Equivalence findings

- **Chat2DB-equivalent:** source tree, schema/table/column search, relationships, masked samples, format/explain/execute, history/replay, verified SQL, PostgreSQL/MySQL, and 10M lazy loading use real ChatBI API/database paths.
- **DB-GPT-equivalent:** planner, fixed graph state, five agents, six-tool registry, governed prompt/skill assets, query/knowledge/verification/chart/insight/artifact, retry/timeout/loop guard/partial result, trace, RBAC, and audit are present. There is deliberately no direct database or arbitrary Python tool; guarded QueryPipeline and a non-executable fixed-operation file interpreter provide the required safer behavior.
- **PandasAI-equivalent:** CSV/XLS/XLSX/Parquet/multi-sheet, DataFrame filtering/aggregation/join/segmentation/trend/TopN, chart, and authenticated artifact paths are active. No PandasAI or enterprise path is imported.

## Final overrides

Any one of the following forces `FINAL_STATUS=PARTIAL`, `RELEASE_ALLOWED=NO`, and `FINAL_TAG_ALLOWED=NO`: a matrix row without final-SHA evidence; an open/memory/UI/auth/file failure; performance or load threshold failure; security bypass/leak/write; unknown license; failed migration/cold start; E2E below 30; dirty worktree; or local/remote candidate mismatch.
