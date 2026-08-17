# ChatBI V1.0.0 Rollback

## Baselines

- Final Tag: `chatbi-v2-v1.0.0`
- Day 4 safe SHA: `d70125f6172dd170c419110fd75d47e87a7f121a`
- Day 4 migration: `20260817_0006`
- V1 final migration: `20260817_0008`

## Back up first

Stop metadata administration writes and use the deployment environment's secret manager to back up PostgreSQL. Never put passwords in command history, documents, or the repository. Business data stays in the local PostgreSQL/MySQL servers and is not a Docker volume; do not use `docker compose down -v` as a database rollback mechanism.

## Emergency application rollback

1. Stop the application with `.\scripts\stop.ps1`.
2. Deploy the retained Day 4 image or SHA `d70125f6172dd170c419110fd75d47e87a7f121a`.
3. Using the backed-up metadata database, downgrade only when schema compatibility requires it: `.\.venv\Scripts\python.exe -m alembic downgrade 20260817_0006` from `backend`.
4. Start Day 4 and verify health, data-source connections, Ask, Result Oracle, Golden 50 and zero writes.

`CHATBI_RAG_MODE=off` and `CHATBI_AGENT_MODE=off` are emergency diagnostics for the final image, not a release-compliant V1 configuration. The safer rollback is to deploy the fully tested Day 4 artifact together with its compatible schema.

## Restore V1 final

```powershell
cd backend
.\.venv\Scripts\python.exe -m alembic upgrade 20260817_0008
cd ..
.\scripts\start.ps1
.\scripts\verify.ps1
```

Then verify PostgreSQL/MySQL READY, signed live RAG READY, five-role Agent READY, Ask `SUCCEEDED`, Oracle `PASSED`, Golden 50 PASS, RAG Golden 120 PASS, provider secrets hidden, and Git/tag identity.

## Executed simulation

The isolated rollback exercise ran final migration `0008` → Day 4 migration `0006` and validated Day 4 start/Ask/Golden50, then restored `0008` and validated final start/Ask/Golden50. Temporary schema and source were removed; real project data was preserved. Evidence: `docs/evidence/day5/rollback-rag-agent-simulation.json`.
