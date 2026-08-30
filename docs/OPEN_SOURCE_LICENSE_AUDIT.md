# Open-source and supply-chain audit — V1.4.0 release candidate

## V1.4.0 release-candidate ownership and redistribution declaration — 2026-08-30

This document now describes the V1.4.0 release candidate. Earlier V1.1.0 and
V1.3.0 sections below are retained as the chronological audit record; where an
older statement conflicts with this section, this current declaration governs
the files distributed by the V1.4.0 release candidate.

### Owner-attested original Legacy RAG contribution

The project owner attests original authorship of the selected source recorded in
`backend/vendor/legacy_energy_rag/b2573a9dc1881a54581c5c556fb4a8c34046f9c3/LOCK.json`
and contributes the following three byte-identical selected-source files to
ChatBI V2 under the repository's Apache License 2.0:

- `app/knowledge/indexer.py`
- `app/knowledge/reranker.py`
- `app/knowledge/security.py`

This is an owner-attested original contribution for public distribution. The
root `LICENSE` applies to the copies stored below the locked vendor directory.
The source commit, Git blob identities, SHA-256 values, dependency/data closure
and rollback boundary are recorded in the machine-readable `LOCK.json`; the
corresponding owner notice is
`docs/runtime/V1_3_PHASE3_OWNER_AUTHORIZED_LEGACY_RAG_LOCK.md`. No other source,
data, credential, UI, model, logo or asset from that legacy project is granted
or distributed by this declaration.

The `SELECTED_SOURCE_VENDORED_RUNTIME` integration mode is a runtime topology
only. It is neither a private/internal license nor a separately published
package; redistribution of the three files is governed solely by the
owner-attested original contribution under Apache-2.0.

### Project-owned UI reference assets

The project owner confirms that `ChatBI_V2_完整UI设计参考包_高清版/` is original,
project-owned ChatBI V2 design material. Its HTML, PNG, JSON and Markdown files
are contributed with this repository under Apache License 2.0. The reference
pack contains no copied third-party UI, logo, font, trademark or restricted
brand asset. Its pages remain design and acceptance references; runtime product
behavior is implemented by the project-owned frontend source.

For the V1.4.0 release-candidate distribution, the accurate result is:

- restricted or unlicensed copied source, UI, logo, model or benchmark assets: **0**;
- owner-attested original contribution: **3 locked Legacy RAG Python files**, Apache-2.0;
- owner-contributed original UI reference pack: **included**, Apache-2.0;
- the V1.4.0 candidate SBOMs have been regenerated from 106 Backend and 353
  Frontend components with zero unknown licenses; publication remains conditional
  on rebinding their checksums and every final gate to the frozen release SHA.

## V1.3.0 Phase 3 addendum — 2026-08-22

Phase 3 preserves every Phase 2 and SQLBot exception decision and raises direct upstream reuse from three to five projects through two narrow, independently attributable paths:

- DB-GPT `packages/dbgpt-core` at `db580e952e544acf9f6c6c153da29dc67e9e40d7`, installed from exact Git provenance or the canonical archive whose SHA-256 is `e225a2e222874adfb504e03f6a2d091729d8ecb2c874783fd4bcbc2c7c8ef31b`. Only MIT-licensed AWEL `DAG`, `MapOperator` and `BaseOperator.call` execute. `dbgpt-app`, RAG, datasource/connectors, auth, conversation, credentials, embedded skills and assets remain excluded.
- PandasAI community `pandasai/sandbox/sandbox.py` at `bbbb771d31062d81f6fa19bafb40620d5cbe48f4`, Git blob `6f31f9dfd3dbd023c7f82a1533bb3c577efd19fd`, byte SHA-256 `a6d4934cffc70d8a325071d8ab94b12ec0ded9043cdc01e9ba3a4d1f64d210c6`. The exact MIT file and license are retained; every `ee/**` path and the root import closure that loads EE remain excluded.

The DB-GPT runtime never receives raw questions, SQL, keys, datasource/model identifiers, connectors, RAG state or tool outputs. The PandasAI base `Sandbox.execute` delegates to a ChatBI worker with no host mounts, secrets or external network. Both boundaries fail closed on missing/mismatched provenance. Detailed selected paths, checksums, retained licenses, runtime entry, fallback and rollback are machine-readable in `docs/UPSTREAM_LOCK.json`. This is an engineering compliance record, not legal advice.

## V1.3.0 Phase 2 addendum — 2026-08-21

This addendum supersedes the V1.1 statements that no reviewed upstream source is present. Phase 2 intentionally vendors three exact, license-permitted Python files after a new path-level audit.

