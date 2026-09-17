# Changelog

All notable source-release changes are documented here. Historical evidence remains in `docs/releases/` and `docs/STATUS.md`.

## [1.4.0] - Unreleased

### Added

- Managed Excel/CSV datasources with bounded parsing, isolated PostgreSQL schemas, read-only roles, catalog synchronization, and governed deletion.
- Backend-managed evaluation trend data, member creation, resource permissions, and expanded audit controls.
- Guarded answer presentation shared by chat and analysis endpoints, with truthful SSE deltas and provider trace metadata.
- Distinct dashboard presentations and a draggable, collision-aware semantic model canvas.

### Changed

- Local Showcase can route MiMo, DeepSeek, and Kimi without ChatBI's internal cost admission limits while preserving provider-side quotas and every SQL, result, citation, and answer guard.
- Backup manifests use the V3 contract and preserve current datasource/history semantics.
- GitHub release workflows now run on `main` in addition to their historical release branches.

### Fixed

- Windows PowerShell 5.1 bootstrap argument preservation.
- Streaming gateway contract alignment, datasource/answer lifecycle races, cancellation deadlines, sandbox tombstones, query cancellation, and late provider writes.

### Security

- Expanded sensitive-column lineage propagation and fail-closed response masking.
- Hardened model, SQL, RAG, sandbox, cancellation, and cross-workspace publication boundaries.

## [1.3.1] - 2026-08-29

- Published immutable source release for the V1.3 enterprise-oriented local/private deployment baseline.
- See [V1.3.1 Release Notes](docs/releases/V1_3_1_RELEASE_NOTES.md).

[1.4.0]: https://github.com/wyg916/ChatBI-V2/compare/chatbi-v2-v1.3.1...HEAD
[1.3.1]: https://github.com/wyg916/ChatBI-V2/releases/tag/chatbi-v2-v1.3.1
