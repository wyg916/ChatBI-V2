# C Data Workspace gap analysis

Scope: read-only comparison of the audit base (`cceeb1c...` / Phase 2 business tree) and the observed non-canonical candidate `codex/v2.1-data-workspace` at `9e2525c84ee2ef72e849f4020bbd8085af4d9a84`. No C code was changed or merged.

The candidate is clean and contains one commit based directly on Phase 2, but `V2_1_INTEGRATION_INPUT_MATRIX.md` still says `C_INPUT_STATUS=NOT_PROVIDED`. It is therefore a reusable candidate, not a formal Day 2 input, and cannot be used as the Day 2 base.

## Capability matrix

Legend: `BASE` = available at audit base; `CANDIDATE` = implemented only on non-canonical `9e2525c`; `MISSING` = no complete product path found.

| Capability | CURRENT_CAPABILITY | REUSABLE_ASSET | MISSING_CAPABILITY | TARGET_USER_ENTRY | FROZEN_ZONE_INTERSECTION | MIGRATION_REQUIRED | SECURITY_RISK | TEST_REQUIRED |
|---|---|---|---|---|---|---|---|---|
| Data-source tree | BASE partial | Datasource detail schema/table tree | Large-catalog tree virtualization | Data source detail / Data Workspace | `frontend/src/router.tsx` if new route | No | Catalog enumeration | 79-table and access tests |
| PostgreSQL Explorer | BASE | SQLAlchemy inspector, catalog tables | Search/paging UX | Data Workspace catalog | Router/model/query executor | No | Cross-workspace metadata | PG real E2E |
| MySQL Explorer | BASE | Same connector abstraction | Equivalent C end-to-end evidence beyond basic catalog | Data Workspace catalog | Same | No | Dialect/object authorization | MySQL real E2E |
| Schema/Table/Column search | CANDIDATE | Additive search API with kind/page/page_size | Server-side total currently materializes all matches before slicing | Catalog search | API router/models | No | Wildcard/large response abuse | Search pagination/perf |
| Relationship and PK/FK | BASE/CANDIDATE | Synced relation, column PK/FK flags | Composite-key UX and unresolved relationship state | Catalog/relationship panel | Models/router | No | Metadata leakage | Composite FK tests |
| Sample values | BASE metadata; CANDIDATE live | Guarded sample API + masking | Policy-driven sensitivity labels; current masking is name-regex only | Sample panel | Query executor | No | Sensitive value disclosure | Mask, pagination, no-write tests |
| Pagination | CANDIDATE | Search/sample/history page contracts | Stable cursor/keyset option for very large histories | All C panels | None direct | No | Offset amplification | Boundary/load tests |
| Lazy loading | CANDIDATE | User-triggered sample fetch | Cancel/stale-request handling | Sample panel | Frontend route | No | Accidental large scan | Browser network assertions |
| 10M table browsing | CANDIDATE evidence | 50-row samples from benchmark | Final-SHA reproducibility and p95 gate | Data Workspace | Query executor | No | Full scan/timeout | 10M p95 and truncation |
| Read-only SQL Workspace/Editor | CANDIDATE | Additive page, textarea editor, API | Production editor ergonomics are minimal; acceptable for V1 if safe | `/datasources/:id/workspace` | Router, query executor | Yes, history table | SQL injection/write attempts | PG/MySQL guarded E2E |
| SQL Format | CANDIDATE | SQLGlot dialect formatting | Comments/parse error UX matrix | SQL toolbar | Query executor indirectly | No | Parser differential | Dialect cases |
| SQL Explain | CANDIDATE | `QueryExecutor.explain` path | Explain-plan sensitive-field redaction and timeout evidence | SQL toolbar | Query executor | Yes, shared history | Expensive EXPLAIN/ANALYZE | Explain allowlist tests |
| SQL Execute | CANDIDATE | SQLGlot Guard → executor → Oracle | Final Day1 semantic/security compatibility | SQL toolbar | `backend/app/query/executor.py` | Yes | DDL/DML/COPY/multi-statement | 38+ dangerous cases |
| Query history | CANDIDATE | Workspace+user-scoped `SqlWorkspaceRun` | Retention/purge policy | History tab | Models init/router | Yes (`sql_workspace_run`) | SQL text retention | Isolation/retention tests |
| History replay | CANDIDATE | Re-guards and re-executes stored SQL | Explicit source-run lineage field | History action | Query executor | Yes | Stale grants/schema drift | Revoke-then-replay denial |
| Verified SQL save | CANDIDATE | Writes VerifiedAnswer after success | Review semantics and B feedback compatibility | Result/history action | Answer model via route/model init | Yes | Self-verification privilege | Role/replay/oracle tests |
| SQLBot/answer-library bridge | BASE answer library; CANDIDATE save | Existing VerifiedAnswer and B feedback candidate model | B/C canonical contract reconciliation | Answer library | `frontend/src/types/api.ts` via B, not C currently | No extra beyond C | Poisoned verified examples | B+C recall tests |
| Sensitive-field masking | CANDIDATE partial | Name-regex response masking | Semantic/classification-based masking and nested/result/export coverage | Sample/results | Query executor response | No | PII exposure | Positive/negative masking |
| RBAC | BASE/CANDIDATE | `datasource.read`, `query.ask`, `answer.manage` | Exact Analyst/Admin C policy matrix | Entire workspace | Core access indirectly | No | Permission confusion | Role matrix |
| Workspace isolation | BASE/CANDIDATE | Datasource ownership and run workspace/user filters | All B-integrated feedback/detail endpoints must match | Entire workspace | Models/router | Yes | IDOR | Cross-workspace IDs |
| SQLGlot Guard | BASE/CANDIDATE | Existing `SqlGuard` and policy | Refresh against Day1 semantic/query changes | Execute/explain/replay/sample | `backend/app/query/executor.py` | No | Parser bypass | Dialect security corpus |
| Dangerous SQL block | BASE/CANDIDATE | Single SELECT/CTE allowlist | Expand C-specific explain/replay corpus | SQL Workspace | Query executor | No | Business DB write | 100% blocked; writes 0 |
| Browser E2E | CANDIDATE | One real 10M loop | MySQL, auth failure, pagination, IME/Chat regression, dynamic ports | Browser | Playwright/route surfaces | No | False PASS from seeded auth | Serial authenticated E2E |

