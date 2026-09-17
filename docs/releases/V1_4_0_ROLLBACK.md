# ChatBI V2 v1.4.0 Rollback Plan

> Status: **PENDING — RELEASE CANDIDATE ONLY**
>
> The final v1.4.0 release SHA, annotated tag object, GitHub Release and exact rollback evidence are `PENDING`. This document defines the required rollback controls; it does not claim that a release or rollback has already been executed.

## Immutable-history rules

- Never move, recreate, overwrite or delete the existing `chatbi-v2-v1.3.1` tag or GitHub Release.
- After publication, never move, recreate or overwrite the proposed `v1.4.0` annotated tag or its GitHub Release.
- Never use `git push --force`, `git push --force-with-lease`, destructive reset, or history rewriting to roll back a public release.
- Do not replace a published artifact in place. Correct source history through a reviewed PR and publish a new patch release when a forward fix is required.

## Source rollback paths

### Before the PR is merged

If the candidate fails review or validation, leave remote `main` unchanged. Correct or abandon `chore/open-source-release`; do not create `v1.4.0` and do not alter any existing release tag.

### After merge but before tag and GitHub Release

Create a short-lived rollback branch from the current remote `main`, revert the exact candidate merge or the identified commits, and open a new pull request. Run the same required GitHub Actions and merge only after review. Do not reset or force-push `main`.

### After `v1.4.0` is published

Keep the tag and Release immutable. Choose one controlled path:

1. **Forward fix:** correct the defect through a reviewed PR and publish a new patch version without altering `v1.4.0`.
2. **Deployment rollback:** restore a verified pre-upgrade backup and deploy an older immutable compatible tag. If source commits must also be removed from `main`, use a separate revert PR; do not rewrite history.

The final release merge SHA, revert range and PR URLs remain `PENDING` until publication.

## Database migration constraints

The candidate declares Alembic head `20260829_0015`:

- `20260829_0014` adds managed Excel/CSV datasource metadata and related managed-storage state.
- `20260829_0015` permits historical `SQLWorkspaceRun` records to retain evidence after datasource deletion by making the datasource reference nullable with `ON DELETE SET NULL` behavior.

Downgrade precautions:

1. **`0015 → 0014`:** migration `0014` cannot represent detached SQL-workspace history. If any run has a missing datasource link, restore the referenced datasource relationship or retain `0015`. Do not discard historical runs merely to force a downgrade.
2. **`0014 → 0013`:** export and remove managed Excel/CSV datasources through the Backend API, then verify that managed rows, schemas and helper-reader state are absent. The downgrade must fail closed while managed spreadsheet state remains.
3. **Code/schema compatibility:** do not start the v1.3.1 source against an unreviewed `0015` schema. Complete the controlled database downgrade or use a source version explicitly compatible with the current schema.
4. **Project scope:** operate only on the exact ChatBI project, environment file, PostgreSQL schema and Compose project being rolled back. Never use `docker compose down -v` or delete unrelated local PostgreSQL/MySQL databases.

## Backup requirements

Before merge deployment or any database migration:

1. Stop or quiesce writes using the project-scoped deployment procedure.
2. Create a complete pre-upgrade backup with the source version that owns its manifest format.
3. Record the source commit, migration head, database identity, manifest version, file list and SHA-256 checksums outside the database being changed.
4. Perform a restore verification in an isolated project-owned environment before relying on the backup.
5. Preserve both the pre-upgrade backup and the failed-release evidence until the rollback window closes.

Successor backups use the `chatbi-enterprise-backup-v3` contract. Restore them only with matching-source semantics. Never rename or relabel a V2/V3 manifest to bypass source-compatibility checks.

## Controlled rollback procedure

1. Record the deployed source SHA, image digests, migration head, active configuration and observed failure.
2. Stop the affected deployment with its exact environment file and project scope.
3. Preserve logs, audit records, the matching backup manifest and all checksums.
4. Resolve the `0015 → 0014` detached-history guard, then the `0014 → 0013` managed-spreadsheet guard when an older schema is required.
5. Check out the intended immutable source tag and rebuild the scoped images; do not reuse an image whose source revision cannot be proven.
6. Restore only a verified backup compatible with that source and migration head.
7. Run Doctor, migration status, health, login, anonymous-401, read-only datasource and one verified ChatBI query smoke test.
8. Confirm that no temporary worker, container, network, schema or plaintext credential remains.
9. Record the rollback commit/PR, deployed tag, database result and validation evidence. Until completed, each field remains `PENDING`.

## Release-specific rollback evidence

| Field | Value |
|---|---|
| v1.4.0 final commit SHA | `PENDING` |
| v1.4.0 annotated tag object | `PENDING` |
| Verified pre-upgrade backup | `PENDING` |
| Backup manifest/checksum report | `PENDING` |
| `0015 → 0014` validation | `PENDING` |
| `0014 → 0013` validation | `PENDING` |
| Revert PR or forward-fix PR | `PENDING` |
| Post-rollback smoke result | `PENDING` |

A production rollback remains outside this source-release certification and requires environment-specific change control.
