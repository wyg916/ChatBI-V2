# ChatBI V2 v1.4.0 Release Candidate Manifest

> Manifest state: **PRE-PUBLICATION CANDIDATE — NOT RELEASED**
>
> The filename is retained for compatibility with existing documentation links. This tracked file is a candidate manifest and publication checklist, not a Final Release attestation.
>
> A commit cannot contain a truthful record of its own final merged SHA, future annotated-tag object, GitHub Release URL or publication timestamp. Those identities must be recorded after publication in an immutable external attestation, such as the GitHub Release body and GitHub's PR, Actions, tag and Release records. This file must never be backfilled with invented `PASS` values or remote identities.

## 1. Candidate identity and publication intent

| Field | Value |
|---|---|
| Product | ChatBI V2 / ChatBI Core |
| Proposed version | `v1.4.0` |
| Release type | Stable source release candidate |
| Target repository | `wyg916/ChatBI-V2` |
| Target repository URL | `https://github.com/wyg916/ChatBI-V2` |
| Visibility | Public |
| License | Apache License 2.0 |
| Preparation branch | `chore/open-source-release` |
| Target/default branch | `main` |
| Publication strategy | Preparation branch → pull request → three GitHub Actions gates → merge → immutable annotated tag → GitHub Release |
| Current immutable base release | `chatbi-v2-v1.3.1` |
| Base release peeled commit | `dddca12d3f4a337c51a12ce5cd9a880239b8429d` |
| Release approval ID | Generated outside the repository from the frozen candidate; not yet attested |
| Pull request number/URL | Post-publication external attestation required |
| Final merged `main` SHA | Post-publication external attestation required; cannot be self-recorded here |
| Proposed annotated tag | `v1.4.0` |
| Annotated tag object SHA | Post-publication external attestation required |
| Tag peeled commit | Post-publication external attestation required and must equal final remote `main` SHA |
| GitHub Release ID/URL | Post-publication external attestation required |
| Publication timestamp | Post-publication external attestation required |

No existing tag may be moved or reused. After publication, the external attestation must prove that the new tag's peeled commit exactly equals the validated final remote `main` SHA.

## 2. Candidate source provenance

The functional successor starts with these five commits after the immutable v1.3.1 base:

| Commit | Subject | Release scope |
|---|---|---|
| `852d8aa35a6ec0a31bed34ba695ec6a17034b457` | `fix(startup): preserve WinPS bootstrap arguments` | Windows one-click/bootstrap reliability |
| `e64387fdbec4459beaafd71153b6363af472c47d` | `feat(showcase): close ChatBI experience and controls` | ChatBI experience and management controls |
| `35bf0d666bb1482ecd78c3f1617d442a18e084fc` | `fix(stream): align live gateway contract` | Streaming contract and answer presentation |
| `7b8d3babccac2aebe489f849ae43a1a6d66daaef` | `fix(governance): close managed datasource and answer lifecycle` | Excel/CSV datasource and answer lifecycle governance |
| `1833ddeb827283d5cd1f8e94b3770dfbde5e3936` | `fix(runtime): harden live provider execution` | Model Gateway runtime hardening |

The final release may include additional reviewed open-source packaging commits from `chore/open-source-release`. Their exact list and final diff are `PENDING` until the approved PR is frozen.

## 3. Included release scope

- Windows PowerShell startup/bootstrap argument preservation.
- Targeted ChatBI-first UX and management-control closure.
- Authenticated live stream contract alignment and guarded final presentation.
- Backend-managed Excel/CSV datasource import and lifecycle behavior.
- Answer/resource governance and retained SQL-workspace history.
- Model Gateway provider runtime hardening and verified-source fallback.
- Migration head `20260829_0015` and V3 backup-manifest compatibility controls.
- Open-source documentation, governance, supply-chain and CI preparation accepted by the final PR.

## 4. Explicitly excluded claims

This source release must not be presented as:

- production-deployment certification;
- proof that external model providers are unlimited, free or permanently available;
- equivalent PostgreSQL/MySQL implementation depth without exact evidence;
- Kubernetes, Helm, HA PostgreSQL, multi-node DR, production SLA/monitoring, Terraform, new Enterprise SSO or signed production OCI delivery;
- certification inherited from historical v1.3.1 or v1.3.0 test totals.

## 5. Required GitHub gates and external attestation

The PR into `main` must complete all of the following at the exact candidate revision:

| Workflow | Run URL | Commit/merge SHA | Candidate state |
|---|---|---|---|
| V1.3 Phase3 and IBM Official Self-Contained Release Gate | External attestation required | External attestation required | Not attested in this candidate file |
| V1.3 Phase4 Product Experience and Governance Gate | External attestation required | External attestation required | Not attested in this candidate file |
| V1.3 Phase5 Release Hardening Gate | External attestation required | External attestation required | Not attested in this candidate file |

`main` must not be described as CI-green until GitHub Actions records successful exact-candidate runs. Their immutable URLs and SHA bindings belong in the post-publication external attestation, not as prefilled claims in this tracked checklist.

Pull-request status alone is insufficient for jobs whose workflow condition is `push` or `workflow_dispatch`. After merge, the exact final `main` SHA must complete the full `main` push gates, including the IBM official self-contained evaluation jobs, before `v1.4.0` is tagged.

## 6. Exact-candidate validation requirements

Historical evidence may inform the plan but cannot satisfy these requirements. Results must be produced against the frozen candidate and preserved outside the self-referential tracked commit. No unchecked row below is a PASS.