## Target API and database

The candidate's additive API is a reasonable reusable asset: catalog search, relationships, samples, format, execute, explain, history, replay and verify under `/api/v1/data-workspace/*`. The target persistent table is `sql_workspace_run`; existing `datasource_*`, `query_audit_event` and `verified_answer` remain authoritative and must not be duplicated.

## Frozen-zone intersection

The candidate commit changes 25 files and intersects five frozen paths:

- `backend/app/api/router.py`
- `backend/app/models/__init__.py`
- `backend/app/query/executor.py`
- `frontend/src/router.tsx`
- `frontend/src/test/routes.test.tsx`

It also adds migration `20260818_0010_data_workspace.py`. Because the candidate is based on Phase 2 rather than future `DAY1_FINAL_SHA`, its revision number and parent are provisional.

## License impact

The candidate records Chat2DB commit `5372213f267a087c232cb86cae4b200e00c3389f` under a custom `LicenseRef-Chat2DB` for current upstream. Chat2DB is reference-only; no source, UI, logo, prompt or asset may be copied or embedded. C is a ChatBI-owned clean-room equivalent using existing SQLGlot/SQLAlchemy/React dependencies and introduces no new package.

## Implementation order and rollback

`IMPLEMENTATION_ORDER`: refresh Day1 contracts → intake candidate SHA/tree/tests/license → reconcile migration ID → backend models/migration → catalog APIs → guarded execute/explain/history → Verified SQL/B bridge → UI → targeted/security/E2E → Phase 2 regression.

`ROLLBACK`: record `PRE_C_SHA`; revert the single C integration commit; downgrade only the reconciled C migration after backup/usage check; leave Datasource, QueryRun, VerifiedAnswer and Phase 2 records intact.

`C_CODE_CHANGED=NO`
