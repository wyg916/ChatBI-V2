# V1.1.0 non-blocking technical debt

These items do not weaken a V1.1.0 hard gate. Anything affecting accuracy, isolation, read-only safety, final-SHA evidence, or release reproducibility is a blocker and is not allowed on this list.

| Priority | Item | Current containment | Exit criterion |
| --- | --- | --- | --- |
| P1 | ECharts lazy chunk remains about 555 kB and triggers a Vite warning | route-level lazy loading keeps it out of the entry bundle; no functional failure | selective imports or stable chunk split without chart regression |
| P1 | MySQL is a compatibility path rather than the primary 10M load source | PostgreSQL is primary; MySQL catalog/query/Golden compatibility remains gated | expand dialect Golden and performance coverage after P0 release |
| P1 | Evaluation profile metadata is stored in an existing typed metadata field | API filters it and evidence remains persisted/auditable | dedicated migration after release with backward-compatible data move |
| P1 | Fixed-operation file analysis caps extracted/returned rows | UI states the limitation; no generated code surface exists | governed larger-data execution with the same isolation and resource limits |
| P1 | Local deterministic hybrid retrieval is intentionally compact | ACL, citation, no-evidence and Golden accuracy are hard gated | replace only behind `RagAdapter` with equal/better Golden and security results |
| P1 | Release scripts are Windows/PowerShell-first | Docker and Python gates are reproducible; documented versions are pinned | add CI parity for Linux without changing local-DB ownership |
| P1 | Starlette 1.3 emits a test-only deprecation warning for its legacy `httpx` TestClient adapter | runtime and browser/API gates pass; the warning does not affect production ASGI requests | adopt the supported `httpx2` test adapter after FastAPI test tooling stabilizes, with full regression |

No P2 platform expansion—general Agent marketplace, generic knowledge-base lifecycle, long-term memory/forgetting, prediction platform, deep OIDC/Vault, or unrelated workflow—is accepted as V1.1.0 debt or a release blocker.
