# ChatBI V2 v1.3.1 Rollback

## Immutable published V1.3.1 contract

The published annotated tag `chatbi-v2-v1.3.1` peels to `dddca12d3f4a337c51a12ce5cd9a880239b8429d` and has migration head `20260828_0013`. Its immutable source rollback point is annotated tag `chatbi-v2-v1.3.0`, peeled to `52db955fd67ebe592c289399a135528c13cb3e3d`, with migration head `20260822_0012`. Never move, overwrite or recreate either tag or its GitHub Release.

Backups created by the published V1.3.1 source use the V2 manifest contract. Restore those backups only with the matching published source/tag; current successor source deliberately refuses V2 manifests. Do not relabel a backup manifest.

## Unreleased main successor

The current unreleased working-tree successor declares migration head `20260829_0014`, with direct downgrade target `20260828_0013`, and creates V3 backup manifests. These changes are not part of the immutable `chatbi-v2-v1.3.1` tag and are not certified by the tag's historical test totals.

Migration `0014` fails closed while managed Excel/CSV datasource rows, schemas or helper readers remain. Export and delete those datasources through the Backend API before an `0014 → 0013` downgrade. A rollback that changes metadata schema must use a verified pre-upgrade backup and the exact project-scoped deployment commands. Do not use `docker compose down -v`, delete local PostgreSQL/MySQL databases, or operate an unrelated Compose project/schema.

## Historical isolated `0013 → 0012` runner

Current source retains one narrowly scoped historical runner:

```powershell
.\scripts\test-v131-historical-rollback-dry-run.ps1 `
  -EvidencePath <external-evidence-root>\rollback\v1.3.1-historical-rollback.json
```

The runner is fixed to V1.3.1-line candidate `852d8aa35a6ec0a31bed34ba695ec6a17034b457` at `20260828_0013` and rollback SHA `89bdc12936be0555bdad8a85f06932fb7dc476ee` at `20260822_0012`. It refuses SHA/head overrides and must not be used for `0014`. It reads `.env` from this repository. Its automatic Python selection accepts only an interpreter that can import `psycopg`, `pydantic` and `pydantic_settings`; if none is available, pass the project Backend virtual-environment interpreter explicitly with `-Python <path-to-backend-venv-python>`.

This isolated historical evidence validates only the fixed `0013 → 0012 → 0013` path. It does not certify the unpublished `0014` successor.

## Controlled procedure

1. Stop the affected deployment with its exact `-EnvFile` and project scope.
2. Preserve logs, the matching backup manifest and the failed-release evidence.
3. Verify the pre-upgrade backup and its SHA-256 values using the same release source that created its manifest format.
4. For the unpublished successor, remove managed spreadsheet sources through the Backend API and validate `0014 → 0013` before any older rollback. For the published V1.3.1 contract, use the audited `0013 → 0012` path in the exact project-owned PostgreSQL schema.
5. Check out the intended annotated tag, rebuild the scoped images and restore only a backup compatible with that source/tag.
6. Run Doctor, migration status, health, login, anonymous 401, read-only datasource and one verified ChatBI query smoke.
7. Confirm that no temporary worker, container, network or schema remains.

A production rollback remains outside this source-release certification and requires environment-specific change control.
