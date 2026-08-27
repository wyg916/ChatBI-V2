# Enterprise Datasource Onboarding

Datasource onboarding must use the product UI or public Backend API. Do not insert datasource rows directly into the metadata database.

## Required chain

```text
Add Datasource
→ Test Connection
→ Schema Sync
→ Catalog Sync
→ Semantic Binding
→ Publish Semantic Model
→ ChatBI
```

## Least-privilege PostgreSQL example

An enterprise database administrator should create a dedicated login and grant only:

```sql
GRANT CONNECT ON DATABASE business_db TO chatbi_reader;
GRANT USAGE ON SCHEMA reporting TO chatbi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO chatbi_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA reporting
  GRANT SELECT ON TABLES TO chatbi_reader;
```

Do not grant schema ownership, `CREATE`, DDL, DML, superuser, replication, file, or external-program permissions.

## UI/API flow

1. Sign in as an administrator.
2. Open Data Sources and add PostgreSQL or MySQL.
3. Supply host, port, database, read-only username/password, SSL policy, and optional schema.
4. Run Test Connection. The saved datasource status must become `CONNECTED`.
5. Run Schema Sync. Confirm non-zero schema, table, and column counts and status `SYNCED`.
6. Create a semantic model bound to that datasource.
7. Add entities, metrics, dimensions, relationships, terms, and synonyms.
8. Publish the semantic model, which creates a traceable semantic version.
9. Ask a representative question and confirm SQL Guard allowed it, execution succeeded, and Result Oracle passed.

`scripts/smoke.ps1` exercises the same formal API path against an explicitly configured read-only smoke datasource. Smoke-only variables never bypass product services.

## Network notes

- From Docker to PostgreSQL on Windows host: `host.docker.internal`.
- From Docker to a private database server: use its DNS name or private IP and allow the Backend host.
- Do not use `localhost` for a host-side database.
- Require TLS when traffic crosses an untrusted network.

## Demo versus enterprise data

Demo Seed is optional and is intended only for quick experience. Enterprise deployment defaults to no Demo Seed and connects a real datasource. Simulated data, when used, remains clearly reproducible and outside frontend source code.
