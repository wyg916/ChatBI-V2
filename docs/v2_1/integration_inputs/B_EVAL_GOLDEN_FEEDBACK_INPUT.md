# B Eval / Golden / Feedback Integration Input

## Canonical contract

```text
WORKFLOW=B
STATUS=READY
CAPABILITY_SCOPE=IBM Eval + Golden / Result Oracle + SQLBot Feedback / Verified SQL
SOURCE_BRANCH=origin/codex/v2.1-eval-golden-feedback
CANONICAL_SOURCE=REMOTE
CANONICAL_SHA=5690d9d0ec04be0b21dfd642e0d8802ae1d5142a
TREE_SHA=a805ccfa23db8231bca894bfee8a8856a14de347
BASE_MERGE_BASE=23c6be78dd0c83dd81c5b4559ddab9dc77ff6fbd
PHASE2_SHA=6cdbf12f6c2e8494afe21262fd092795c4f784c3
FETCH_STATUS=PASS
TREE_VERIFICATION=PASS
TREE_IDENTICAL=YES
CONTENT_DIFF_COUNT=0
CI_RUN=32059294683
CI_STATUS=PASS
CI_URL=https://github.com/wyg916/ChatBI-V2/actions/runs/32059294683
INTEGRATION_METHOD=MERGE_CANONICAL_REMOTE_BRANCH
ROLLBACK_INPUT=REVERT_FUTURE_B_MERGE_COMMIT_AS_ONE_UNIT
BLOCKERS=NONE
```

## Remote verification

- `git fetch --no-tags origin refs/heads/codex/v2.1-eval-golden-feedback:refs/remotes/origin/codex/v2.1-eval-golden-feedback` completed successfully.
- The fetched remote ref resolves directly to `5690d9d0ec04be0b21dfd642e0d8802ae1d5142a`.
- `git rev-parse origin/codex/v2.1-eval-golden-feedback^{tree}` resolves to `a805ccfa23db8231bca894bfee8a8856a14de347`.
- GitHub Actions Run `32059294683` is `completed/success`, with `headSha=5690d9d0ec04be0b21dfd642e0d8802ae1d5142a` and `headBranch=codex/v2.1-eval-golden-feedback`.
- The local reconciliation commit `39b689c9f2cb404ee05251c36db6a1a667086fad` has the same Tree SHA and a content diff count of 0, but it is not the canonical integration input and must not replace the remote SHA in governance records.

## Complete canonical chain

The canonical remote input is a three-commit chain rooted at the actual merge-base `23c6be78dd0c83dd81c5b4559ddab9dc77ff6fbd`:

1. `89d0d251910d5dc872242bd30de27bdae08a9532` — `feat: close v2.1 evaluation and feedback loop`
2. `3a093dbfad874f8b13e0b244b6603cce8907a29c` — `fix: include workspace packages in eval CI`
3. `5690d9d0ec04be0b21dfd642e0d8802ae1d5142a` — `fix: keep Vite config independent of Node types`

Do not cherry-pick only `5690d9d0ec04be0b21dfd642e0d8802ae1d5142a`. It is only the final commit in the canonical chain. Formal integration should fetch the remote branch, revalidate its tip and Tree SHA, then merge the canonical remote branch. If final conflict audit requires another method, all three commits' effective content must enter the integration branch and the final tree must be reconciled against the canonical Tree SHA.

## Capabilities

```text
IBM_EVAL_STATUS=PASS
MULTI_GROUND_TRUTH=PASS
RESULT_COMPARE=PASS
ERROR_ANALYSIS=PASS
EVAL_DASHBOARD=PASS
CI_GATE=PASS
GOLDEN_COUNT=50
SQL_EXECUTION_RATE=1.0
RESULT_VALUE_ACCURACY=1.0
DANGEROUS_SQL_BLOCK_RATE=1.0
SQLBOT_FEEDBACK_STATUS=PASS
VERIFIED_SQL_STATUS=PASS
FEEDBACK_REPLAY_RATE=1.0
```

The remote evidence records PostgreSQL execution/result/semantic `50/50`, MySQL compatibility execution/result `10/10`, dangerous SQL blocking `38/38`, and feedback replay `3/3`.

## Tests

```text
REMOTE_CI=PASS
BACKEND_TEST=PASS (130/130)
FRONTEND_TEST=PASS (29/29)
FRONTEND_BUILD=PASS (732 modules)
E2E_TEST=PASS (2/2 workflow-specific)
GOLDEN_RELEASE_GATE=PASS
FEEDBACK_RELEASE_GATE=PASS
```

These are B-branch isolated results and do not represent v2.1 Final Gate or a post-integration regression.

## Conflict audit

The canonical B range changes 30 files relative to its actual merge-base. Four paths intersect `CORE_FROZEN_ZONE` and are therefore `HIGH_CONFLICT` even if Git later reports no textual conflict:

```text
backend/app/api/routes/evaluation.py
backend/app/services/evaluation.py
frontend/playwright.config.ts
frontend/src/types/api.ts
```

`KNOWN_CONFLICTS=4_HIGH_CONFLICT_FROZEN_PATHS; TEXTUAL_MERGE_NOT_EXECUTED`

During formal integration, these files require manual three-way review against the Phase 2 blob anchors. Preserve server-side Auth/Workspace permissions, Phase 2 test discovery, and existing chat/auth API types. Run the per-workflow regression set immediately after B integration.

## Migration impact

`MIGRATION_IMPACT=NO_ALEMBIC_CHANGE`

B does not add or modify an Alembic migration. Evaluation profiles and feedback evidence currently reuse typed metadata in existing records. The branch's `IR-EVAL-002` requests future dedicated evaluation/feedback tables and a compatible backfill; that request must be handled by the later unified migration plan, not silently introduced while registering B.

## License impact

`LICENSE_IMPACT=THIRD_PARTY_NOTICES_UPDATED; NO_DEPENDENCY_MANIFEST_CHANGE`

- IBM Text-to-SQL Evaluation Toolkit is documented as an Apache-2.0 design reference; no IBM source, package, logo, or benchmark bundle is copied.
- SQLBot is documented as reference-only because of its modified GPLv3 and additional conditions; no SQLBot source, UI, logo, prompt, text, or asset is copied.
- `THIRD_PARTY_NOTICES.md` is changed by B and must be preserved during integration review.

## Rollback contract

No B merge commit exists yet. After formal integration, record the resulting merge commit as the rollback anchor and revert that merge as one unit if B must be removed. Do not roll back only the final canonical commit, and do not move the Phase 2 protection ref.