| Project | Fixed revision and selected path | Closure | Runtime verdict |
| --- | --- | --- | --- |
| OpenChatBI | `c8786cb...`; `openchatbi/catalog/catalog_store.py` | Root MIT; selected file imports only stdlib and already-pinned SQLAlchemy | PASS, byte-identical pinned vendor module, runtime calls > 0 |
| WrenAI | `7830cc7...`; `core/wren/src/wren/type_mapping.py`, `core/wren/src/wren/mdl/wren_dialect.py` | Selected `core/**` is Apache-2.0; imports only stdlib and already-pinned SQLGlot | PASS, two byte-identical pinned vendor modules, runtime calls > 0 |
| SuperSonic | `af08d86...` | Root adds a commercial derivative-distribution restriction | CLEAN_ROOM only; upstream source calls = 0 |
| IBM Text-to-SQL Evaluation Toolkit | `60dd451...`; fixed checkout, 11 exact selected files, wheel/sdist audit | PASS for selected Apache-2.0 source only; package/wheel/sdist remain BLOCKED because root LICENSE is Apache-2.0 while distribution metadata says MIT | official `evaluate_prediction` calls = 50; `get_failed_records` executions = 1; no source/package copied or distributed |
| SQLBot | `2a86aa9...`; official repository and exact xpack wheel inspected | BLOCKED: modified GPLv3 branding conditions plus required `sqlbot-xpack 0.0.5.35` with no license metadata/file | service/CLI/database calls = 0; ChatBI feedback is clean-room |

The OpenChatBI/Wren destination blobs match the official locked Git blobs. Their individual SHA-256 values, selected paths, license notice, dependency closure, runtime entry, disable switch and rollback are machine-readable in `docs/UPSTREAM_LOCK.json` and `backend/app/semantic_runtime/_upstream/provenance.json`. IBM runs outside the repository from a fixed checkout and validates all 11 selected hashes before execution. Direct upstream reuse count is exactly 3 projects, not the target 4. This remains an engineering compliance record, not legal advice.

The V1.3.0 SQLBot direct-runtime target is superseded by the controlled [`SQLBot License and Runtime Requirement Exception`](opensource/V1_3_SQLBOT_LICENSE_EXCEPTION.md). The pinned tree has no path-specific grant that relaxes the modified root terms; official startup necessarily imports an unclosed XPack package, and no immutable commit-bound official runtime artifact is publicly reproducible. Therefore `SQLBOT_DIRECT_UPSTREAM_REUSE=BLOCKED_BY_UPSTREAM_LICENSE`, official calls and XPack loads remain zero, and the ChatBI-owned feedback/replay path is not counted as upstream reuse.

- Audit date: 2026-08-30 (Asia/Shanghai); the dependency inventory below was regenerated for the V1.4.0 working candidate and must be checksum-bound again after the final release SHA is frozen.
- Scope: release-candidate backend/frontend sources, complete frontend lockfile, selected upstream and owner-contributed source, original project assets, notices, checksums, rollback boundaries, and regenerated CycloneDX/SPDX output at the final frozen SHA.
- Pre-freeze observation: restricted or unlicensed copied source/UI/logo/model/benchmark assets: **0**; unknown package licenses: **0**. This observation is not a publication PASS; exact release status remains conditional on the frozen-SHA gates and post-publication external attestation.
- Machine-readable inventories: `docs/sbom/V1_4_0.cdx.json` and `docs/sbom/V1_4_0.spdx.json`.
- Reproduction: start the release compose stack, then run `.venv\Scripts\python.exe scripts\release\generate_sbom.py --backend-container <backend-container>`. The generator exits non-zero when any installed backend or locked frontend package has no normalized license.

This is an engineering compliance record, not legal advice. Any future source incorporation, additional upstream path, version change, model weight, dataset, logo, or redistributed binary requires a new path-level audit before merge.

## Last generated dependency inventory (V1.4.0 candidate)

The following counts describe the current V1.4.0 working candidate. The final
release gate must verify or regenerate both SBOM formats from the frozen
candidate and fail if any component has an unknown license.

| Inventory | Source of truth | Components | Unknown licenses | Result |
| --- | --- | ---: | ---: | --- |
| Backend | Packages installed in the release Backend container | 106 | 0 | Candidate inventory; final recheck required |
| Frontend | Every non-root package in `frontend/package-lock.json` | 353 | 0 | Candidate inventory; final recheck required |
| Combined | CycloneDX 1.6 / SPDX 2.3 | 459 | 0 | Candidate inventory; final recheck required |

The backend inventory includes first-party `chatbi-*` distributions under the repository's Apache-2.0 license. The frontend inventory includes both runtime and development lock entries and preserves npm scope/integrity metadata. `NOASSERTION` is not used for any package license in the SPDX document.

## Upstream path-level decisions

