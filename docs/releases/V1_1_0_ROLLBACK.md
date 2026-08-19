# ChatBI V2 V1.1.0 rollback

Rollback is capability-scoped first and release-wide only when necessary. Preserve evidence and backups; never expose or copy secrets, reset Git destructively, or delete local metadata/business databases as a convenience.

## Before change or release

1. Record the current commit, image IDs, Alembic head, `.env` location (not contents), PostgreSQL metadata backup, demonstration schema signature, and MySQL compatibility backup.
2. Stop new traffic and let active SSE/Agent/file tasks reach zero via diagnostics.
3. Keep the prior known-good images/commit available. Do not move the V1.1.0 tag.

## Capability rollback

| Incident | Immediate action | Data effect |
| --- | --- | --- |
| Semantic adapter | set `CHATBI_SEMANTIC_RUNTIME_MODE=local`, restart Backend | none; reduced semantic evidence |
| RAG runtime/ACL | set `CHATBI_RAG_MODE=off` or activate the governed configured fallback | knowledge/hybrid requests fail clearly or degrade according to policy; no fabricated answer |
| Bounded Agent | set `CHATBI_AGENT_MODE=off` | complex route unavailable/controlled fallback; deterministic data path remains |
| File parser/analysis | disable affected route/parser and reject the format | no code execution fallback; retain scoped metadata for audit according to retention policy |
| Feedback promotion | disable review/promotion and similar recall | existing answers remain; replay never bypasses Guard/Oracle |
| Data Workspace | hide UI/route and retain read-only base query flow | history remains until an approved data migration |

## Database migration rollback

1. Confirm the exact current head and backup metadata PostgreSQL.
2. Stop Backend/RAG Runtime.
3. From `backend`, run Alembic downgrade only to the reviewed predecessor of `20260818_0010`, then start the prior compatible application image.
4. Verify authentication, workspace isolation, read-only query, and audit before reopening traffic.
5. If rolling forward again, apply `alembic upgrade head` and rerun migration, Backend, E2E and cold-start gates.

Do not drop or recreate the metadata database. Demonstration schemas may be recreated only through the explicit fixed-seed reset after confirming the target is `demo_business`, `chatbi_demo_business`, or `chatbi_benchmark_v21`; never target a workspace root or an unresolved path/database variable.

## Full candidate rollback

1. Stop Compose from the repository with `scripts/stop.ps1`.
2. Check out the previously recorded known-good commit using a non-destructive approved Git workflow; preserve all user changes first.
3. Restore the matching metadata backup if its schema is not backward compatible.
4. Rebuild/start twice from stopped state, verify three services healthy, login required, Golden smoke, guarded read-only query, RAG identity/ACL, and zero lifecycle counters.
5. Record the rollback SHA, database backup ID, commands, checks and any lost functionality in the incident evidence.

If V1.1.0 has not yet been pushed to `main` or tagged, simply keep the integration candidate unpublished; do not create/move a tag to represent a failed candidate.
