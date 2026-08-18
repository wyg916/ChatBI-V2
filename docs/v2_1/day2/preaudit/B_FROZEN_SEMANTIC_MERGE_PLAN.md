# B frozen-file semantic merge plan

Prerequisite: `DAY1_STATUS=PASS`, a full `DAY1_FINAL_SHA`, successful preaudit refresh, and re-verification of B tip/tree. This document is a plan only.

## `backend/app/api/routes/evaluation.py`

**Phase 2 logic to preserve**

- Resolve a real `Principal` on every overview/run/case endpoint.
- Pass `principal.workspace_id` into all reads and `principal` into execution.
- Keep `evaluation.read` / `evaluation.run` / `answer.manage` permission boundaries and audited actor identity.

**B logic to add**

- Evaluation definitions, execution, comparisons, dashboard and release gate.
- Correct/incorrect feedback, recall, review and replay endpoints.
- `evaluation_run_view` response shaping and B schemas/services.

**Why incoming overwrite is invalid**

B was authored from a merge base before Phase 2 workspace scoping. Its original existing endpoints call unscoped service functions and would allow cross-workspace record selection.

**Manual merge steps**

1. Start from the refreshed Day 1/Phase 2 route.
2. Add B imports and additive endpoints.
3. Change every B service call to accept `principal.workspace_id` or `principal`; never use `_` when identity is needed for filtering/audit.
4. Ensure definition IDs, compare IDs, dashboards, gates, feedback answers and replay query runs are scoped before lookup.
5. Preserve audit commit ordering and error mapping.

**Targeted regression**

- B backend test plus anonymous 401, cross-workspace overview/run/case/feedback 403-or-404, evaluation.run/answer.manage role denial, audit actor/workspace assertions.
- Golden 50, feedback 3/3 and migration smoke.

**Rollback**

Revert the single B integration merge commit and verify Phase 2 evaluation routes still pass.

## `backend/app/services/evaluation.py`

**Phase 2 logic to preserve**

- Workspace filters for overview, runtime datasource/model lookup, security regression, run detail and case detail.
- `QueryPipeline.execute(..., principal=principal)` so authorization is not bypassed.
- EvaluationRun ownership set from authenticated Workspace.

**B logic to add**

- IBM-compatible multi-ground-truth result comparison and accuracy dimensions.
- Evaluation profiles/definitions, comparison, dashboard and numerical release gate.
- Rich result diff/error analysis and B run view.

**Why incoming overwrite is invalid**

B's original `_runtime`, `run_golden_evaluation`, details and dashboard helpers default to the default workspace. That silently undoes Phase 2 tenant isolation.

**Manual merge steps**

1. Define all public service signatures with an explicit `workspace_id` or `Principal`.
2. Thread Workspace filters through `_runtime`, evaluation selection, comparisons, dashboard, gate, definition execution and case navigation.
3. Keep B adapter computations pure; persist their output only on workspace-owned records.
4. Invoke the refreshed Day 1 QueryPipeline with the authenticated principal and updated semantic runtime.
5. Ensure feedback replay uses SQL Guard, QueryExecutor and ResultOracle; never trust stored SQL solely because it was previously verified.

**Targeted regression**

- 50/50 PostgreSQL, 10/10 MySQL, 38/38 dangerous SQL, B multi-ground-truth dimensions, cross-workspace direct-ID denial and replay guard/oracle tests.

**Rollback**

Revert the B merge as one unit; retain all pre-existing Phase 2 EvaluationRun data and do not alter migrations.

## `frontend/playwright.config.ts`

**Phase 2 logic to preserve**

- Import and apply `adminStorageState` so authenticated E2E does not rely on client headers or anonymous access.
- Preserve existing global setup and Phase 2 test discovery.

**B logic to add**

- `CHATBI_WEB_BASE` override and derived development port for isolated B runs.

**Why incoming overwrite is invalid**

Taking B wholesale drops authenticated storage state; taking Phase 2 wholesale prevents isolated dynamic-port B CI.

**Manual merge steps**

Import `adminStorageState`, calculate `webBase/webPort`, use dynamic base URL/port, and retain `storageState`, global setup, trace and existing testDir.

**Targeted regression**

- Run Phase 2 authenticated Playwright and B E2E with both default port and an overridden `CHATBI_WEB_BASE`; anonymous-auth tests must still create their own empty context.

**Rollback**

Revert the B merge and run the Phase 2 Playwright config smoke.

## `frontend/src/types/api.ts`

**Phase 2 logic to preserve**

- Nine-route `QuestionRoute`, Session/Auth, Conversation/Message, Attachment and chat input/response contracts.

**B logic to add**

- EvaluationProfile/Create, accuracy/release-gate fields, comparisons/dashboard, feedback candidates/workflows/replay.

**Why incoming overwrite is invalid**

B's file is based before the Chat/Auth/Attachment type additions. Incoming overwrite would break compile-time contracts for all five protected product capabilities.

**Manual merge steps**

Start from refreshed Day 1 types, append B types, de-duplicate shared names, keep optionality consistent with backend schemas, then typecheck all API consumers.

**Targeted regression**

- Frontend typecheck/build, all Vitest, Ask/Login/Attachment tests, B evaluation tests and route tests.

**Rollback**

Revert the B merge; no generated type file or lockfile should remain.

## Completion rule

All four files must be reviewed against base/ours/theirs and committed in one auditable B integration merge. A clean textual merge is not sufficient evidence. Any targeted or Phase 2 regression failure stops the wave at `PRE_B_SHA`.
