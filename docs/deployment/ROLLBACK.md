# Deployment Rollback

This guide translates the existing V1.3 rollback controls into an operator workflow. It does not require internal Phase Evidence.

## Recovery point

Use the exact last-known-good Git tag/SHA and the backup taken before upgrade. Do not move `chatbi-v2-v1.3.0` or modify the existing GitHub Release.

## Procedure

```powershell
.\scripts\stop.ps1
git switch --detach <last-known-good-sha>
.\scripts\restore.ps1 -Name <pre-upgrade-backup> -RestoreStorage -Force
.\scripts\start.ps1
.\scripts\doctor.ps1
```

If the failed candidate and recovery point use the same migration head and metadata is intact, the owner may omit Restore after validating that decision. When migration heads differ or data correctness is uncertain, restore the verified pre-upgrade dump.

## Validation

- exact source SHA and expected image IDs;
- Backend, Frontend, RAG, and Sandbox ready;
- authenticated login;
- metadata migration at the expected head;
- datasource connection and Schema Sync;
- representative SQL result value and signature;
- RAG citation, file upload, answers, and dashboards;
- no cross-project Compose resources stopped or deleted.

Never use `docker system prune`, `docker compose down -v`, broad database deletion, or a production datasource as a rollback test.
