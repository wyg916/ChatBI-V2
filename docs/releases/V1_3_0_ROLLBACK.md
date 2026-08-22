# ChatBI V1.3.0 Phase 5 Rollback Plan

Phase 5 is limited to a short-lived candidate branch. Before formal release, rollback is deletion or abandonment of `codex/v1.3.0-release-hardening-full-gate`; the immutable recovery point is Phase 4 SHA `89bdc12936be0555bdad8a85f06932fb7dc476ee`. Do not move historical tags or rewrite Phase 4.

For a deployed candidate, stop Backend, Frontend, Sandbox Controller and Docker proxy, then restore the Phase 4 application images/configuration. The Phase 5 restricted proxy has no database state. Temporary performance schemas, users, grants, sessions, attachments and workers must be removed using their run-specific identifiers, and absence must be verified before rollback is accepted.

Migration verification uses an isolated PostgreSQL schema and must finish at the existing single V1.3 head. Phase 5 must not edit historical migrations. If a release-discovered data migration defect exists, stop certification and create a new forward migration rather than rewriting history.

After rollback, rerun Phase 4 Backend, Frontend, browser, Phase 3 Sandbox and IBM gates on the recovery SHA. Preserve the failed Phase 5 Evidence and checksums for diagnosis; never overwrite it with rollback results.