| Validation | Required command/evidence | Candidate checklist |
|---|---|---|
| Git working tree and diff integrity | `git status`; `git diff --check`; release file inventory | [ ] External exact-candidate evidence required |
| Tracked-file and current-tree secret scan | Sanitized scan report | [ ] External exact-candidate evidence required |
| Full Git-history secret scan | Sanitized history report | [ ] External exact-candidate evidence required |
| Dependency and license review | Backend/frontend audit plus third-party notice review | [ ] External exact-candidate evidence required |
| Backend unit/integration suite | Exact command, totals and log | [ ] External exact-candidate evidence required |
| PostgreSQL spreadsheet concurrency/integration | Exact command, totals and log | [ ] External exact-candidate evidence required |
| Frontend tests | Exact command, totals and log | [ ] External exact-candidate evidence required |
| TypeScript typecheck | Exact command and diagnostics count | [ ] External exact-candidate evidence required |
| Frontend production build | Exact command and module/build result | [ ] External exact-candidate evidence required |
| E2E/browser primary flow | Exact candidate screenshots/log | [ ] External exact-candidate evidence required |
| Golden Set/Result Oracle regression | Exact dataset/signature and result | [ ] External exact-candidate evidence required |
| Migration empty DB to `0015` | Migration evidence | [ ] External exact-candidate evidence required |
| Migration `0013 → 0014 → 0015` | Migration evidence | [ ] External exact-candidate evidence required |
| Controlled downgrade guards | `0015 → 0014` and `0014 → 0013` evidence | [ ] External exact-candidate evidence required |
| Docker Compose stopped-state start #1 | Exact candidate evidence | [ ] External exact-candidate evidence required |
| Docker Compose stopped-state start #2 | Exact candidate evidence | [ ] External exact-candidate evidence required |
| Backend/RAG/Frontend/Sandbox health | Endpoint and container evidence | [ ] External exact-candidate evidence required |
| README clean-start reproduction | Independent clean-path evidence | [ ] External exact-candidate evidence required |
| Public screenshot privacy review | Final published asset list | [ ] External exact-candidate evidence required |

## 7. Artifact integrity

| Artifact | Path/URL | SHA-256 or immutable identity | Status |
|---|---|---|---|
| Source archive | GitHub-generated after publication | External checksum required | Not attested in this candidate file |
| CycloneDX SBOM | `docs/sbom/V1_4_0.cdx.json` | External final-candidate checksum required | Candidate artifact present; not a release attestation |
| SPDX SBOM | `docs/sbom/V1_4_0.spdx.json` | External final-candidate checksum required | Candidate artifact present; not a release attestation |
| Container/image revision evidence | External attestation required | External immutable identity required | Not attested in this candidate file |
| Release notes | `docs/releases/V1_4_0_RELEASE_NOTES.md` | External final-candidate checksum required | Candidate document |
| Rollback plan | `docs/releases/V1_4_0_ROLLBACK.md` | External final-candidate checksum required | Candidate document |
| GitHub Release assets | GitHub Release after publication | External immutable identity required | Not attested in this candidate file |

Private audit reports, raw secret findings, credentials, local database content, private logs and unsanitized screenshots must never be included in the public release.

## 8. Database and rollback identity

| Field | Value |
|---|---|
| Proposed migration head | `20260829_0015` |
| Direct downgrade target | `20260829_0014` |
| Pre-upgrade published schema head | `20260828_0013` |
| New backup contract | `chatbi-enterprise-backup-v3` |
| Verified pre-upgrade backup | External exact-candidate evidence required |
| Backup manifest/checksums | External exact-candidate evidence required |
| Rollback evidence | External exact-candidate evidence required |

Rollback must follow [V1.4.0 Rollback](V1_4_0_ROLLBACK.md). It must not move tags, force-push, destroy volumes or bypass migration fail-closed guards.

## 9. Publication checklist

- [ ] Release approval ID is current and exactly approved.
- [ ] Frozen candidate HEAD and working tree match the externally approved Release ID.
- [ ] No unresolved Critical/High security, secret, privacy or license blocker remains.
- [ ] Public documentation and screenshots are sanitized and reproducible.
- [ ] All exact-candidate local validation rows above are complete.
- [ ] All three GitHub Actions gates are green for the PR candidate.
- [ ] The PR is reviewed and merged into `main` without rewriting history.
- [ ] Final remote `main` SHA is re-read and recorded in the external attestation.
- [ ] Annotated tag `v1.4.0` is created at that exact SHA and verified.
- [ ] GitHub Release, artifacts, checksums and timestamp are recorded in the external attestation.
- [ ] Repository Description, Topics, License and security settings are verified.

## 10. Post-publication external attestation contract

After the approved PR is merged and the release is published, the external attestation must bind all of the following without modifying or moving an existing tag:

- approved Release ID and frozen candidate SHA;
- PR number/URL and the exact SHA/result URL for each required GitHub Actions gate;
- final remote `main` SHA;
- annotated tag name, tag object SHA and peeled commit;
- GitHub Release ID/URL and publication timestamp;
- source archive, SBOM and published-asset checksums or immutable identities.

The tag peeled commit must equal the final remote `main` SHA, and the GitHub Release must target that tag. A verifier must be able to reconstruct those relationships from GitHub's immutable records and the external attestation alone; this candidate checklist never certifies itself.

Until every mandatory item is externally verified, publication decision remains: **CANDIDATE / NOT RELEASED**.
