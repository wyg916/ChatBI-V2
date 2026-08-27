# ChatBI V2

Enterprise-oriented open-source ChatBI / NL2SQL platform for local deployment, private deployment, enterprise PoC, and secondary development.

ChatBI V2 turns a governed natural-language question into a read-only SQL query, validates the business result, and returns a chart, evidence, and an auditable answer. It is ChatBI-first: data sources, semantic models, verified answers, dashboards, and evaluation stay on one product path.

![ChatBI V2 ask-data interface](artifacts/chat-ui-optimization-20260819/final-integration/chat-ui-result-1440x900.png)

## Why ChatBI V2

- Verifiable by design: SQL AST guard, read-only execution, Result Oracle, result signatures, and audit records.
- A lightweight semantic layer: Metric, Dimension, Entity, Relationship, Business Term, and Synonym.
- Governed enterprise knowledge: Workspace/RBAC/ACL-bound RAG with citation and answer guards.
- Bounded complex analysis: five fixed roles, six allowlisted tools, hard budgets, complete Trace, and no direct Agent database access.
- Replaceable adapters: Semantic Engine, NL2SQL Engine, Model Provider, Chart Engine, RAG, and evaluation boundaries remain explicit.
- Deployment without mandatory Provider keys: the base product and deterministic NL2SQL path start locally; live AI clearly reports that Provider configuration is required.

## Core product path

```text
Connect datasource
→ Sync Schema and catalog
→ Bind and publish semantic model
→ Ask in natural language
→ Generate and guard read-only SQL
→ Execute and verify result values
→ Build chart and business conclusion
→ Save answer or dashboard
→ Regress through the evaluation center
```

The browser only calls Backend `/api/v1`. Database credentials, SQL execution, Provider keys, guards, and result verification stay server-side.

## Windows quick start

Prerequisites:

- Windows 10/11 with PowerShell 7 recommended
- Docker Desktop with Docker Compose
- Git
- PostgreSQL 15+ reachable from Docker
- At least 2 logical CPUs, 4 GB RAM, and 5 GB free disk; 8 GB RAM and 10 GB disk are recommended for first build

```powershell
git clone https://github.com/wyg916/ChatBI-V2.git
cd ChatBI-V2
Copy-Item .env.example .env
```

Edit `.env` and set `CHATBI_DATABASE_URL` to a project application role. PostgreSQL on the Windows host must use `host.docker.internal`, not `localhost`. Then run:

```powershell
.\scripts\doctor.ps1
.\scripts\bootstrap.ps1
.\scripts\bootstrap.ps1 -SkipBuild
.\scripts\start.ps1 -SkipBuild
```

Bootstrap generates the four local application secrets still marked as placeholders, applies Alembic migrations, and creates the Workspace and login identities. It is idempotent. Start calls Bootstrap automatically unless `-SkipBootstrap` is explicitly supplied.

When ready:

- Frontend: <http://127.0.0.1:5173/>
- Backend health: <http://127.0.0.1:8000/health>
- API docs: <http://127.0.0.1:8000/docs>
- RAG health: <http://127.0.0.1:8001/health>

Ports are configurable. The initial administrator is `admin@chatbi.local`; its generated password remains only in the Git-ignored `.env`.

```powershell
.\scripts\status.ps1
.\scripts\verify.ps1
.\scripts\stop.ps1
```

See the [complete Quick Start](docs/deployment/QUICK_START.md) and [configuration reference](docs/deployment/CONFIGURATION.md).

## Deployment operations

```powershell
.\scripts\doctor.ps1
.\scripts\backup.ps1
.\scripts\restore.ps1 -Name <backup-name> -Force
.\scripts\reset.ps1 -Force
```

Reset is a destructive local operation. Metadata reset is additionally guarded by local mode, `CHATBI_ALLOW_METADATA_RESET=YES`, an explicit `chatbi_*` schema, `-Metadata`, and confirmation or `-Force`. It never runs `docker system prune` or deletes an enterprise datasource.

Deployment guides:

