# ChatBI V2 v1.4.0 Release Candidate

> Status: **PENDING — NOT PUBLISHED**
>
> This document describes the proposed `v1.4.0` source release. It is not evidence that the release, tag, GitHub Actions runs, or GitHub Release already exists.

## Release intent

ChatBI V2 v1.4.0 is the proposed successor to the immutable published `chatbi-v2-v1.3.1` release at commit `dddca12d3f4a337c51a12ce5cd9a880239b8429d`. The candidate brings the five post-v1.3.1 commits into a separately validated open-source release line:

| Commit | Change |
|---|---|
| `852d8aa35a6ec0a31bed34ba695ec6a17034b457` | Preserve Windows PowerShell bootstrap arguments and harden one-click startup behavior. |
| `e64387fdbec4459beaafd71153b6363af472c47d` | Close identified ChatBI user-experience and management-control gaps. |
| `35bf0d666bb1482ecd78c3f1617d442a18e084fc` | Align the live streaming gateway and answer-stream contract. |
| `7b8d3babccac2aebe489f849ae43a1a6d66daaef` | Close managed Excel/CSV datasource and answer-lifecycle governance. |
| `1833ddeb827283d5cd1f8e94b3770dfbde5e3936` | Harden live Model Gateway provider execution and verified fallback behavior. |

The final release commit may also contain the reviewed open-source packaging changes made on `chore/open-source-release`. Its exact SHA is `PENDING` until the pull request is merged.

## Proposed highlights

### Startup and deployment reliability

- Preserve bootstrap arguments when the Windows PowerShell 5.1 entry point delegates to the project scripts.
- Keep the project-scoped Doctor, bootstrap, migration, start, verify, stop, backup and restore boundaries.
- Continue using project-owned local PostgreSQL as the metadata database; the frontend accesses data only through the Backend API.

### ChatBI experience and administration

- Improve the affected ChatBI-first pages and management controls without introducing a separate general-purpose AI administration product.
- Close user, role, audit, datasource and answer-governance interactions covered by the successor changes.
- Preserve the six primary product modules: Ask Data, Datasources, Semantic Model, Answer Library, Dashboards and Evaluation Center.

### Streaming and answer presentation

- Align authenticated streaming behavior across the supported ChatBI analysis path.
- Keep deterministic query evidence as the source of truth and apply provider-based presentation only after a valid source answer exists.
- Preserve the verified source answer when provider presentation is unavailable or rejected; a presentation failure must not turn a successful analysis into a false failure.

### Managed Excel/CSV datasources

- Add Backend-managed Excel/CSV datasource metadata, parsing and lifecycle operations.
- Keep spreadsheet files and metadata behind Backend authorization and workspace/resource checks.
- Preserve SQL workspace history when a managed datasource is removed by using the nullable datasource relationship introduced by migration `20260829_0015`.

### Model runtime hardening

- Harden live provider request execution, response normalization, streaming integration and guarded fallback behavior.
- Keep MiMo, DeepSeek and Kimi behind the single Model Gateway rather than adding direct provider calls to product features.
- External model availability still depends on valid credentials, vendor policy, network reachability, quotas and billing. This release does not promise unlimited, free or permanently available provider service.

## Database and backup compatibility

- Proposed migration head: `20260829_0015`.
- Migration `20260829_0014` introduces managed spreadsheet datasource metadata.
- Migration `20260829_0015` makes `SQLWorkspaceRun → Datasource` history links nullable with `ON DELETE SET NULL` semantics.
- New successor backups use the `chatbi-enterprise-backup-v3` contract and must be restored with matching source semantics. Backup manifests must never be relabeled to bypass compatibility checks.

See [V1.4.0 Rollback](V1_4_0_ROLLBACK.md) before upgrading a database or creating a deployment rollback plan.

## Required publication path

This candidate must be published only through the following controlled path:

1. Finalize and validate `chore/open-source-release` with a clean working tree.
2. Push that preparation branch and open a pull request into `main`; do not force-push or overwrite `main`.
3. Require all three repository workflow checks to complete successfully for the candidate PR:
   - `V1.3 Phase3 and IBM Official Self-Contained Release Gate`
   - `V1.3 Phase4 Product Experience and Governance Gate`
   - `V1.3 Phase5 Release Hardening Gate`
4. Merge only after the release approval remains valid and every required check is green.
5. Re-verify the final `main` SHA and wait for the exact-SHA `main` push runs, including the push-only IBM official self-contained jobs, to complete successfully.
6. Create a new immutable annotated tag `v1.4.0` at that exact SHA and publish the GitHub Release.

Current publication fields:

| Field | Value |
|---|---|
| Final release commit SHA | `PENDING` |
| Pull request URL | `PENDING` |
| GitHub Actions result | `PENDING` |
| Annotated tag object SHA | `PENDING` |
| Tag peeled commit | `PENDING` |
| GitHub Release URL | `PENDING` |
| Publication timestamp | `PENDING` |

Historical test totals from v1.3.1 or earlier commits do not certify v1.4.0. The tracked [V1.4.0 Release Candidate Manifest](V1_4_0_FINAL_MANIFEST.md) defines the required gates; fresh exact-candidate results and final GitHub identities must be preserved in the private approval package and post-publication external attestation.

## Known boundaries

- This is a source-release candidate for local deployment, Enterprise PoC, private-deployment validation and secondary development. It is not production-deployment certification.
- Kubernetes, Helm, HA PostgreSQL, multi-node disaster recovery, production monitoring/SLA, production key rotation, signed immutable production OCI, Terraform and new Enterprise SSO development remain outside this release.
- PostgreSQL remains the primary development/test metadata database. MySQL datasource compatibility must not be described as equivalent to complete PostgreSQL-path coverage without exact release evidence.
- Local Showcase credentials are development-only and must never become public or Enterprise defaults.
