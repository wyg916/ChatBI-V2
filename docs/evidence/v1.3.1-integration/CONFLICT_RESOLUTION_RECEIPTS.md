# V1.3.1 Integration Conflict Resolution Receipts

Integration base: `fbb42a48568985808dbbc12d07728abcb59febc9`

B source: `656496a470404390d0324b8cdddd4666e4423b6c`

Strategy: `git merge --no-ff --no-commit 656496a470404390d0324b8cdddd4666e4423b6c`

## Receipt 1

- FILE: `README.md`
- C_BEHAVIOR: Chinese ChatBI-first product narrative, immutable V1.3.0 release facts, seven Showcase capabilities, local one-click operation, videos, and interview material.
- B_BEHAVIOR: Enterprise-oriented open-source positioning, Quick Start, Doctor/Bootstrap, configuration, Provider, datasource, backup/restore, private deployment, security, and explicit production limitations.
- FINAL_BEHAVIOR: One answer-first README keeps the enterprise positioning and core product path, then documents Default Open Source, Local Showcase, and Enterprise PoC as distinct modes. Showcase remains explicitly local/portfolio-only and all A/B guides remain linked.
- WHY: Neither side alone described the full supported product without misclassifying Showcase as enterprise deployment or dropping enterprise operations.

## Receipt 2

- FILE: `backend/Dockerfile`
- C_BEHAVIOR: Documents why RapidOCR requires GLib/XCB/OpenGL libraries and keeps the layer cache-stable.
- B_BEHAVIOR: Documents the same packages as a stable layer and calls out the avoided 220 MB reinstall.
- FINAL_BEHAVIOR: Keep C's technically explicit import-failure explanation and the shared cache-stable package installation.
- WHY: Runtime packages are identical; the more precise failure explanation is safer for future diagnosis and does not change B build behavior.

## Receipt 3

- FILE: `docker-compose.yml`
- C_BEHAVIOR: Provides build identity (`CHATBI_GIT_SHA`, release version, frontend build), a development default, and a legacy local database fallback.
- B_BEHAVIOR: Makes project/image/port/storage identity configurable, defaults environment to local, requires an explicit PostgreSQL URL, and adds project-scoped operations.
- FINAL_BEHAVIOR: Keep B's canonical project-scoped Compose and required external PostgreSQL URL, while retaining C build identity variables. Environment remains mode-configurable rather than hard-coded.
- WHY: Enterprise Fresh must fail fast without an explicit database while Showcase supplies its own development-mode process values; build identity must remain observable.

## Receipt 4

- FILE: `docs/DECISIONS.md`
- C_BEHAVIOR: Records immutable release/Showcase maintenance, local database boundaries, reset safeguards, and deterministic evidence behavior.
- B_BEHAVIOR: Records project-scoped Quick Deploy, canonical-LF selected-source validation, and single-build/single-bootstrap optimizations.
- FINAL_BEHAVIOR: Preserve both histories. Duplicate ADR identifiers are resolved in the semantic integration commit and a dedicated integration ADR records the final precedence and mode boundaries.
- WHY: Both tracks contain real accepted decisions; deleting either would make the candidate's provenance and safety boundaries unauditable.

## Receipt 5

- FILE: `docs/STATUS.md`
- C_BEHAVIOR: Preserves A Showcase PASS history, exact release facts, 45/45 browser evidence, 2/2 starts, and the local cleanup baseline.
- B_BEHAVIOR: Preserves Enterprise Quick Deploy implementation and its honest partial/full-gate history, including interrupted Backend evidence and Fresh tests.
- FINAL_BEHAVIOR: Keep A and B histories as separately titled sections; add a new Integration Candidate section only from this branch's independently observed gates.
- WHY: Historical track evidence cannot substitute for integration evidence, but it must not be rewritten or lost.

## Receipt 6

- FILE: `scripts/stop.ps1`
- C_BEHAVIOR: Runs an unscoped `docker compose down --remove-orphans` using implicit directory/project state.
- B_BEHAVIOR: Resolves and validates the selected EnvFile, derives its explicit Compose project name, and stops only that project with PASS/FAIL output.
- FINAL_BEHAVIOR: Use B's EnvFile- and ProjectName-scoped stop implementation; Showcase supplies its own explicit project identity.
- WHY: An unscoped stop can affect another ChatBI deployment. Project-scoped shutdown is required for Default, Showcase, Enterprise, and integration isolation.
