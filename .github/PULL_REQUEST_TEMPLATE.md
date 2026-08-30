## Summary

Describe the problem and the smallest change that solves it.

## ChatBI scope

- [ ] This change serves the datasource → semantic model → governed query → verified result → answer/dashboard → evaluation workflow.
- [ ] It does not introduce a general AI platform, unrestricted agent/tool system, prediction platform, or plugin marketplace.

## Security and data boundaries

- [ ] Frontend code uses only Backend APIs and stores no database or provider credential.
- [ ] SQL remains read-only and passes authorization, AST guard, timeout, row-limit, audit, and Result Oracle controls.
- [ ] Logs, fixtures, screenshots, and evidence contain no secret, customer data, internal path, or private endpoint.
- [ ] New third-party code or assets include provenance, license review, and notice updates.

## Validation

List every command actually run and its result. Include relevant backend, frontend, migration, Golden, E2E, build, and security checks. Do not mark unrun checks as passed.

## Known limitations and rollback

Describe residual risk, migration/rollback impact, and any operator action.
