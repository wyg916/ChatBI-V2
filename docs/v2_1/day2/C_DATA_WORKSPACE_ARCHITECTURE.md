# C Data Workspace Architecture

- Status: PASS
- Tested code SHA: `b766275bd4cff015312b1d0fbdbae26d81611d71`
- Base / POST_B SHA: `f117991e0722f1ee6e505f74d3eeeee85399af7d`
- Executed at: `2026-08-19T01:42:56+08:00`

## Product path

The user enters the Data Workspace from the existing datasource detail page at `/datasources/:id/workspace`. The page exposes the real PostgreSQL/MySQL catalog, Schema/table/column search, primary/foreign-key metadata, relationships, lazy sample pages, a read-only SQL editor, Format, Explain, Execute, result evidence, per-user history, replay, and Verified SQL save.

The browser calls only Backend API routes. It never receives a database host credential, password, encrypted password, provider key, or administrator secret.

## Security and execution flow

`HttpOnly authenticated session -> Principal workspace/role -> datasource resource grant -> SQLGlot AST Guard -> QueryExecutor read-only transaction -> ResultOracle -> audit + workspace/user history`

- Format parses with SQLGlot but never executes.
- Explain is constructed server-side only after the original SELECT passes the Guard; `EXPLAIN ANALYZE` is never accepted from the caller.
- Execute, sample and replay use the same bounded QueryExecutor and read-only transaction.
- Sample data is fetched only after an explicit click, with page size at most 100 and server-side OFFSET/LIMIT.
- Sensitive names such as password, token, phone, email, bank account and private key are masked in sample responses.
- History filters by both Workspace and user. Replay and verify reject foreign runs.
- Verified SQL is created only from a successful Oracle-passed guarded run and links back to the datasource and result signature.

## Contracts and persistence

- Additive API prefix: `/api/v1/data-workspace`.
- Additive ORM table: `sql_workspace_run`.
- Alembic: `20260818_0010`, single parent `20260818_0009`.
- Migration round trip: `0010 -> 0009 -> 0010`, PASS.
- Frozen Zone intersection: 5 shared files, all additive/minimal semantic merges; no RAG, Agent, attachment, auth, memory, Wren, OpenChatBI or SuperSonic runtime was replaced.
- License impact: Chat2DB is reference-only under a locked audit; no source, package, UI, container, brand or asset was copied.
- Evidence: `docs/evidence/v2_1/C_DATA_WORKSPACE_RUNTIME.json`, `artifacts/v2_1/day2/c/b-regression.json`, and `artifacts/v2_1/day2/c/phase2-runtime-acceptance.json`.
- Failures: one brittle E2E assertion assumed 18 fields while the final 10M fixture has 19; corrected to assert the real table name plus numeric field count.
- Blockers: none.
- Rollback: revert the C commit and run `alembic downgrade 20260818_0009`; no business database data changes are required.
