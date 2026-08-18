# Open-source license audit draft — v2.1 Day 1

- Observed: 2026-08-18 (Asia/Shanghai)
- Evidence cache: `D:\Codex\home\upstream-audit` (outside this repository)
- Scope: repository tree, root/subdirectory licenses, package manifests, representative headers and exact commit SHA.
- Result: no third-party source, UI, logo or brand asset is copied by Day 1. The three active semantic integrations are ChatBI-owned clean-room adapters behind explicit interfaces.

| Project | Locked SHA | License finding | Day 1 decision |
|---|---|---|---|
| WrenAI | `7830cc746c11602d5899d8fdec1e28de4ce11a87` | Multi-license map: `core/**` and `sdk/**` Apache-2.0, `docs/**` CC-BY-4.0; trademarks excluded | Public MDL-compatible clean-room runtime; no code or marks copied |
| OpenChatBI | `c8786cb180081dbdd18d841efa33b70d77b633e9` | MIT | Clean-room catalog/linking workflow; retain upstream as design provenance |
| SuperSonic | `af08d869c4609bf8d48d64e78c61427fe93f7489` | Apache-2.0 plus commercial derivative-distribution condition | Clean-room SemanticQuery pipeline; no derivative source distribution |
| IBM text2sql toolkit | `60dd4515236adb335f2053b7c069397d7d88fe0a` | Apache-2.0 | Locked only; frozen B is not merged on Day 1 |
| SQLBot | `2a86aa926c4a22400a4ab4506c3ec384f7855a9d` | Modified GPLv3 with logo/copyright conditions | Design-only/clean-room; no UI or source copy |
| Chat2DB | `5372213f267a087c232cb86cae4b200e00c3389f` | `LicenseRef-Chat2DB`; external product/object distribution restricted | Design-only; current source is forbidden for ChatBI product embedding |
| DB-GPT | `db580e952e544acf9f6c6c153da29dc67e9e40d7` | MIT root plus path-specific skill licenses | Locked only for later path-level review |
| PandasAI | `bbbb771d31062d81f6fa19bafb40620d5cbe48f4` | MIT community paths; enterprise license under any `ee/**` path | Community-only candidate; all enterprise paths forbidden |

The machine-readable repository, version, selected paths, checksums, runtime entries, allowed/forbidden usage, fallback and rollback fields are in `docs/UPSTREAM_LOCK.json`. This is an engineering draft, not legal advice; any move from clean-room behavior to source incorporation requires a new path-level review and an update to `THIRD_PARTY_NOTICES.md` before merge.
