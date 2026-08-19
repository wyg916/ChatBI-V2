# ChatBI V2 V1.1.0 release notes

V1.1.0 turns the V2.1 three-day optimization work into a single release candidate centered on trustworthy enterprise question answering—not a generic AI platform.

## Highlights

- The default data path now links schema and semantics through independent OpenChatBI-, SuperSonic-, and Wren-compatible adapters before SQLGlot Guard, read-only execution, Result Oracle, and IBM-compatible evidence.
- Open-ended Chat handles 12 product routes through one persistent Conversation/Message runtime, with clarification and explicit unsupported/no-evidence behavior instead of forcing unknown prompts into a revenue query.
- Short-term memory preserves governed metric/dimension/time/region/customer/product/source/model/filter and prior evidence context, scoped to one workspace, user, and conversation.
- Full-chain SSE authenticates token/user/conversation ownership with one joined metadata read and no authentication cache, flushes acceptance early, emits bounded heartbeats/stages, propagates disconnect cancellation to PostgreSQL, and exposes leak counters.
- Data Workspace provides PostgreSQL/MySQL catalog search, relationships, masked samples, format/explain/read-only execute, history/replay and Verified SQL, including 10M lazy exploration.
- Governed Live RAG enforces signed identity, ACL/scenario filtering, hybrid retrieval/rerank and versioned citations; complex analysis remains a bounded five-role/six-tool workflow with no direct database connector.
- Structured file analysis covers CSV/XLS/XLSX/Parquet and fixed DataFrame operations without executing generated code; document/image/multimodal routes remain authenticated and evidence-bound.
- Final security scope expands dangerous SQL to 56 forms and actively attacks authentication, attachments, RAG, Agent boundaries, sandbox policy, secrets and supply chain.
- Python release pins were refreshed after the initial dependency audit blocked 86 advisories; the final lock is accepted only with zero `pip-audit` findings and complete product regression.
- Reproducible CycloneDX 1.6 and SPDX 2.3 SBOMs cover the installed backend container and complete frontend lockfile with unknown licenses blocked.

## Compatibility and operations

- PostgreSQL remains the primary metadata/development/test database; MySQL remains the compatibility data source.
- Docker Compose runs Backend, RAG Runtime and Frontend only. It creates no database container or database volume.
- Alembic remains at one head, `20260818_0010`.
- `LocalSemanticEngine`, RAG off/fallback, and Agent off are incident rollback controls, not V1.1.0 release defaults.

## Upgrade

Follow `INSTALL.md`, preserve local `.env` and database backups outside the repository, start Docker Desktop and local PostgreSQL/MySQL, then use the one-click launcher. The launcher never auto-logs in, injects a browser token, creates an anonymous administrator, resets Git, or resets business/metadata data.

## Known non-blocking items

The ECharts route-lazy chunk retains a Vite size warning, MySQL breadth is smaller than the primary PostgreSQL 10M path, and the fixed file interpreter deliberately caps previews/outputs. See `docs/TECH_DEBT_V1_1.md`.

## Release integrity

The release is ready only when the untracked final evidence manifest shows every gate passing on the exact pushed Final Candidate SHA and the tracked worktree is clean. No main push or tag is implied; both require explicit owner authorization.
