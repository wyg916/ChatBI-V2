# V1.3.0 Runtime Architecture Requirement Delta

Status: `APPROVED_FOR_V1_3_0_PHASE2`

Scope: Phase 2 data/semantic/evaluation upstream closure only

Product baseline: `a7e9b207948660f7063e2539596b404edb059de3`

Target branch: `codex/v1.3.0-data-semantic-upstream`

## 1. Governing document and version mapping

The implementation, capability, Phase 0-6, testing, security, performance, license, Evidence, Git and release principles in `ChatBI_V2_V1.2.0_Runtime_Architecture_优化落地方案_v1.0` continue as controlled V1.3.0 requirements.

The following are historical identity fields and are not executable V1.3.0 instructions:

- the V1.2.0 version, branch and tag names;
- the `5303bdb...` starting baseline;
- `release/v1.2.0-rc1`;
- any instruction to modify or recreate V1.2.0 release state.

Current identity is V1.3.0 Phase 2 on `codex/v1.3.0-data-semantic-upstream`. `main`, existing tags and the V1.2.0 release remain outside this closure.

## 2. Requirements carried forward without change

- ChatBI remains the only Question Router, Model Gateway, SQL execution gateway, Trace owner and browser SSE owner.
- Data questions remain `Schema/Semantic context -> NL2SQL -> SQLGlot Guard -> EXPLAIN Cost Guard -> read-only Executor -> Result Oracle -> critical Verification Query`.
- Provider keys remain behind Model Gateway and are never provided to upstream components, browsers, tests or Evidence.
- Every direct upstream integration requires an exact revision, path-level license/import closure, runtime calls, A/B evidence, user entry, fallback and rollback.
- IBM remains an offline CI/Batch evaluator and does not enter the online request path or receive database credentials.
- Unknown or restricted upstream license paths fail closed. A clean-room capability is never counted as direct upstream reuse.
- Release evidence must come from one committed closure SHA, a clean worktree and non-force remote delivery.

## 3. Phase 2 realized upstream baseline

| Project | V1.3.0 Phase 2 mode | Runtime evidence | Decision |
| --- | --- | ---: | --- |
| OpenChatBI | exact selected MIT source behind ChatBI bridge | 588 calls | PASS |
| WrenAI | exact selected Apache-2.0 source behind ChatBI bridge | 140 calls | PASS |
| IBM Text-to-SQL Toolkit | external fixed checkout, 11 Apache-2.0 selected files | 50 comparisons + 1 error analysis | local PASS; remote CI required |
| SQLBot | no source/service/XPack integration; ChatBI clean-room feedback retained | 0 official calls | blocked by upstream license/runtime closure |

`REAL_UPSTREAM_REUSE_COUNT=3`. This number must not be raised by counting SuperSonic, Chat2DB, SQLBot or other clean-room/reference-only paths.

## 4. IBM self-contained GitHub Runner delta

The former workflow's external `api_base` and long-lived repository-secret dependency are replaced by a self-contained GitHub-hosted Runner gate:

```text
ephemeral PostgreSQL service
-> repository migration and fixed demo seed
-> isolated CI workspace/user/datasource/semantic model
-> short-lived Runner-generated authentication material
-> localhost ChatBI Backend
-> pinned IBM checkout and selected-source hash verification
-> Golden 50 / multiple ground truth / execution compare / error analysis
-> artifact upload and non-zero release blocking
```

Mandatory boundaries:

- no production database, data, user, Provider key or production secret;
- fixed, reproducible seed data only;
- localhost API only, with no public tunnel or long-lived public runner;
- package/wheel/sdist remain blocked by the IBM Apache-2.0/MIT metadata conflict;
- the official toolkit receives already executed rows/columns, SQL and frozen ground truth, never a database connection;
- the remote run SHA must equal the committed Phase 2 closure SHA.

## 5. SQLBot requirement delta

The governing document's Phase 2 target `SQLBOT_DIRECT_RUNTIME_CALLS > 0` cannot be satisfied safely at the locked upstream revision. V1.3.0 therefore approves the exception defined in [`../opensource/V1_3_SQLBOT_LICENSE_EXCEPTION.md`](../opensource/V1_3_SQLBOT_LICENSE_EXCEPTION.md).

For V1.3.0 Phase 2 only, the accepted Gate is:

```text
SQLBOT_DIRECT_UPSTREAM_REUSE=BLOCKED_BY_UPSTREAM_LICENSE
SQLBOT_RUNTIME_CALLS=0
SQLBOT_XPACK_LOADED=0
CHATBI_CLEAN_ROOM_FEEDBACK=PASS
CHATBI_VERIFIED_SQL_REPLAY=PASS
SQLBOT_LICENSE_EXCEPTION=ACCEPTED_FOR_V1_3_0
```

This is a documented requirement delta, not a statement that SQLBot upstream reuse passed. It does not relax SQL Guard, read-only execution, Oracle, Workspace isolation or feedback attestation.

## 6. Approval and lifecycle

- Project-owner approval: `YES`, recorded by the explicit Phase 2 document-compliant closure instruction dated 2026-08-21.
- Engineering compliance approval: conditional on the locked evidence and zero SQLBot/XPack loading.
- Legal characterization: none; this is not legal advice.
- Expiry: the exception applies only to V1.3.0. A later version must carry it forward explicitly or re-open the original Gate.

Re-review is mandatory if SQLBot publishes authoritative XPack source/license terms, a reproducible fixed-commit artifact with an auditable loaded-file inventory, removes or clarifies branding/redistribution conditions, or if ChatBI changes its repository license/distribution mode.

## 7. Phase 2 completion rule

This delta is necessary but not sufficient for `PHASE_2_GATE=PASS`. PASS additionally requires:

- committed closure documents and self-contained CI wiring;
- Phase 1/2 regressions and three live Provider smoke on the closure SHA;
- non-force remote delivery and Local/Tracking/`ls-remote` equality with `0/0`;
- a successful IBM remote run on the same closure SHA with 50 official comparisons and at least one official error-analysis execution;
- a clean final worktree, no main change and no tag creation.
