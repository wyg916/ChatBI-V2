# ChatBI V2 v1.3.1 Rollback

The immutable source rollback point is annotated tag `chatbi-v2-v1.3.0`, peeled to `52db955fd67ebe592c289399a135528c13cb3e3d`. Never move, overwrite or recreate that tag or its GitHub Release.

V1.3.1 has unique migration head `20260828_0013`; the V1.3.0 migration head is `20260822_0012`. A rollback that changes metadata schema must use a verified pre-upgrade backup and the project-scoped deployment commands. Do not use `docker compose down -v`, delete local PostgreSQL/MySQL databases, or operate an unrelated Compose project/schema.

## Controlled procedure

1. Stop the V1.3.1 deployment with its exact `-EnvFile` and project scope.
2. Preserve logs, the V1.3.1 backup manifest and the failed-release evidence.
3. Verify a pre-upgrade V1.3.0-compatible metadata backup and its SHA-256 manifest.
4. If the metadata schema was upgraded, run the audited downgrade from `20260828_0013` to `20260822_0012` in the exact project-owned PostgreSQL schema.
5. Check out annotated tag `chatbi-v2-v1.3.0`, rebuild the scoped images and restore only the verified compatible backup.
6. Run Doctor, migration status, health, login, anonymous 401, read-only datasource and one verified ChatBI query smoke.
7. Confirm that no temporary worker, container, network or schema remains.

The V1.3.1 integration gate already exercised `0013 → 0012 → 0013` on an isolated local PostgreSQL schema. A production rollback remains outside this source-release certification and requires environment-specific change control.
