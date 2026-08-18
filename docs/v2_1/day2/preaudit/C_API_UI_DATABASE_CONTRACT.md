# C API, UI and database contract

Status: proposed contract derived from existing ChatBI boundaries and non-canonical C candidate. It becomes authoritative only after refresh against `DAY1_FINAL_SHA`.

## Invariants

1. Browser → Backend API → existing connector → local PostgreSQL/MySQL. Browser never receives a database URL or credential.
2. Every endpoint resolves a server-side session and Workspace; client identity headers are never an authentication substitute.
3. Every executable SQL string is parsed again at execution/replay time. Only one `SELECT` or `WITH ... SELECT` may reach the connector.
4. Datasource grants, schema/table/column allowlists, timeout, row limit, concurrency limit, masking, audit and Result Oracle remain mandatory.
5. C must remain inside the Data Source secondary entry; it must not create a seventh top-level navigation module or a generic database IDE.

## API contract

| Endpoint | Permission | Input | Output / persistence | Failure behavior |
|---|---|---|---|---|
| `GET /data-workspace/datasources/{id}/search` | `datasource.read` | q, kind, page/page_size | Catalog items from synced metadata only | 403 cross-workspace; bounded page |
| `GET .../{id}/relationships` | `datasource.read` | datasource ID | PK/FK relations | No foreign-workspace objects |
| `GET .../{schema}/tables/{table}/sample` | `query.ask` + datasource query grant | page/page_size | Guarded live rows, masked columns, signature | 422 on guard/execution failure; no raw error secrets |
| `POST /data-workspace/sql/format` | `query.ask` | datasource ID, SQL | SQLGlot formatted SQL | Parse error 422, no execution/history write |
| `POST /data-workspace/sql/explain` | `query.ask` + query grant | datasource ID, SQL, row_limit | WorkspaceRun with redacted plan | Guard before explain; timeout applies |
| `POST /data-workspace/sql/execute` | `query.ask` + query grant | datasource ID, SQL, row_limit | WorkspaceRun with execution/oracle/signature | Dangerous SQL recorded as rejected; business write count 0 |
| `GET /data-workspace/sql/history` | `query.ask` | optional datasource, page | Only caller Workspace+user runs | IDOR returns 403/404 consistently |
| `POST /data-workspace/sql/history/{id}/replay` | `query.ask` | run ID | New run with source lineage | Re-resolve grants/catalog and re-guard |
| `POST /data-workspace/sql/history/{id}/verify` | `answer.manage` | owner/status | VerifiedAnswer ID/signature | Only successful Oracle-passed run; audited |

## UI contract

- Entry: button on `/datasources/:id` to `/datasources/:id/workspace`; no top-level nav change.
- Tabs: Catalog, read-only SQL, My History.
- Catalog: server-side search, explicit object kind, bounded page, lazy samples, PK/FK/relationship states.
- SQL: plain V1 editor, Format/Explain/Execute, visible read-only notice, guard/oracle/status/result signature, bounded table.
- History: caller-only runs, new-run replay, Verified SQL action. No silent auto-execution on page load.
- All pages preserve 1366×768, 1440×900 and 1920×1080 usability and authenticated route guard.

## Database and migration contract

Target table: `sql_workspace_run` with IDs for Workspace, user, datasource and optional VerifiedAnswer; operation; original/normalized SQL; status; guard/execution/oracle JSON; duration/error; source lineage; created/expiry timestamps.

Migration sequencing is not frozen as `20260818_0010` until Day 1 refresh. Let `DAY1_MIGRATION_HEAD` be the head at `DAY1_FINAL_SHA`; allocate C as the next unique revision after B (B currently has none). If another workflow already owns `0010`, rename C's revision and update `down_revision`; never create multiple heads.

Downgrade drops only C-owned indexes/table after checking for retained audit/answer references. It must not delete a VerifiedAnswer merely because its source workspace run is removed; use nullable `SET NULL` linkage where appropriate.

## Frozen merge rules

- `api/router.py`: additive include only; preserve Auth/Chat/Attachment route order and dependencies.
- `models/__init__.py`: export C model without deleting Phase 2/RAG/Agent entities.
- `query/executor.py`: preserve Day1 timeout/read-only/result behavior; add `explain` through the same connection policy, not a second connector.
- `frontend/router.tsx`: add a lazy secondary route behind existing Auth guard; preserve six primary navigation modules.
- route tests: append C route assertions and retain every Phase 2 route/auth assertion.

## Rollback

Use the recorded `PRE_C_SHA` and revert C as one integration unit. If the migration was applied, first stop new C traffic, back up C run records, downgrade the C revision, then verify Phase 2 Ask/Auth/Attachment, datasource and answer-library APIs.
