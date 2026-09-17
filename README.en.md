# ChatBI Studio

[简体中文](README.md) · [Installation](INSTALL.md) · [License](LICENSE)

An open-source ChatBI application for governed natural-language analytics. Connect PostgreSQL or MySQL, define business semantics, ask questions, verify results, and save answers and dashboard cards.

Core features include read-only SQL execution, AST validation, Result Oracle, ECharts, spreadsheet imports, governed retrieval, citation checks, bounded orchestration, workspace permissions, and audit records.

The frontend uses React and TypeScript. FastAPI owns database access and model credentials. PostgreSQL stores application metadata. Replaceable adapters isolate model, semantic, retrieval, and chart engines.

## Start

Install Docker Compose and PowerShell, provision PostgreSQL with a dedicated application role, copy `.env.example` to `.env`, and configure `CHATBI_DATABASE_URL`. Run `scripts/start.ps1`, then open `http://localhost:5173`.

Initialization creates the workspace, login identities, tool bindings, and system prompts. Configure your own read-only datasource and semantic model after login. See [installation](INSTALL.md) for credentials and deployment requirements.

## Source layout

- `backend/`: APIs, query engine, connectors, migrations.
- `frontend/`: product interface and chart rendering.
- `packages/`: bounded adapters and shared contracts.
- `sandbox_runtime/`: isolated computation.
- `scripts/`: deployment and maintenance.
- `docs/`: architecture, operations, configuration, and license records.

See [CONTRIBUTING](CONTRIBUTING.md), [SECURITY](SECURITY.md), and [third-party notices](THIRD_PARTY_NOTICES.md). Licensed under Apache-2.0.
