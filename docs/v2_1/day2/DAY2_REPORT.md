# ChatBI V2.1 Day 2 integration report

## Outcome

The pre-freeze Day 2 candidate is functionally PASS at Git `4d463e995855cd8ab5b34ece2ae2b3d7fed1ecf2`. Final PASS is issued only by the post-document, same-SHA gate and local/remote equality check; its raw manifest is stored under `artifacts/v2_1/day2-final/<DAY2_FINAL_SHA>/` without changing tracked files.

Day 2 lands the B Evaluation/Golden/Feedback workflow, C guarded Data Workspace, and D controlled RAG, fixed five-role/six-tool analysis, and non-executable structured-file analysis. It does not merge to `main`, create or move a tag, or execute the next day.

## Evidence and actual results

Executed 2026-08-19 Asia/Shanghai:

- Backend: `python -m pytest -q` — 185/185 PASS.
- Frontend: `npm test -- --run` — 12 files / 33 tests PASS; TypeScript PASS; Vite production build PASS with 738 modules.
- Browser: `npx playwright test --workers=1` — 63/63 PASS, including 15 live complex analyses and the file result/table/ECharts/Artifact flow; console, page and blocking request errors are 0.
- B: Golden 50/50, SQL execution 1.0, result-value accuracy 1.0, dangerous-SQL block 1.0, Multiple Ground Truth PASS, eight evaluation dimensions 1.0, Feedback replay 2/2 and rate 1.0.
- C: PostgreSQL and MySQL explorer/Explain/readonly execution/history/replay/Verified SQL PASS; 10M lazy sample PASS; sensitive masking PASS; business database writes 0.
- D: Knowledge 20/20 and citation accuracy 1.0; Agent 15/15 and trace complete 1.0; File 10/10 and result accuracy 1.0. Unauthorized recall, cross-scenario recall, prompt-injection evidence, direct DB access, guard/oracle bypass, unauthorized tool calls, sandbox escape, credential access and unrestricted network are all 0.
- Phase 2: 60/60 route coverage and Trace, follow-up 10/10, data/file/image/citation accuracy 1.0, unsupported-request hallucination 0.
- Day 1 semantic: 20/20; Wren/OpenChatBI/SuperSonic runtime call rates, Recall@5, MDL mapping and Golden consistency are all 1.0.
- SSE: 5 concurrent clients for 30 seconds, 68 requests, 0 errors, TTFE p95 824.427 ms, heartbeat max gap 2506.574 ms, cancellation cleanup 42.070 ms, 2/2 >10-second requests continuously streamed, connection/task leak 0/0.
- Startup: two consecutive full stopped-state runs reached 3/3 healthy in 27.840 and 28.362 seconds.
- Migration: one head `20260818_0010`; isolated PostgreSQL upgrade→base→upgrade PASS and temporary schema removed.

Evidence paths are this directory's B/C/D JSON and Markdown files, `MIGRATION_EVIDENCE.json`, `DAY2_PHASE2_REGRESSION.json`, `DAY2_TEST_SUMMARY.json`, and the post-freeze raw manifest directory described above.

## Boundaries, migration and rollback

- Frozen Zone intersection: 22 reviewed files. Each was merged per file; frozen blob wholesale overwrite count is 0. Phase 2 60/60 and full E2E 63/63 are the non-regression evidence.
- Migration impact: only C adds `20260818_0010` and `sql_workspace_run`; B and D add no migration. Roll back C with `alembic downgrade 20260818_0009` after disabling the additive Data Workspace route.
- License impact: IBM/SQLBot, Chat2DB, DB-GPT and PandasAI are pinned provenance or license boundaries. No upstream source, UI, prompt, logo, asset or restricted path is copied; PandasAI is not imported. No new direct dependency is added.
- Security: SQL remains behind authentication, Workspace/resource authorization, SQLGlot, readonly QueryExecutor and Result Oracle. The file interpreter executes no generated/user Python and sees only validated scoped previews. Agent tools do not hold database credentials.
- Rollback: revert the B/C/D merge chain in reverse order; keep DATA_QUERY on its existing deterministic pipeline; downgrade only the C migration as above.

Failures: none in the candidate product/test gates. Blockers: none in local engineering gates. Remote push/equality is intentionally evaluated only after the final tracked commit.
