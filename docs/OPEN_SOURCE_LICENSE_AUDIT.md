# Open-source and supply-chain audit — V1.1.0

## V1.3.0 Phase 2 addendum — 2026-08-21

This addendum supersedes the V1.1 statements that no reviewed upstream source is present. Phase 2 intentionally vendors three exact, license-permitted Python files after a new path-level audit.

| Project | Fixed revision and selected path | Closure | Runtime verdict |
| --- | --- | --- | --- |
| OpenChatBI | `c8786cb...`; `openchatbi/catalog/catalog_store.py` | Root MIT; selected file imports only stdlib and already-pinned SQLAlchemy | PASS, byte-identical pinned vendor module, runtime calls > 0 |
| WrenAI | `7830cc7...`; `core/wren/src/wren/type_mapping.py`, `core/wren/src/wren/mdl/wren_dialect.py` | Selected `core/**` is Apache-2.0; imports only stdlib and already-pinned SQLGlot | PASS, two byte-identical pinned vendor modules, runtime calls > 0 |
| SuperSonic | `af08d86...` | Root adds a commercial derivative-distribution restriction | CLEAN_ROOM only; upstream source calls = 0 |
| IBM Text-to-SQL Evaluation Toolkit | `60dd451...`; official checkout and wheel build | BLOCKED: root LICENSE Apache-2.0, `pyproject.toml` and wheel METADATA MIT; benchmark data closure incomplete | official evaluation calls = 0; ChatBI adapter is clean-room |
| SQLBot | `2a86aa9...`; official repository and exact xpack wheel inspected | BLOCKED: modified GPLv3 branding conditions plus required `sqlbot-xpack 0.0.5.35` with no license metadata/file | service/CLI/database calls = 0; ChatBI feedback is clean-room |

The OpenChatBI/Wren destination blobs match the official locked Git blobs. Their individual SHA-256 values, selected paths, license notice, dependency closure, runtime entry, disable switch and rollback are machine-readable in `docs/UPSTREAM_LOCK.json` and `backend/app/semantic_runtime/_upstream/provenance.json`. Direct upstream reuse count is exactly 2 projects, not 5. This remains an engineering compliance record, not legal advice.

- Audit date: 2026-08-19 (Asia/Shanghai)
- Scope: released backend container, complete frontend lockfile, eight upstream design references, copied source/assets, notices, checksums, rollback boundaries, CycloneDX and SPDX output.
- Result: **PASS for the audited release candidate**. Unknown dependency licenses: **0**. Copied restricted source/UI/logo/model/benchmark assets: **0**.
- Machine-readable inventories: `docs/sbom/V1_1_0.cdx.json` and `docs/sbom/V1_1_0.spdx.json`.
- Reproduction: start the release compose stack, then run `.venv/Scripts/python scripts/release/generate_sbom.py`. The generator exits non-zero when any installed backend or locked frontend package has no normalized license.

This is an engineering compliance record, not legal advice. Any future source incorporation, additional upstream path, version change, model weight, dataset, logo, or redistributed binary requires a new path-level audit before merge.

## Dependency inventory

| Inventory | Source of truth | Components | Unknown licenses | Result |
| --- | --- | ---: | ---: | --- |
| Backend | Packages installed in `chatbi-v2-backend-1` | 64 | 0 | PASS |
| Frontend | Every non-root package in `frontend/package-lock.json` | 255 | 0 | PASS |
| Combined | CycloneDX 1.6 / SPDX 2.3 | 319 | 0 | PASS |

The backend inventory includes first-party `chatbi-*` distributions under the repository's Apache-2.0 license. The frontend inventory includes both runtime and development lock entries and preserves npm scope/integrity metadata. `NOASSERTION` is not used for any package license in the SPDX document.

## Upstream path-level decisions

All revisions below were checked out from their official GitHub remotes in the external audit cache and match `docs/UPSTREAM_LOCK.json`. No reviewed upstream source file is present in the ChatBI repository.

