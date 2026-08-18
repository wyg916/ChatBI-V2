# C Data Workspace upstream and boundary audit

Audit date: 2026-08-18

## Decision

`IMPLEMENTATION_MODE=CLEAN_ROOM_EQUIVALENT`

Chat2DB was inspected only to confirm user-facing capability categories. The current upstream license contains restrictions for external products, managed delivery, embedded products, white-label/OEM delivery, and object-form distribution. ChatBI therefore does not import, vendor, fork, call, embed, redistribute, or copy any Chat2DB source or asset. The implementation in this branch is independently authored from ChatBI requirements and existing project contracts.

## Upstream lock

- Repository: `https://github.com/OtterMind/Chat2DB` (the former CodePhiliaX URL resolves to this repository).
- Branch: `main`.
- Commit: `5372213f267a087c232cb86cae4b200e00c3389f`.
- Historical comparison tag: `v0.3.7` at `698323ae831e7471fab348677c768eece619d064`.
- Root license identifier: `LicenseRef-Chat2DB` for 5.3.0+.
- Root license SHA-256: `30efd4500ecc4c19eec9dadd09e4a6b34585eb631c13e5edc4c459924f336ea7`.
- Subdirectory license found in selected paths: none.
- File-header license override found in selected paths: none observed; root terms govern.

Selected reference-only paths and SHA-256:

| Path | SHA-256 | Review purpose |
| --- | --- | --- |
| `README.md` | `89020b2f11789809ba0718a81d6a711179a2ea0a5118090774def9be0e463ed2` | Public feature categories and security boundary |
| `chat2db-community-client/src/pages/main/workspace/index.tsx` | `14f949b62e23581c0b064c3950c47f7aaad48623693bc716d05d2ea1e8e60fff` | Workspace information architecture only |
| `chat2db-community-client/src/service/history.ts` | `e1608a8b403db10f2a8b785330a70b45aa6daf40e8ce81d52031ae4b8e6883dd` | History capability existence only |
| `chat2db-community-server/chat2db-community-storage/src/main/java/ai/chat2db/community/storage/large/ConsoleStorage.java` | `a44fad8f893f90ef852ef36cf5bc3f174db744254b89871d3e1e0a6e7bbfa5d3` | Persistence category only |
| `chat2db-community-server/chat2db-community-domain/chat2db-community-domain-core/src/main/java/ai/chat2db/community/domain/core/impl/db/DbTableServiceImpl.java` | `5cf15f47c8624466d9908135fc7fb95cf644c4d2d450783ea7edaa43b3ceacc2` | Metadata browsing category only |

## ChatBI differential implementation

The branch adds a ChatBI-owned Data Workspace page and API for PostgreSQL/MySQL catalog search, relationships, primary/foreign keys, lazy sample pages, SQL formatting, explain, guarded execution, per-user history, replay, and Verified SQL persistence. Every executable statement follows:

`authenticated session -> workspace/resource permission -> SQLGlot Guard -> QueryExecutor read-only transaction -> ResultOracle/read-only result validation -> audit/history`

Sensitive column names are masked in sample responses. History is filtered by both Workspace and user. The browser receives no database credential and never connects to a database.

## Impact and rollback

- Frozen-zone intersection: minimal route/model/executor/router-test deltas; no Phase 2 file is wholesale replaced.
- Migration impact: adds `20260818_0010` and table `sql_workspace_run` only.
- API impact: additive `/api/v1/data-workspace/*` routes.
- License impact: notice/audit only; no new runtime dependency.
- Rollback: remove the additive frontend route/link, omit the Data Workspace router, and run `alembic downgrade 20260818_0009`. Existing QueryPipeline, Phase 2 chat, answers, dashboards, evaluation, and datasource metadata remain intact.
