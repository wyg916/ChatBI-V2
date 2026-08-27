# Troubleshooting

Run:

```powershell
.\scripts\doctor.ps1
```

Doctor prints `PASS`, `WARN`, or `FAIL` and an `ACTION` for every blocking issue.

## Docker is not running

Symptom:

```text
FAIL: Docker running - Docker Desktop is not running
ACTION: Start Docker Desktop and wait until it reports Ready.
```

Recovery: start Docker Desktop, wait for Engine readiness, rerun Doctor, then Bootstrap.

## Port conflict

Symptom: Backend, Frontend, or RAG port is listening but does not return the expected ChatBI health endpoint.

Recovery: stop the owning process or change the matching `CHATBI_*_PORT`. Keep all three ports distinct and update CORS/browser URLs.

## PostgreSQL configuration error

Symptoms: invalid URL, TCP unreachable, authentication failure, or migration failure.

Recovery:

1. use `postgresql+psycopg://`;
2. replace `localhost` with `host.docker.internal` for a Windows host database;
3. verify database, role, password, firewall, and `search_path`;
4. grant metadata privileges only inside the ChatBI-owned database/schema;
5. rerun `config.ps1`, `doctor.ps1`, then `bootstrap.ps1`.

No partial service stack is started when critical configuration or Bootstrap fails.

## Missing Provider key

This is not a startup failure. Doctor reports WARN for live AI and the base application remains usable. Configure one of MiMo, DeepSeek, or Kimi server-side when live Provider behavior is required. Never paste a key into the Browser.

## Migration is not at head

Run:

```powershell
.\scripts\bootstrap.ps1 -SkipBuild
```

If migration fails, stop. Preserve the error, database backup, source SHA, and migration head. Do not edit a historical migration.

## Services do not become healthy

```powershell
.\scripts\status.ps1
docker compose --env-file .env --project-name <project> logs --tail 200
```

Inspect the specific service without dumping `.env`. Fix the root cause and rerun Start. Stop only with `scripts/stop.ps1`.

## Backup/restore

Backup needs the pinned PostgreSQL maintenance image and write access to `CHATBI_BACKUP_ROOT`. Restore rejects a missing manifest, checksum mismatch, or schema mismatch before changing the database.
