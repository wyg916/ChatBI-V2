# Day 2 integration wave plan

Target sequence:

`DAY1_FINAL_SHA → B → targeted + Phase2 regression → C → targeted + Phase2 regression → D → full RAG/Agent/File + Phase2 regression → DAY2_FINAL_SHA`

No step in this document was executed by the preaudit.

## Wave 0 — establish Day 2 base

1. Complete refresh and record `DAY2_BASE_SHA=DAY1_FINAL_SHA`, tree, remote ref, clean status, migration head and Frozen manifest intersection delta.
2. Bring `codex/v2.1-final-integration` to that accepted Day1 tree without rebasing/squashing Phase 2 history.
3. Run Day1 final smoke and record `PRE_B_SHA=DAY2_BASE_SHA`.

## Wave B

1. Fetch exact remote B branch; verify tip `5690d9d0...`, tree `a805ccfa...`, merge base and all three commits.
2. Record `PRE_B_SHA` and perform one complete-chain merge.
3. Manually reconcile four frozen files per `B_FROZEN_SEMANTIC_MERGE_PLAN.md`; reconcile Day1 license/decision/Vite changes as medium/high semantic conflicts.
4. Migration: none; prove single head unchanged.
5. Targeted: B backend/frontend/E2E, Golden 50, multi-ground-truth, feedback 3/3, Workspace/RBAC/replay Guard+Oracle.
6. Run full Phase 2 no-regression minimum.
7. Commit one B integration commit, record SHA/tree and verify the remote integration ref after push.
8. Failure: stop and revert the B merge commit to `PRE_B_SHA`; no reset.

## Wave C

1. Record `PRE_C_SHA` as accepted B integration SHA.
2. Verify formal C intake. Reconcile the `9e2525c...` candidate only if registered; otherwise implement on fresh Day1-based C branch.
3. Manually merge five known frozen surfaces plus any refreshed Day1 intersections.
4. Migration: allocate one unique C revision after current head; upgrade-base-upgrade and downgrade proof.
5. Targeted: PG/MySQL explorer, 10M browse, search/pagination/lazy loading, format/explain/execute, history/replay, Verified SQL+B feedback, masking/RBAC/Workspace and dangerous SQL.
6. Run Phase 2 no-regression.
7. Commit one C integration commit, record SHA/tree/migration head and remote ref.
8. Failure: revert C integration commit; back up then downgrade C-only table if applied; return to `PRE_C_SHA`.

## Wave D

1. Record `PRE_D_SHA` as accepted C integration SHA.
2. Verify D intake and license/SBOM. Old-project code remains non-copyable; PandasAI `ee/**` is forbidden; DB-GPT/old designs are reference-only unless path-level review says otherwise.
3. Manually reconcile RAG/Agent/Attachment/Chat/SSE/Auth/Compose/requirements/UI frozen paths.
4. Migration: add file job/artifact tables only if the approved implementation needs persistence; use the next unique revision after C.
5. Targeted: RAG Golden 120 and ACL/injection; complex E2E 10 and budget/bypass counters; file Golden 10, 11 Phase2 formats, real no-network sandbox resource/escape/cleanup/artifact tests; citation UI.
6. Run Phase 2 no-regression, then Backend/Frontend/E2E full.
7. Commit one D integration commit and verify SHA/tree/migration head/remote ref.
8. Failure: stop new D traffic for containment, revert D integration commit, remove only D disposable runtime/jobs after backup, and return to `PRE_D_SHA`.

## Final Day 2 gate

On one clean tree only: Backend full; Frontend typecheck/test/build; serial E2E; migration single-head upgrade-base-upgrade; IBM/feedback/C/RAG/Agent/File gates; Golden 50; Phase 2 matrices; license/SBOM/secret scan; browser errors 0; two starts from stopped state. Record `DAY2_FINAL_SHA`, tree and remote branch verification.

No final tag and no `origin/main` push are part of this Day 2 preintegration plan. Any missing formal input or failed hard gate leaves status `PARTIAL` or `BLOCKED`.
