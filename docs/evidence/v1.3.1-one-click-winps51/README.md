# V1.3.1 Windows one-click startup compatibility evidence

Date: 2026-08-29
Scope: P0 Local Showcase startup; deterministic / LEVEL0 / no paid Provider calls.

## Failure reproduction

- Entry: root `一键启动-ChatBI-V2.cmd`.
- Runtime: Windows PowerShell 5.1.26100.9168.
- Baseline: `dddca12d3f4a337c51a12ce5cd9a880239b8429d`.
- Result: `bootstrap.ps1` passed PowerShell parsing but the nested `sh -c` command reduced the Python `-c` payload to `from`; Python raised `SyntaxError`, followed by `BOOTSTRAP=FAIL` and `START=FAIL`.

## Fix and validation

- Removed the nested shell command and passed readiness, migration verification, and deployment bootstrap as separate Docker argument calls.
- PowerShell parse: `bootstrap.ps1`, `start.ps1`, and `showcase.ps1` all PASS.
- V1.3.1 integration contract: 7/7 PASS.
- Related deployment, system, Showcase reset, and migration tests: 20/20 PASS.
- Run 1: zero Showcase containers → exact root CMD → `BOOTSTRAP=PASS`, `VERIFY=PASS`, `START=PASS`.
- Run 2: zero Showcase containers → Windows PowerShell 5.1 Showcase start → `BOOTSTRAP=PASS`, `VERIFY=PASS`, `START=PASS`.
- Migration: `20260828_0013 (head)` on both runs.
- Final services: Backend, RAG Runtime, Frontend, Sandbox Controller, and Sandbox Docker Proxy are 5/5 healthy.
- HTTP: Frontend 200; Backend version reports 1.3.1; five protected API probes return 401 anonymously.
- External Provider calls: 0.
- Database boundary: existing local PostgreSQL/MySQL preserved; no database container or Docker database volume added.