- [Quick Start](docs/deployment/QUICK_START.md)
- [Configuration](docs/deployment/CONFIGURATION.md)
- [Private deployment](docs/deployment/PRIVATE_DEPLOYMENT.md)
- [Datasource onboarding](docs/deployment/DATASOURCE.md)
- [Backup and restore](docs/deployment/BACKUP_RESTORE.md)
- [Upgrade](docs/deployment/UPGRADE.md)
- [Rollback](docs/deployment/ROLLBACK.md)
- [Troubleshooting](docs/deployment/TROUBLESHOOTING.md)
- [Security](docs/deployment/SECURITY.md)

## Provider configuration

MiMo, DeepSeek, and Kimi use OpenAI-compatible server-side adapters. No key is required for base startup. For live Provider features, set only the relevant server-side key in `.env`:

```text
CHATBI_MIMO_API_KEY=
CHATBI_DEEPSEEK_API_KEY=
CHATBI_KIMI_API_KEY=
```

Keys are never returned to the browser or written to Trace and evidence. `CHATBI_MODEL_PROVIDER=auto` uses configured Providers and otherwise retains the deterministic local path. Details are in [Model Control Plane](docs/runtime/MODEL_CONTROL_PLANE.md).

## Datasources and demo data

An enterprise deployment does not depend on Demo Seed. Add a read-only PostgreSQL or MySQL account through the product:

```text
Add Datasource → Test Connection → Schema Sync → Catalog Sync
→ Semantic Binding → Publish → ChatBI
```

For a quick local experience, the existing `scripts/bootstrap-local-databases.ps1` can provision reproducible simulated business data in locally installed PostgreSQL/MySQL. Compose itself contains no database service or database volume. See [Datasource onboarding](docs/deployment/DATASOURCE.md).

## Architecture

```text
React + ECharts
       │ /api/v1
       ▼
FastAPI ── Auth / Workspace / RBAC / Audit
  ├── Semantic Context → NL2SQL → SQL Guard → Read-only Executor → Result Oracle
  ├── Governed RAG Runtime → ACL → Citation Guard → Answer Guard
  ├── Fixed five-role orchestration → six allowlisted tools
  └── PostgreSQL metadata + external read-only business datasources
```

Frontend: React, TypeScript, Vite, ECharts. Backend: Python, FastAPI, SQLAlchemy, Alembic, SQLGlot. Runtime architecture is documented in [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Security and evaluation

- Generated SQL is limited to one `SELECT` or `WITH ... SELECT`.
- DDL, DML, multiple statements, file access, external programs, and unsafe functions are rejected.
- Datasource credentials are encrypted server-side; users supply least-privilege read-only accounts.
- Query timeout, row limit, concurrency controls, masking, audit, Workspace isolation, ACL, and result signatures are enforced.
- Frozen Golden Sets, Backend tests, Frontend tests/build, E2E, migration checks, and release gates provide reproducible evidence.

Review [Security](docs/deployment/SECURITY.md), [Acceptance](docs/ACCEPTANCE.md), and the [Golden 50 set](evaluation/golden/day4-golden-50.json).

## Release positioning

The immutable `chatbi-v2-v1.3.0` tag remains the current formal release baseline. Enterprise quick-deploy work on a successor branch is a candidate for owner review; it does not move the existing tag or GitHub Release.

ChatBI V2 supports local deployment, documented private deployment, enterprise PoC, and secondary development. It is not advertised as production certified. Kubernetes, Helm, HA PostgreSQL, multi-node disaster recovery, production key rotation, immutable production OCI signing, production monitoring, and a formal SLA remain future work.

## Repository

```text
frontend/       React + TypeScript product UI
backend/        FastAPI, metadata, semantic, query, RAG, and orchestration
packages/       replaceable contracts and adapters
database/       reproducible optional local demo data
evaluation/     Golden Sets and evaluation assets
scripts/        deployment and verification commands
docs/           product, architecture, deployment, release, and evidence
```

Contributions are welcome under [CONTRIBUTING.md](CONTRIBUTING.md). Review [LICENSE](LICENSE), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), and the [open-source license audit](docs/OPEN_SOURCE_LICENSE_AUDIT.md) before redistribution.
