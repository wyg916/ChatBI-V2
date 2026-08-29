# ChatBI V2 v1.3.1

## Immutable published release

ChatBI V2 v1.3.1 is an **Enterprise-oriented Open-source ChatBI / NL2SQL Platform** source release. The published annotated tag `chatbi-v2-v1.3.1` peels to commit `dddca12d3f4a337c51a12ce5cd9a880239b8429d`. It supports local deployment, Enterprise PoC, private-deployment validation and secondary development. It is not a production-deployment certification.

### Published highlights

1. Fixed conversation intent routing, context isolation and stale-answer handling.
2. Improved chart/table rendering and automatic positioning for long answers.
3. Closed the MiMo (`mimo-v2.5`), DeepSeek (`deepseek-v4-flash`) and Kimi (`kimi-k2.6`) configuration, status and single-Model-Gateway path.
4. Added Query and Security Settings with explicit server-side enforcement boundaries.
5. Added Workspace, Appearance and read-only System Information views.
6. Added User, Role, Invitation, Audit and RBAC administration closure.
7. Preserved the independently certified actionable-control baseline: 894/894 PASS, with integration-delta controls PASS.
8. Added enterprise quick-deployment workflows for Doctor, Bootstrap, Start/Stop, Backup/Restore, Configuration and Troubleshooting.
9. Unified three supported modes: Default Open Source, Local Showcase and Enterprise PoC.
10. Advanced the unique Alembic migration head to `20260828_0013`; the immutable V1.3.0 rollback target remains `20260822_0012`.
11. Passed Golden 50 execution, result-value and semantic/Oracle gates.
12. Passed two independent clean Enterprise deployment validations.

### Certified tag evidence

- Backend: 704 collected, 697 passed, 7 designed skips, 0 failed, 0 errors.
- Frontend: 64/64 tests, TypeScript diagnostics 0, production build PASS.
- Browser core experience: 45/45 PASS at the certified integration SHA.
- PostgreSQL and MySQL: connection, read-only enforcement, Schema/Catalog sync and representative query PASS.
- Exact-SHA live Provider smoke: MiMo, DeepSeek and Kimi PASS through the single Model Gateway with no direct-provider bypass.
- Migration: empty database to `0013`, `0013 → 0012 → 0013`, and existing `0012 → 0013` PASS.
- Fresh Enterprise deployment: 2/2 PASS.

These totals and claims certify only the immutable published tag above. They must not be reused as evidence for later `main` changes. The annotated-tag object, GitHub Release ID/URL, checksums and exact publication timestamp remain recorded in the external V1.3.1 Final Release Manifest.

## Unreleased `0014` main successor

The current working-tree successor is not part of `chatbi-v2-v1.3.1` and has not been published as a release. It introduces Alembic head `20260829_0014` for managed spreadsheet datasource metadata, with direct downgrade target `20260828_0013`; it also moves new backups to the `chatbi-enterprise-backup-v3` contract and requires matching-source restore semantics.

Current source regression covers empty database to `0014`, existing `0013 → 0014`, and the managed-datasource downgrade guard. That incremental regression does not inherit the tag's Backend, Frontend, browser, Provider or fresh-deployment totals. The successor requires its own complete release gates and evidence before any new release claim; current progress and remaining gates are tracked in `docs/STATUS.md`.

## Known risks

- Graceful shutdown can still report exit code 137 for Backend/Sandbox Proxy while Docker reports `OOMKilled=false`. No corruption, resource leak or restart failure was observed; this remains registered and non-blocking for this source release.
- External Provider billing remains `UNKNOWN_PARTIAL`; the exact-SHA test ledger records the bounded calls and confirmed internal cost estimate, but does not claim complete provider-side billing reconciliation.

## Production boundary

This release does **not** include production deployment certification. Kubernetes, Helm, HA PostgreSQL, multi-node disaster recovery, production monitoring/SLA, production key rotation, signed immutable production OCI, new Enterprise SSO development and Terraform are deferred. Additional enterprise hardening is required before production deployment.

Local Showcase credentials documented elsewhere are `LOCAL_SHOWCASE_ONLY` and must never be used as Enterprise defaults.
