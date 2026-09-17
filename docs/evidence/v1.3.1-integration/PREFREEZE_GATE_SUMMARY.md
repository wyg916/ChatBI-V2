# V1.3.1 integration pre-freeze gate summary

Date: 2026-08-28

This repository record contains only sanitized, reproducible gate facts. Live
provider responses, local environment values, credentials, database URLs, and
post-freeze exact-SHA evidence belong outside the repository.

## Provenance and merge

- Integration base C: `fbb42a48568985808dbbc12d07728abcb59febc9`
- B source: `656496a470404390d0324b8cdddd4666e4423b6c`
- A main: `8f0326b59759e2549e7f684f0a3e40e3b6faffdf`
- V1.3.0 release: `52db955fd67ebe592c289399a135528c13cb3e3d`
- Strategy: `--no-ff --no-commit`, six manual text-conflict receipts, then one merge commit
- Merge commit: `9d2dbef8841cfbfab22fb685e58163612e85debe`
- Text conflicts: 6 resolved, 0 unresolved
- Semantic conflicts: 6 resolved, 0 unresolved

## Validated gates

- PowerShell parsing: all deployment scripts PASS
- `.env.example`: 100 unique keys, zero duplicates, three complete provider sets, no real keys
- ADRs: 92 unique IDs, zero broken references
- Compose matrix: Default/Showcase/Enterprise all render; one canonical file; active database services 0; database volumes 0
- Backend: 704 collected, 697 passed, 7 designed skips, 0 failed, 0 errors
- Frontend: 16 files / 64 tests PASS; TypeScript diagnostics 0; production build 991 modules
- Migration: one head `20260828_0013`; empty, rollback roundtrip, and existing-0012 upgrade PASS
- Doctor: 0 failures, 0 warnings, provider live calls 0
- Sandbox: worker succeeded with result 9, verified runtime, destroyed worker, shared resolved image, orphan count 0
- Golden50: execution 50/50, result value 50/50, semantic 50/50, dangerous SQL 56/56
- Datasources: PostgreSQL and MySQL each synchronized 1 schema, 9 tables, 56 columns, and 12 relationships; representative read-only query returned 1,095 orders; write SQL was rejected
- Consecutive starts: 2/2 from fully stopped, each 5/5 healthy with login and anonymous 401 smoke
- Showcase: isolated metadata Schema reset/start/status/stop PASS; browser 45/45; deterministic Level0; paid calls 0
- C integration delta: administrator settings/provider/RBAC/invitation/audit writes, API/DB readback, analyst 403, and restart persistence PASS; runtime errors 0
- Backup/restore: V2 manifest at migration `0013`; nonzero settings/provider/invitation/RBAC/workspace state; forced mutation changed the fingerprint; restore returned it exactly
- A restoration: A's own Showcase Status/Verify/Login PASS at 15173/18080/18081; 5/5 healthy; main and origin/main remain exact and clean

## Freeze boundary

Enterprise Fresh 2/2, final secret scans, exact-SHA live Provider smoke, cleanup,
remote push, and remote SHA comparison must execute against the eventual clean
semantic-fix commit. They are not pre-declared PASS here.
