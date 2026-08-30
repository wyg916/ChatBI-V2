# Backup and Restore

ChatBI backup covers the metadata PostgreSQL schema and, when present, the project-owned attachment storage directory. The secret-bearing environment file is intentionally excluded.

## Backup

```powershell
.\scripts\backup.ps1
```

For the canonical local one-click Showcase, target its actual Compose project explicitly so the command can close the correct write path:

```powershell
.\scripts\backup.ps1 -ProjectName chatbi-v2-showcase
```

Or choose a stable name:

```powershell
.\scripts\backup.ps1 -Name before-upgrade-2026-08-27
```

The command first rejects any running canonical ChatBI Compose project known to share the selected metadata target (`chatbi-v2-showcase`, `chatbi-v2`, or the project configured by the selected environment file); it never stops that competing project automatically. It then records whether the scoped stack is running and stops it to close the API write window before checking the served migration and managed-datasource counts and running the pinned PostgreSQL client image as a short-lived maintenance container. It writes the dump, optional storage archive, and V3 manifest to invocation-unique staging names, calculates independent SHA-256 values, and publishes the manifest last only after every artifact succeeds. Reusing any existing backup name is rejected so a failed retry cannot damage an earlier recovery point. The manifest has `secrets_included=false` and records migration head `20260829_0015`, candidate version/Git identity, non-secret metadata counts, and a sanitized fingerprint covering Workspace, Settings, Provider runtime state, Invitation, RBAC, Datasource, Conversation/Answer persistence, and Dashboard metadata. A previously running stack is resumed and health-verified even when backup fails.

Current restore accepts only `chatbi-enterprise-backup-v3`. A V2 manifest belongs to the release contract that created it and must be restored with that matching source/tag (for the published V1.3.1 artifact, `chatbi-v2-v1.3.1`). Do not relabel or hand-edit a V2 manifest to bypass this boundary; create a fresh V3 backup after upgrading with the current source.

Managed Excel/CSV data is intentionally fail-closed in this metadata backup version: its dedicated `excel_*` schemas and database login roles cannot be reconstructed by a metadata-only `pg_restore`. Export and delete those managed datasources through the Backend API before backup. Backup and restore both verify zero `datasource_import`/`excel_datasource` records before changing data; they never silently omit or orphan an import.

If `CHATBI_DATABASE_SCHEMA` is set, only that schema is dumped. Without it, backup explicitly dumps only the default `public` metadata schema. It never dumps the administrator-owned `chatbi_admin`, `demo_business`, or any `excel_*` schema as an accidental side effect of a whole-database dump; an isolated explicit metadata schema remains recommended for enterprise use.

## Restore

Restore is destructive and requires confirmation or `-Force`:

```powershell
.\scripts\restore.ps1 -Name before-upgrade-2026-08-27 -Force
```

Add `-ProjectName chatbi-v2-showcase` when restoring the canonical local Showcase. Backup/restore apply the same fail-closed check in both directions: Showcase is rejected while the default/configured project is running, and the default/configured project is rejected while Showcase is running. Competing projects are reported and must be stopped explicitly, preventing two stacks that share `chatbi_v2` from racing the operation.

To restore the optional storage archive too:

```powershell
.\scripts\restore.ps1 -Name before-upgrade-2026-08-27 -RestoreStorage -Force
```

Restore:

1. validates the manifest format and dump SHA-256;
2. verifies the backup schema equals current `CHATBI_DATABASE_SCHEMA`;
3. checks managed spreadsheet counts and, when requested, validates and fully extracts the storage archive to a safe staging directory before stopping any service;
4. stops only the configured Compose project, repeats the spreadsheet preflight, atomically swaps staged storage, then runs `pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error --single-transaction`;
5. runs the read-only `alembic current` check and takes a sanitized snapshot without executing migrations, seeds, or deployment bootstrap mutations;
6. requires head `20260829_0015` and verifies the restored sanitized metadata fingerprint against the manifest before any later startup/bootstrap action is allowed.

If the transactional database restore fails, the previous storage directory is restored. Once PostgreSQL commits, later verification failures keep the matching restored storage in place and retain the prior directory under a unique `restore-previous` path for explicit operator recovery; the script does not silently create a new-database/old-storage pairing.

## What is not backed up

- `.env` and Provider keys;
- an external enterprise business datasource;
- managed Excel/CSV datasource rows (export and delete these before backup);
- Docker images and build cache;
- source code, which remains in Git.

Keep the environment file in a separate secret-management backup process. Test restore on an isolated schema before relying on a backup for recovery.
