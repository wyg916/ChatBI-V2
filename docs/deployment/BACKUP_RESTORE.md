# Backup and Restore

ChatBI backup covers the metadata PostgreSQL schema and, when present, the project-owned attachment storage directory. The secret-bearing environment file is intentionally excluded.

## Backup

```powershell
.\scripts\backup.ps1
```

Or choose a stable name:

```powershell
.\scripts\backup.ps1 -Name before-upgrade-2026-08-27
```

The command runs the pinned PostgreSQL client image as a short-lived maintenance container, writes a custom-format `pg_dump`, calculates SHA-256, optionally archives storage, and creates a manifest with `secrets_included=false`.

If `CHATBI_DATABASE_SCHEMA` is set, only that schema is dumped. Without it, the database role's visible default schema is used; an isolated explicit schema is strongly recommended.

## Restore

Restore is destructive and requires confirmation or `-Force`:

```powershell
.\scripts\restore.ps1 -Name before-upgrade-2026-08-27 -Force
```

To restore the optional storage archive too:

```powershell
.\scripts\restore.ps1 -Name before-upgrade-2026-08-27 -RestoreStorage -Force
```

Restore:

1. validates the manifest format and dump SHA-256;
2. verifies the backup schema equals current `CHATBI_DATABASE_SCHEMA`;
3. stops only the configured Compose project;
4. runs `pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error`;
5. reapplies current migrations and the idempotent deployment bootstrap.

## What is not backed up

- `.env` and Provider keys;
- an external enterprise business datasource;
- Docker images and build cache;
- source code, which remains in Git.

Keep the environment file in a separate secret-management backup process. Test restore on an isolated schema before relying on a backup for recovery.
