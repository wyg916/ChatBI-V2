# ChatBI V2 V1.2.0 Rollback Manifest

V1.2.0 Tag is immutable. Rollback must use a new reviewed commit/branch; never reset `main`, force push, move an existing Tag, delete local PostgreSQL/MySQL data, or prune Docker state as a shortcut.

## Known-good identities

- Current release: `chatbi-v2-v1.2.0^{}`.
- Previous stable release: `chatbi-v2-v1.1.0^{}` = `094c81aaaba44ced62fec7f0b97cc73f217d5975`.
- Integration input: `5303bdb687ffe4c3896292b333edb58ed4003d6c`.
- V1.2.0 introduces no Alembic migration and no dependency change.

## Capability-first rollback

1. Stop new traffic and wait for active SSE/Agent/file tasks to reach zero.
2. For a semantic runtime incident, set `CHATBI_SEMANTIC_RUNTIME_MODE=local` and restart Backend.
3. For governed RAG or bounded Agent incidents, use the existing `CHATBI_RAG_MODE` / `CHATBI_AGENT_MODE` incident controls; never fabricate fallback answers.
4. For a Chat UI-only incident, deploy the previous stable frontend image while keeping the compatible Backend and metadata database intact, then run login, query, RBAC and persistence smoke.

## Full release rollback

Create a dedicated rollback branch from the current `main`, preserve evidence and backups, then revert in this exact non-destructive order:

```powershell
git revert 2b75c7e90d01f27ed5d880b00fe68761f3715b17
git revert c0da6d758070b04303b263a7713998376e723201
git revert 6bd3a96ab8207c4fa13fe8afad1414e1e0cb0d0f
git revert 388666b6dc2e3d5bd9617c0dd0c195db2691900b
git revert 5303bdb687ffe4c3896292b333edb58ed4003d6c
git revert 758de13aa53ad69cf2231b39b81c6c13258b32de
git revert 15291e6e23464893fc88bd6b4b94f28f0be53d80
git revert -m 1 8676c07cc3144026fbbd282f54d318ae3cc2f546
```

The order is the exact reverse of `main`'s first-parent release sequence after V1.1.0. It first removes the final transactional cancellation acknowledgement, the scoped cancellation implementation and its release-gate hardening, then removes the V1.2.0 metadata/SBOM/freeze commit, final evidence/test hardening and the Chat UI merge while preserving the original `main` parent. Review each generated revert before publishing; do not execute these commands on a dirty worktree.

## Data and service recovery

1. Run `scripts/stop.ps1`.
2. Because V1.2.0 has no migration, do not downgrade or restore the metadata database merely to roll back UI/runtime code.
3. If independent operational writes require restoration, use the pre-release PostgreSQL backup and separately verified MySQL compatibility backup; never delete or recreate broad databases.
4. Build and start the rollback candidate twice from stopped state.
5. Verify Backend/Frontend/RAG health, login, read-only NL2SQL, Result Oracle, RAG ACL, Agent budgets, attachment isolation and browser error counters before reopening traffic.
6. Record the rollback commit, image IDs, backup IDs, test results and lost capabilities in incident evidence.
