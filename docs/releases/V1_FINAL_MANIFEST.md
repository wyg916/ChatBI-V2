# ChatBI V2 V1.0.0 Final Manifest

## Release identity

- Product: ChatBI V2 / ChatBI Core
- Version: `1.0.0`
- Final SHA: the commit peeled from annotated tag `chatbi-v2-v1.0.0`
- Final Tag: `chatbi-v2-v1.0.0`
- Build Time: `2026-08-17T23:25:06+08:00`
- Migration Head: `20260817_0007`
- Previous safe rollback target: `d70125f6172dd170c419110fd75d47e87a7f121a` (`chatbi-v2-day4-quality-pass`)

The Git object ID cannot be embedded literally in the same commit whose content determines that ID. The annotated tag's peeled target is therefore the authoritative Final SHA:

```powershell
git rev-parse "chatbi-v2-v1.0.0^{}"
git rev-parse main
git rev-parse origin/main
```

All three must be identical after release finalization.

## Final gate results

| Gate | Final result |
| --- | --- |
| Golden Manifest SHA-256 | `25580af42bc76ebddd3d49e6b9c16f8bfabba8ba485a835c453c29175ee2a64a` |
| Golden Result | Original Golden20 PASS; PostgreSQL execution/result/semantic 50/50; MySQL execution/result 10/10 |
| SQL Accuracy | 50/50 = 100% |
| Result Accuracy | 50/50 = 100% |
| Security Block Rate | 38/38 = 100%; actual successful write attempts 0 |
| Backend Tests | 118/118 PASS |
| Frontend Tests | TypeScript PASS; Vitest 27/27; production build PASS; 731 modules |
| E2E | Serial 36/36 PASS |
| Parallel E2E | 5 workers × 2 rounds = 72/72 PASS; retries 0; runtime race 0 |
| Provider Smoke | Kimi, MiMo, DeepSeek Discovery/Auth/Chat/SQLPlan/Guard PASS; active release provider deterministic |
| UI14 | 14/14 at 1440×900, 1366×768 and 1920×1080; runtime errors 0 |
| Cold Start | PASS in 44.2s using an isolated temporary PostgreSQL metadata schema |
| One-click Start | Run1 PASS in 34.7s; full stop; Run2 PASS in 23.7s |
| Migration | Single head; upgrade → base → upgrade PASS; temporary schema removed |
| Secret Scan | PASS; `.env` ignored; tracked secret artifacts 0; keys absent from evidence/frontend |
| License Gate | PASS for direct pinned dependencies; no copied legacy production source or provenance-pending payload distributed |
| Rollback Simulation | PASS; Day4 safe baseline started and validated, then final candidate restored and validated |

## Third-party summary

The project is Apache-2.0 licensed. SQLGlot and Apache ECharts are used through project-owned boundaries. Backend/frontend direct dependency licenses are summarized in `THIRD_PARTY_NOTICES.md`. Controlled legacy interoperability uses HTTP contracts only; no old production source, logo, database dump, credential, or provenance-pending evaluation payload is distributed.

## Known limitations

- Apache ECharts remains an independently lazy-loaded 555.48 kB minified chunk and triggers Vite's 500 kB warning; the main entry is 273.08 kB and this warning is non-blocking.
- V1 provides minimal ADMIN/ANALYST RBAC, not a complete enterprise SSO/OIDC/Vault platform.
- Optional legacy Agent interoperability remains off because that endpoint cannot receive the ChatBI ToolExecutor callback.
- External model availability depends on provider network, quota, pricing and data policies; the deterministic runtime remains the stable default.

## Evidence and rollback

- Final evidence index: `docs/evidence/day5/README.md`
- Release notes: `RELEASE_NOTES_V1.md`
- Installation: `README.md` and `INSTALL.md`
- Demo: `DEMO.md`
- Rollback procedure: `docs/releases/V1_ROLLBACK.md`
