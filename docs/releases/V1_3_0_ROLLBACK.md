# ChatBI V1.3.0 Phase 5 Executable Rollback Manifest

Phase 5 is limited to a short-lived candidate branch. Before formal release, rollback is deletion or abandonment of `codex/v1.3.0-release-hardening-full-gate`; the immutable recovery point is Phase 4 SHA `89bdc12936be0555bdad8a85f06932fb7dc476ee`. Do not move historical tags or rewrite Phase 4.

For a deployed candidate, stop Backend, Frontend, RAG runtime, Sandbox Controller and Docker proxy, then restore the exact Phase 4 source/image identity. The Phase 5 restricted proxy has no database state. Temporary performance schemas, users, grants, sessions, attachments and workers must be removed using their run-specific identifiers, and absence must be verified before rollback is accepted. Never use `docker compose down -v`, delete the local PostgreSQL/MySQL databases, or expose credentials in commands or Evidence.

Migration verification uses an isolated PostgreSQL schema and must finish at the existing single V1.3 head `20260822_0012`. The rollback SHA has the same head, so migration downgrade is explicitly `NOT_APPLICABLE_SAME_HEAD`; the dry-run still verifies `alembic current` on both versions. Phase 5 must not edit historical migrations. If a release-discovered data migration defect exists, stop certification and create a new forward migration rather than rewriting history.

## Historical evidence boundary

This V1.3.0 manifest does not authorize executing a rollback runner from current `main`. The old `scripts/test-v13-phase5-rollback-dry-run.ps1` path belongs only to the exact historical source revision that produced its evidence; check out that recorded revision before reproducing the old Phase 5 run. Current source intentionally does not provide that filename.

Current source provides `scripts/test-v131-historical-rollback-dry-run.ps1` only for the fixed V1.3.1-line candidate `852d8aa35a6ec0a31bed34ba695ec6a17034b457` (`0013`) to `89bdc12936be0555bdad8a85f06932fb7dc476ee` (`0012`) path. That runner must not be substituted as V1.3.0 evidence and refuses current `0014` input.

The historical runner performed, in order:

1. exact-SHA/clean-worktree/fast-forward ancestry precheck;
2. archive of the candidate and `89bdc12936be0555bdad8a85f06932fb7dc476ee` runtime/build paths into a guarded temporary directory (non-runtime design assets are excluded so Windows archive extraction is encoding-independent);
3. creation of one run-specific PostgreSQL metadata schema;
4. five-service candidate build/start and health, authenticated Dashboard API readback, browser navigation smoke, and migration-head verification;
5. stopped-state candidate shutdown;
6. explicit no-op migration rollback because both versions have head `20260822_0012`;
7. five-service rollback build/start and the same API/browser/migration checks;
8. equality of the candidate and rollback business-data SHA-256 fingerprints;
9. removal of only the run-specific Compose projects, schema and validated temporary directory.

That historical runner forced deterministic local providers, `LEVEL0`, paid authorization
`NO`, and Level0 paid exception `NO`. Production systems are never targeted.
The Evidence contains image IDs and fingerprints but no tokens, cookies,
passwords, Provider keys or raw private data.

After rollback, rerun Phase 4 Backend, Frontend, browser, Phase 3 Sandbox and IBM gates on the recovery SHA. Preserve the failed Phase 5 Evidence and checksums for diagnosis; never overwrite it with rollback results.
