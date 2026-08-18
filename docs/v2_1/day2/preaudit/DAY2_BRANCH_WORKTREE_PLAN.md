# Day 2 branch and worktree plan

This plan is inactive until `DAY1_STATUS=PASS`, `DAY1_FINAL_SHA=<full sha>` and `DAY2_PREAUDIT_REFRESH=PASS`.

## Current observations

- Final Integration is at old governance HEAD `cceeb1c...`; it is not the Day 2 base.
- Existing `codex/v2.1-data-workspace` at `9e2525c...` is a clean candidate based on Phase 2, but no canonical C intake is registered.
- Existing `codex/v2.1-rag-agent-file` is an empty Phase 2-based placeholder.
- Neither existing branch may be advanced or treated as based on future Day1 in this preaudit.

## Refresh gate

After Day 1 returns, run and record:

```text
git fetch --all --prune
git diff <AUDIT_BASE_SHA>..<DAY1_FINAL_SHA>
git diff --name-status <AUDIT_BASE_SHA>..<DAY1_FINAL_SHA>
Frozen Zone Intersection Refresh
Migration Refresh
API Contract Refresh
License Refresh
B Conflict Refresh
C Gap Refresh
D Gap Refresh
```

Also verify the Day1 commit/tree exists locally and remotely, its worktree is clean, all intended Day1 work is in that one tree, and Final Integration can fast-forward or integrate Day1 without rewriting Phase 2 history. Only then set `DAY2_PREAUDIT_REFRESH=PASS`.

## Formal branches

| Purpose | Branch | Worktree/base rule |
|---|---|---|
| Master integration | `codex/v2.1-final-integration` | Move forward to the accepted `DAY1_FINAL_SHA` only through the approved Day1 integration; record `DAY2_BASE_SHA` |
| B source | `origin/codex/v2.1-eval-golden-feedback` | Read-only canonical input; recheck tip `5690d9...` and tree `a805cc...`; merge full chain |
| C feature | `codex/v2.1-day2-data-workspace` | Create fresh from `DAY1_FINAL_SHA` in `E:\ChatBI-V2-wt-day2-data-workspace` |
| D feature | `codex/v2.1-day2-rag-agent-file` | Create fresh from `DAY1_FINAL_SHA` in `E:\ChatBI-V2-wt-day2-rag-agent-file` |

The observed C commit `9e2525c...` may be proposed as a candidate patch only after its SHA/tree, clean status, tests, license and 5 frozen intersections are formally registered. Apply/reconcile it on the fresh C branch; do not make its Phase 2 parent the Day 2 base. The empty old D branch has no reusable delta.

## Creation and safety procedure

1. Confirm recommended branch names and paths do not already exist; do not delete or repurpose unknown worktrees.
2. Resolve `DAY1_FINAL_SHA` to a full commit and tree; confirm remote ref.
3. Create C/D branches independently from that exact SHA; write `BASE_SHA` and `BASE_TREE_SHA` into each intake record.
4. Keep Final Integration as the only wave master. C/D never merge each other directly.
5. Each branch supplies status, canonical SHA/tree, clean status, changed files/stat, frozen intersections, tests, migrations, licenses and rollback contract.
6. Push only the intended task branch after clean/test evidence. Never push main or create/move a tag.

## Migration allocation

Determine `DAY1_MIGRATION_HEAD` during refresh. B currently adds no revision. C candidate's `20260818_0010` is provisional and must become the next unique revision after the refreshed head. D job/artifact metadata, if required, receives the next revision after the accepted C revision. Single head is mandatory after every wave.

## Stop conditions

Stop before branch creation if Day1 is not PASS, the final SHA is absent/unreachable/dirty, preaudit refresh is not PASS, B tip/tree changes, multiple migration heads exist, or unknown WIP overlaps a target path.

`NEXT_STEP=WAIT_FOR_DAY1_FINAL_SHA`
