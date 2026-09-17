# V1.3.0 SQLBot License and Runtime Requirement Exception

Status: `ACCEPTED_FOR_V1_3_0`

Locked upstream commit: `2a86aa926c4a22400a4ab4506c3ec384f7855a9d`

Direct upstream reuse: `BLOCKED_BY_UPSTREAM_LICENSE`

## Original requirement

The governing Runtime Architecture document proposed selective SQLBot reuse for business glossary, feedback, correction, review, Verified SQL recall/replay and regression, with `SQLBOT_DIRECT_RUNTIME_CALLS > 0` as its upstream Gate.

## Audited conflict

The locked repository uses modified GPLv3 terms with additional non-removable frontend logo/copyright conditions. The pinned tree contains only the root SQLBot `LICENSE` plus a bundled TinyMCE GPL-2.0-or-later notice; no backend or selected-capability subdirectory license relaxes the root terms. Eight representative source headers provide no path-specific SPDX, copyright or license override.

Its backend declares `sqlbot-xpack>=0.0.5.35,<0.0.6.0` as a required base dependency and imports XPack before FastAPI application construction. The pinned tree contains 17 XPack-named entries (15 blobs), but no public XPack backend source tree. The XPack workflow checks out a separate repository using a GitHub token; its unauthenticated repository API returns 404. TestPyPI exposes five platform wheels and no sdist, license value, license expression, classifiers, project URLs or packaged license file.

A separate process or container does not close these facts: it would still load the unclosed XPack dependency before serving a request. It also cannot convert an unpinned image into a reproducible fixed-commit runtime artifact.

## Paths evaluated

1. Selected source incorporation: rejected because the root modified-GPLv3/additional-branding terms apply without a path-specific grant, compatibility with ChatBI's Apache distribution boundary is unresolved, and repository policy authorizes SQLBot only as design reference.
2. Official source build/start: rejected because the mandatory startup closure reaches XPack before serving requests.
3. Independent official service: rejected because process isolation does not supply missing XPack terms or achieve `XPACK_LOADED=0`.
4. Official image/Compose: rejected because image/source binding and the loaded-file license inventory are not reproducible: the latest release predates the pinned commit and has no assets, Compose has no tag/digest, four Dockerfile bases use `:latest`, and the base build executes a remote XPack-license validator.
5. Clean-room compensation: retained, but explicitly not counted as SQLBot upstream reuse.

No SQLBot source, UI, prompt, logo, XPack binary, service or container is copied, installed, imported or executed by this decision.

## Accepted V1.3.0 requirement delta

```text
DIRECT_SOURCE_REUSE_SAFE=NO
INDEPENDENT_SERVICE_SAFE=NO
OFFICIAL_RUNTIME_REPRODUCIBLE=NO
XPACK_LICENSE_CLOSED=NO
SQLBOT_DIRECT_UPSTREAM_REUSE=BLOCKED_BY_UPSTREAM_LICENSE
SQLBOT_RUNTIME_CALLS=0
SQLBOT_XPACK_LOADED=0
SQLBOT_LICENSE_EXCEPTION=ACCEPTED_FOR_V1_3_0
REAL_UPSTREAM_REUSE_COUNT=3
CHATBI_CLEAN_ROOM_FEEDBACK=PASS
CHATBI_VERIFIED_SQL_REPLAY=PASS
```

## Clean-room compensating controls

ChatBI's project-owned feedback path keeps the user-visible product capability without claiming upstream reuse:

- feedback and corrections bind to ChatBI users, workspaces and query runs;
- approval records SQL SHA-256, datasource, semantic model/version and result-signature attestation;
- replay rechecks resource binding and routes through the project-owned QueryPipeline;
- SQL still passes SQLGlot Guard, read-only Executor and Result Oracle;
- cross-workspace replay remains forbidden;
- the implementation origin and official runtime call count remain explicit.

## User-visible statement boundary

Allowed statement: "V1.3.0 retains ChatBI-owned verified-SQL feedback/replay; direct SQLBot runtime integration is not included because upstream license and XPack artifact closure are incomplete."

Forbidden statements include `SQLBot upstream reuse=PASS`, `SQLBot integrated`, `4/4 upstream reuse`, or any implication that the clean-room path executes SQLBot code.

## Residual risk and re-review trigger

The product lacks direct upstream SQLBot runtime reuse and may not inherit upstream fixes or behavior. Direct incorporation could introduce GPLv3 copyleft plus additional conditions into the Apache-distributed combined work; compatibility and redistribution consequences remain unresolved. Re-evaluate on an upstream commit/version or license/header change, public XPack source/license publication, an immutable commit-bound runtime with a complete loaded-file inventory, publisher authorization, legal review, or a newly proposed SQLBot source/runtime/brand path.

This engineering compliance decision is not legal advice. It expires after V1.3.0 unless explicitly renewed.
