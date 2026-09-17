# Upgrade

This is an executable upgrade workflow for a future owner-approved version. It does not authorize moving the existing V1.3.0 tag or Release.

## Before upgrade

1. Record the current source SHA and image IDs.
2. Run Doctor and ensure the existing deployment is healthy.
3. Create a named backup and copy its manifest/dump to protected storage.
4. Review Release Notes, migration notes, third-party notices, and rollback target.
5. Before the first managed Excel/CSV import on an existing local installation, install the scoped PostgreSQL helpers with `.\scripts\bootstrap-local-databases.ps1 -SpreadsheetHelpersOnly`. The administrator credential is prompt-only and is not persisted.

```powershell
git rev-parse HEAD
.\scripts\doctor.ps1
.\scripts\backup.ps1 -Name before-upgrade
```

## Update and migrate

Use the owner-approved branch/tag only:

```powershell
.\scripts\stop.ps1
git fetch origin --tags
git switch --detach <approved-tag-or-sha>
.\scripts\config.ps1
.\scripts\bootstrap.ps1
.\scripts\start.ps1 -SkipBuild
.\scripts\doctor.ps1
```

Bootstrap builds the updated Backend image, authenticates to PostgreSQL, and applies forward Alembic migrations before the full service start.

## Acceptance

Verify health, login, datasource connection, Schema Sync, representative deterministic ChatBI, RAG/file smoke, and browser console/network state. Do not treat HTTP 200 alone as correctness evidence.

## Rollback trigger

Rollback if migration fails, health never becomes ready, login fails, datasource/Schema Sync regresses, SQL Guard or Result Oracle behavior changes unexpectedly, or restored answers/dashboards are inconsistent.

Follow [ROLLBACK.md](ROLLBACK.md). Never rewrite a historical migration or move a published tag. Fix a migration defect with a new forward migration after recovery.
