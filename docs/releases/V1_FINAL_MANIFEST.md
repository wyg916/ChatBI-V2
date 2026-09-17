# ChatBI V2 V1.0.1 Final Manifest

## Release identity

- Product: ChatBI V2 / ChatBI Core
- Version: `1.0.1`
- Final SHA: the commit peeled from annotated tag `chatbi-v2-v1.0.1`
- Final Tag: `chatbi-v2-v1.0.1`
- Build Date: `2026-08-18`
- Migration Head: `20260817_0008`
- Previous safe rollback target: `4ec4f0eb8e4060cec035d76b1ffbe32d8f80fce0` (`chatbi-v2-v1.0.0`)

The Git object ID cannot be embedded in the commit that determines that ID. After release, the peeled tag, local `main`, `origin/main`, and `ls-remote` main SHA must be identical.

## Final gate results

| Gate | Final result |
| --- | --- |
| Product routes | `DATA_QUERY`, `KNOWLEDGE_QUERY`, `HYBRID_ANALYSIS`, `COMPLEX_ANALYSIS` PASS |
| Live RAG | Runtime, signed bridge, workspace isolation and identity mapping PASS |
| RAG Golden | 120/120; Recall@10 1.0000; citation accuracy 1.0000; unauthorized retrieval 0 |
| Multi-Agent | Five fixed roles, six allowlisted tools and bounded execution PASS |
| Complex analysis | 10/10 evidence-complete cases PASS; trace completeness 100% |
| Agent security | Direct DB, unknown tool, SQL Guard bypass and RBAC bypass all 0 |
| Streaming/performance | Six public progress stages; no chain-of-thought; TTFT/total/tool latency persisted |
| Prompt migration | Six independently authored, versioned prompts with source, purpose and checksum |
| Integration tables | 15/15 runtime tables used and audited |
| Golden Manifest SHA-256 | `25580af42bc76ebddd3d49e6b9c16f8bfabba8ba485a835c453c29175ee2a64a` |
| Golden Result | Original Golden20 PASS; PostgreSQL execution/result/semantic 50/50; MySQL execution/result 10/10 |
| Security Block Rate | 38/38 = 100%; actual successful write attempts 0 |
| Backend Tests | 127/127 PASS |
| Frontend Tests | TypeScript PASS; Vitest 27/27; production build PASS |
| E2E | Serial 51/51 PASS; parallel 153/153 PASS at 5 workers × 3; retries 0 |
| Provider Smoke | Kimi, MiMo, DeepSeek Discovery/Auth/Chat/SQLPlan/Guard PASS |
| UI14 | 14/14 pages retained; browser regression suite PASS |
| Cold Start | Isolated metadata schema PASS in 72.3s |
| One-click Start | Run1 PASS in 54.5s; complete stop; Run2 PASS in 33.2s |
| Migration | Single head; upgrade to head, base, and re-upgrade PASS; temporary schema removed |
| Secret Scan | Tracked secret matches 0; credentials remain only in ignored local environment |
| License Gate | PASS; old production source copy 0; old source imports 0; Git submodules 0 |
| Rollback Simulation | PASS; Day4 baseline validated and migration `0008` restored without touching real business data |

## Architecture and license boundary

RAG and bounded Multi-Agent are required V1 capabilities but remain subordinate to the ChatBI verification chain. The runtime is independently implemented behind project-owned contracts. No old production source, logo, database dump, credential, or provenance-pending payload is distributed. The project remains Apache-2.0; direct dependency notices are in `THIRD_PARTY_NOTICES.md`.

## Known limitations

- Apache ECharts remains an independently lazy-loaded 555.48 kB minified chunk and triggers Vite's 500 kB warning; it is non-blocking.
- V1 provides minimal ADMIN/ANALYST RBAC, not a complete enterprise SSO/OIDC/Vault platform.
- The orchestrator is intentionally fixed to five roles and six tools; it is not a general Agent platform.
- External model availability depends on provider network, quota, pricing and data policies; deterministic routing remains the stable regression baseline.

## Evidence and rollback

- Final evidence index: `docs/evidence/day5/README.md`
- Release notes: `RELEASE_NOTES_V1.md`
- Installation: `README.md` and `INSTALL.md`
- Rollback procedure: `docs/releases/V1_ROLLBACK.md`