All revisions below were checked against their official origins and match `docs/UPSTREAM_LOCK.json`. Only the explicitly licensed, checksum-locked selected-source files documented in this audit are present; all reference-only projects remain source-excluded.

| Project | Locked revision | Audited license boundary | V1.1.0 decision |
| --- | --- | --- | --- |
| [WrenAI](https://github.com/Canner/WrenAI/tree/7830cc746c11602d5899d8fdec1e28de4ce11a87) | `7830cc746c11602d5899d8fdec1e28de4ce11a87` | Selected `core/**` and `sdk/**` Apache-2.0; `docs/**` CC-BY-4.0; future/restricted paths and marks excluded | Project-authored MDL-compatible adapter only; no source, docs, UI, or marks copied |
| [OpenChatBI](https://github.com/zhongyu09/openchatbi/tree/c8786cb180081dbdd18d841efa33b70d77b633e9) | `c8786cb180081dbdd18d841efa33b70d77b633e9` | Root MIT; no more-specific selected-path license | Clean-room catalog/workflow behavior; no source or sample branding copied |
| [SuperSonic](https://github.com/tencentmusic/supersonic/tree/af08d869c4609bf8d48d64e78c61427fe93f7489) | `af08d869c4609bf8d48d64e78c61427fe93f7489` | Root terms based on Apache-2.0 with an additional derivative-distribution restriction | Design study and project-owned semantic contract only; no source-derived distribution |
| [IBM Text-to-SQL Evaluation Toolkit](https://github.com/IBM/text2sql-eval-toolkit/tree/60dd4515236adb335f2053b7c069397d7d88fe0a) | `60dd4515236adb335f2053b7c069397d7d88fe0a` | Apache-2.0 | Project-authored result comparator; no toolkit source or benchmark bundle copied |
| [SQLBot](https://github.com/dataease/SQLBot/tree/2a86aa926c4a22400a4ab4506c3ec384f7855a9d) | `2a86aa926c4a22400a4ab4506c3ec384f7855a9d` | Modified GPLv3 plus logo/copyright conditions | Reference-only; no source, UI, prompt text, brand, or asset copied |
| [Chat2DB](https://github.com/OtterMind/Chat2DB/tree/5372213f267a087c232cb86cae4b200e00c3389f) | `5372213f267a087c232cb86cae4b200e00c3389f` | `LicenseRef-Chat2DB`; object distribution/external-product use restricted for 5.3.0+ | Reference-only; no dependency, service, container, source, UI, or asset used |
| [DB-GPT](https://github.com/eosphoros-ai/DB-GPT/tree/db580e952e544acf9f6c6c153da29dc67e9e40d7) | `db580e952e544acf9f6c6c153da29dc67e9e40d7` | Root MIT for `packages/dbgpt-core`; embedded skills and application surfaces excluded | V1.1/Day 2 provenance-only conclusion is superseded solely for the Phase 3 core/AWEL selected runtime above |
| [PandasAI](https://github.com/Sinaptik-AI/pandas-ai/tree/bbbb771d31062d81f6fa19bafb40620d5cbe48f4) | `bbbb771d31062d81f6fa19bafb40620d5cbe48f4` | Selected community sandbox file MIT; all `ee/**` paths under enterprise terms | V1.1/Day 2 not-imported conclusion is superseded solely for the exact Phase 3 community sandbox file above |

## Source, asset, and secret checks

- `docs/UPSTREAM_LOCK.json` records repository, exact SHA, selected paths, license files, SHA-256 checksum, allowed/forbidden use, runtime entry, fallback, and rollback.
- `THIRD_PARTY_NOTICES.md` records direct package and design provenance notices. The SQLBot revision is aligned with the locked audit SHA.
- The final security runner scans tracked files for credential patterns and scans prohibited upstream names/import forms. It records findings in the final-SHA security artifact.
- Except for the three owner-attested original, hash-locked Legacy RAG contributions explicitly licensed under Apache-2.0 above, the legacy project's production source, private evaluation payloads, database dumps, credentials, model weights, logos, and UI assets are excluded from the public release.

## Release conditions and rollback

1. Preserve `docs/UPSTREAM_LOCK.json`, this audit, both V1.4.0 SBOMs, and `THIRD_PARTY_NOTICES.md` in every V1.4.0 distribution.
2. Keep Wren/OpenChatBI/SuperSonic behind `SemanticEngine`; keep IBM behind `EvaluationAdapter`; keep the RAG bridge behind `RagAdapter`.
3. Default fallbacks must remain available: local semantic engine, ChatBI Result Oracle and deterministic full-file operations. A DB-GPT or Sandbox provenance/runtime failure must be labelled and fail closed; it must never be reported as a verified upstream call.
4. If an audited license changes or an unknown license appears, block release and use the recorded per-capability rollback; do not silently substitute source.
