# Deployment Security

## Trust boundaries

- Browser → Backend `/api/v1` only.
- Backend → metadata PostgreSQL with a project application role.
- Backend → enterprise datasource with a read-only role.
- Backend → governed RAG Runtime with HMAC and Workspace/user/role binding.
- Fixed Agent tools → Query Pipeline/RAG/verification adapters only.

The Browser never connects to a database and never stores database or Provider credentials.

## Database

- Do not use a PostgreSQL/MySQL administrator or schema owner as a business datasource.
- Generated SQL is one `SELECT` or `WITH ... SELECT`.
- SQLGlot AST allowlists, timeout, row limit, concurrency limit, read-only transaction, masking, audit, and Result Oracle remain mandatory.
- Metadata reset is denied outside local mode and an explicit project-owned `chatbi_*` schema.
- Reset and Restore require confirmation or `-Force`.

## Secrets

- `.env` is Git-ignored and excluded from Backup.
- Bootstrap generates application secrets locally and does not print them.
- Provider keys remain server-side and are not exposed by capability APIs, logs, Trace, evidence, or Markdown.
- Use secret-manager injection and restrictive filesystem permissions for private servers.
- Rotate generated credentials before external exposure and after suspected compromise.

## Network

- Expose only the Frontend or an approved reverse proxy.
- Use TLS at the ingress and TLS to databases across untrusted networks.
- Restrict Backend, RAG, database, and Docker socket access.
- The Sandbox Controller and Docker proxy use internal Compose networks, read-only filesystems, dropped capabilities, and no-new-privileges.

## RAG and Agent

RAG enforces Workspace ownership, RBAC/ACL, signed identity mapping, injection checks, citation verification, and Answer Guard. Complex analysis is limited to five roles and six tools with step, tool, replan, depth, timeout, and token budgets. Agent direct database, arbitrary URL, filesystem, shell, and dynamic-tool access remain prohibited.

## Production gap

This candidate is not production certified. Enterprise SSO, formal production key rotation, immutable OCI signing, HA, disaster recovery, production monitoring, and an SLA require separate design, implementation, and evidence.
