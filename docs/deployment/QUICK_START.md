# Windows Docker Quick Start

This is the verified priority deployment path for ChatBI V2. Linux/private-server steps are documented separately and are not claimed as production certified.

## 1. Prerequisites

- Windows 10/11
- PowerShell 7 recommended
- Docker Desktop and Docker Compose
- Git
- PostgreSQL 15+ reachable from Docker
- 2+ logical CPUs, 4+ GB RAM, and 5+ GB disk; 8 GB RAM and 10 GB disk are recommended

ChatBI does not start a PostgreSQL container. Metadata and optional simulated business data remain in the user's locally installed or enterprise-managed database.

## 2. Clone and configure

```powershell
git clone https://github.com/wyg916/ChatBI-V2.git
cd ChatBI-V2
Copy-Item .env.example .env
```

Edit `.env`:

1. Set `CHATBI_DATABASE_URL` to a PostgreSQL application role.
2. For PostgreSQL on the same Windows machine, use `host.docker.internal`.
3. Keep `CHATBI_SEED_DEMO_SEMANTIC_MODEL=false` for an enterprise deployment.
4. If ports change, update `CHATBI_CORS_ALLOW_ORIGINS`.

Do not set Provider keys merely to start the base product.

## 3. Bootstrap, diagnose, and start

```powershell
.\scripts\bootstrap.ps1
.\scripts\doctor.ps1
.\scripts\start.ps1 -SkipBuild -SkipBootstrap
```

Bootstrap builds the Backend image, authenticates to PostgreSQL, applies Alembic migrations, creates the default Workspace, creates or rotates the two local login identities, and seeds governed RAG/Agent control records. It is idempotent and can be run again safely.

Start checks configuration and port conflicts before Compose starts. Success prints Frontend, Backend, RAG, and deployment mode.

## 4. Login and onboard data

Open the printed Frontend URL. Sign in as `admin@chatbi.local` with `CHATBI_BOOTSTRAP_ADMIN_PASSWORD` from the local `.env`.

Continue with:

```text
Add Datasource → Test Connection → Schema Sync → Catalog Sync
→ Semantic Binding → Publish → Ask Data
```

Always use a read-only datasource account.

## 5. Operate

```powershell
.\scripts\status.ps1
.\scripts\verify.ps1
.\scripts\doctor.ps1
.\scripts\stop.ps1
```

Stop uses the configured Compose project name and does not prune Docker or affect another project.

## 6. Optional Demo Seed

Quick experience:

```powershell
.\scripts\bootstrap-local-databases.ps1
.\scripts\bootstrap.ps1 -DemoSeed
```

This legacy convenience path uses locally installed PostgreSQL/MySQL and writes reproducible simulated data. A real enterprise deployment connects its own read-only datasource and does not depend on Demo Seed.

## 7. Custom environment file

Every deployment script accepts `-EnvFile`:

```powershell
.\scripts\bootstrap.ps1 -EnvFile D:\secure\chatbi.env
.\scripts\doctor.ps1 -EnvFile D:\secure\chatbi.env
.\scripts\start.ps1 -EnvFile D:\secure\chatbi.env -SkipBuild -SkipBootstrap
.\scripts\stop.ps1 -EnvFile D:\secure\chatbi.env
```

Keep the same file and Compose project name for all lifecycle commands.

Process/CLI values take precedence over the selected EnvFile, the selected EnvFile takes precedence over the default repository `.env`, and hard-coded values are safe fallbacks only. This makes a dedicated Enterprise PoC EnvFile and the isolated Local Showcase mode coexist without overwriting one another.
