# ChatBI V2 v1.3.1

ChatBI V2 v1.3.1 is an **Enterprise-oriented Open-source ChatBI / NL2SQL Platform** source release. It supports local deployment, Enterprise PoC, private-deployment validation and secondary development. It is not a production-deployment certification.

## Highlights

1. Fixed conversation intent routing, context isolation and stale-answer handling.
2. Improved chart/table rendering and automatic positioning for long answers.
3. Closed the MiMo (`mimo-v2.5`), DeepSeek (`deepseek-v4-flash`) and Kimi (`kimi-k2.6`) configuration, status and single-Model-Gateway path.
4. Added Query and Security Settings with explicit server-side enforcement boundaries.
5. Added Workspace, Appearance and read-only System Information views.
6. Added User, Role, Invitation, Audit and RBAC administration closure.
7. Preserved the independently certified actionable-control baseline: 894/894 PASS, with integration-delta controls PASS.
8. Added enterprise quick-deployment workflows for Doctor, Bootstrap, Start/Stop, Backup/Restore, Configuration and Troubleshooting.
9. Unified three supported modes: Default Open Source, Local Showcase and Enterprise PoC.
10. Advanced the unique Alembic migration head to `20260828_0013`; the V1.3.0 rollback target remains `20260822_0012`.
11. Passed Golden 50 execution, result-value and semantic/Oracle gates.
12. Passed two independent clean Enterprise deployment validations.

## Certified release evidence

- Backend: 704 collected, 697 passed, 7 designed skips, 0 failed, 0 errors.
- Frontend: 64/64 tests, TypeScript diagnostics 0, production build PASS.
- Browser core experience: 45/45 PASS at the certified integration SHA.
- PostgreSQL and MySQL: connection, read-only enforcement, Schema/Catalog sync and representative query PASS.
- Exact-SHA live Provider smoke: MiMo, DeepSeek and Kimi PASS through the single Model Gateway with no direct-provider bypass.
- Migration: empty database to `0013`, `0013 → 0012 → 0013`, and existing `0012 → 0013` PASS.
- Fresh Enterprise deployment: 2/2 PASS.

The final Release SHA, annotated-tag object, GitHub Release ID/URL, checksums and exact publication timestamp are recorded in the external V1.3.1 Final Release Manifest because a Git commit cannot self-record its own immutable identity.

## Known risks

- Graceful shutdown can still report exit code 137 for Backend/Sandbox Proxy while Docker reports `OOMKilled=false`. No corruption, resource leak or restart failure was observed; this remains registered and non-blocking for this source release.
- External Provider billing remains `UNKNOWN_PARTIAL`; the exact-SHA test ledger records the bounded calls and confirmed internal cost estimate, but does not claim complete provider-side billing reconciliation.

## Production boundary

This release does **not** include production deployment certification. Kubernetes, Helm, HA PostgreSQL, multi-node disaster recovery, production monitoring/SLA, production key rotation, signed immutable production OCI, new Enterprise SSO development and Terraform are deferred. Additional enterprise hardening is required before production deployment.

Local Showcase credentials documented elsewhere are `LOCAL_SHOWCASE_ONLY` and must never be used as Enterprise defaults.
