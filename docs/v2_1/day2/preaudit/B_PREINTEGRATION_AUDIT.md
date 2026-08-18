# B Eval / Golden / Feedback pre-integration audit

Classification: read-only canonical input verification. No merge was executed.

## Canonical verification

| Check | Result |
|---|---|
| Remote branch | `origin/codex/v2.1-eval-golden-feedback` exists |
| Remote tip | `5690d9d0ec04be0b21dfd642e0d8802ae1d5142a` — matches supplied canonical SHA |
| Tree SHA | `a805ccfa23db8231bca894bfee8a8856a14de347` — matches supplied canonical tree |
| Merge base | `23c6be78dd0c83dd81c5b4559ddab9dc77ff6fbd` |
| Canonical chain | 3 commits, complete |
| Changed files | 30 |
| Phase 2 frozen intersections | 4 (`HIGH_CONFLICT`) |
| Alembic changes | 0 |
| Dependency-manifest changes | 0 |
| Merge executed | NO |

Canonical commits, oldest first:

1. `89d0d251910d5dc872242bd30de27bdae08a9532` — `feat: close v2.1 evaluation and feedback loop`
2. `3a093dbfad874f8b13e0b244b6603cce8907a29c` — `fix: include workspace packages in eval CI`
3. `5690d9d0ec04be0b21dfd642e0d8802ae1d5142a` — `fix: keep Vite config independent of Node types`

Formal integration must fetch and merge the remote branch as a complete chain. Cherry-picking only the tip is prohibited.

## Changed-file inventory

```text
.github/workflows/v21-eval-golden-feedback.yml
THIRD_PARTY_NOTICES.md
backend/app/api/routes/evaluation.py
backend/app/evaluation/ibm_adapter.py
backend/app/schemas/evaluation.py
backend/app/services/evaluation.py
backend/app/services/feedback_loop.py
backend/scripts/prepare_eval_schema.py
backend/scripts/run_v21_release_gate.py
backend/tests/test_v21_eval_feedback.py
docs/DECISIONS.md
docs/STATUS.md
docs/evidence/v2.1/README.md
docs/evidence/v2.1/eval-feedback-release-gate.json
docs/evidence/v2.1/eval-golden-release-gate.json
docs/evidence/v2.1/golden-50-postgres-mysql.json
docs/evidence/v2.1/test-summary.json
docs/integration_requests/EVAL_FEEDBACK_INTEGRATION_REQUEST.md
docs/status/V2_1_EVAL_GOLDEN_FEEDBACK_STATUS.md
evaluation/golden/v2.1-multiple-ground-truth.json
frontend/e2e/v21-eval-feedback.spec.ts
frontend/playwright.config.ts
frontend/src/api/evaluation.ts
frontend/src/pages/EvaluationFeedbackPanel.tsx
frontend/src/pages/EvaluationOverviewPage.tsx
frontend/src/pages/evaluation-overview.css
frontend/src/test/evaluation-feedback-v21.test.tsx
frontend/src/types/api.ts
frontend/vite.config.ts
scripts/start-v21-eval-isolated.ps1
```

## Frozen-zone conflicts

The following paths require manual three-way semantic merge even if Git auto-merges:

- `backend/app/api/routes/evaluation.py`
- `backend/app/services/evaluation.py`
- `frontend/playwright.config.ts`
- `frontend/src/types/api.ts`

The central incompatibility is that Phase 2 added server-side `Principal`/Workspace scoping and authenticated Playwright storage state after B's merge base, while B independently expanded evaluation/feedback contracts. Incoming overwrite would reintroduce cross-workspace access and anonymous test assumptions.

## Migration plan

`MIGRATION_CHANGED=NO`. B reuses existing records and typed JSON metadata. `backend/scripts/prepare_eval_schema.py` is a preparation helper, not an Alembic revision and must not be treated as schema migration evidence.

The B integration wave must run the current migration single-head and upgrade-base-upgrade test without creating a B-only revision. Any future dedicated evaluation/feedback tables are a separate design change and must be sequenced after the refreshed Day 1 head; they cannot be smuggled into this merge.

## License matrix

| Component | Use | License path | Decision |
|---|---|---|---|
| IBM Text-to-SQL Evaluation Toolkit | Design reference / project-owned adapter | Apache-2.0; locked reference in repository manifest | Allowed with notice; no IBM source, bundle, logo or benchmark copied |
| SQLBot | Product-reference only for feedback/Verified SQL concepts | Modified GPLv3 with additional restrictions | No source/UI/prompt/logo/text copied; keep reference-only |
| Existing SQLGlot/React/Playwright dependencies | Existing published packages | Existing notices and lockfiles | No new package introduced by B |

`THIRD_PARTY_NOTICES.md` is changed by B and must be semantically reconciled with Day 1's expanded upstream notice, not overwritten in either direction.

## Existing evidence and limits

B's registered evidence locations are `docs/evidence/v2.1/*`, `backend/tests/test_v21_eval_feedback.py`, `frontend/src/test/evaluation-feedback-v21.test.tsx`, `frontend/e2e/v21-eval-feedback.spec.ts`, and CI run `32059294683`. The recorded isolated results are Backend 130/130, Frontend 29/29, build 732 modules, workflow E2E 2/2, PostgreSQL 50/50, MySQL 10/10, dangerous SQL 38/38, and feedback replay 3/3.

These are B-branch facts only. They are not post-Day1 integration evidence and must not be combined with Phase 2 or Day 1 results to claim a final PASS.

## Conflict forecast against future Day 1

- Day 1 semantic work changes `THIRD_PARTY_NOTICES.md`, `docs/DECISIONS.md`, `frontend/vite.config.ts`-adjacent runtime behavior and QueryPipeline semantics consumed by B evaluation.
- Day 1 SSE/data work changes authenticated streaming and benchmark data used by later evaluation gates.
- B must therefore be refreshed against `DAY1_FINAL_SHA`: compare API signatures, evaluation calls to `QueryPipeline.execute`, workspace scoping, frontend types, Vite/Playwright ports, Golden data signatures and license notices.

## Rollback

Record `PRE_B_SHA` immediately before the formal merge and the resulting B merge commit. If targeted or Phase 2 regression fails, stop integration and revert the B merge commit as one unit. Do not revert only the tip commit, move the Phase 2 protection ref, or reset the Final Integration branch.

`B_PREAUDIT=READY_FOR_REFRESH`

`B_MERGE_EXECUTED=NO`