| Project | Locked revision | Audited license boundary | V1.1.0 decision |
| --- | --- | --- | --- |
| [WrenAI](https://github.com/Canner/WrenAI/tree/7830cc746c11602d5899d8fdec1e28de4ce11a87) | `7830cc746c11602d5899d8fdec1e28de4ce11a87` | Selected `core/**` and `sdk/**` Apache-2.0; `docs/**` CC-BY-4.0; future/restricted paths and marks excluded | Project-authored MDL-compatible adapter only; no source, docs, UI, or marks copied |
| [OpenChatBI](https://github.com/zhongyu09/openchatbi/tree/c8786cb180081dbdd18d841efa33b70d77b633e9) | `c8786cb180081dbdd18d841efa33b70d77b633e9` | Root MIT; no more-specific selected-path license | Clean-room catalog/workflow behavior; no source or sample branding copied |
| [SuperSonic](https://github.com/tencentmusic/supersonic/tree/af08d869c4609bf8d48d64e78c61427fe93f7489) | `af08d869c4609bf8d48d64e78c61427fe93f7489` | Root terms based on Apache-2.0 with an additional derivative-distribution restriction | Design study and project-owned semantic contract only; no source-derived distribution |
| [IBM Text-to-SQL Evaluation Toolkit](https://github.com/IBM/text2sql-eval-toolkit/tree/60dd4515236adb335f2053b7c069397d7d88fe0a) | `60dd4515236adb335f2053b7c069397d7d88fe0a` | Apache-2.0 | Project-authored result comparator; no toolkit source or benchmark bundle copied |
| [SQLBot](https://github.com/dataease/SQLBot/tree/2a86aa926c4a22400a4ab4506c3ec384f7855a9d) | `2a86aa926c4a22400a4ab4506c3ec384f7855a9d` | Modified GPLv3 plus logo/copyright conditions | Reference-only; no source, UI, prompt text, brand, or asset copied |
| [Chat2DB](https://github.com/OtterMind/Chat2DB/tree/5372213f267a087c232cb86cae4b200e00c3389f) | `5372213f267a087c232cb86cae4b200e00c3389f` | `LicenseRef-Chat2DB`; object distribution/external-product use restricted for 5.3.0+ | Reference-only; no dependency, service, container, source, UI, or asset used |
| [DB-GPT](https://github.com/eosphoros-ai/DB-GPT/tree/db580e952e544acf9f6c6c153da29dc67e9e40d7) | `db580e952e544acf9f6c6c153da29dc67e9e40d7` | Root MIT for selected application paths; embedded skills require their own path review | Provenance only for a separately authored bounded orchestrator; embedded skills excluded |
| [PandasAI](https://github.com/Sinaptik-AI/pandas-ai/tree/bbbb771d31062d81f6fa19bafb40620d5cbe48f4) | `bbbb771d31062d81f6fa19bafb40620d5cbe48f4` | Community paths MIT; all `ee/**` paths under enterprise terms | Not imported or packaged; file analysis is a project-owned fixed-operation interpreter |

## Source, asset, and secret checks

- `docs/UPSTREAM_LOCK.json` records repository, exact SHA, selected paths, license files, SHA-256 checksum, allowed/forbidden use, runtime entry, fallback, and rollback.
- `THIRD_PARTY_NOTICES.md` records direct package and design provenance notices. The SQLBot revision is aligned with the locked audit SHA.
- The final security runner scans tracked files for credential patterns and scans prohibited upstream names/import forms. It records findings in the final-SHA security artifact.
- The legacy project's production source, private evaluation payloads, database dumps, credentials, model weights, logos, and UI assets are excluded from the public release.

## Release conditions and rollback

1. Preserve `docs/UPSTREAM_LOCK.json`, this audit, both SBOMs, and `THIRD_PARTY_NOTICES.md` in every V1.1.0 distribution.
2. Keep Wren/OpenChatBI/SuperSonic behind `SemanticEngine`; keep IBM behind `EvaluationAdapter`; keep the RAG bridge behind `RagAdapter`.
3. Default fallbacks must remain available: local semantic engine, ChatBI Result Oracle, bounded local catalog scoring, and project-owned file/agent runtimes.
4. If an audited license changes or an unknown license appears, block release and use the recorded per-capability rollback; do not silently substitute source.
