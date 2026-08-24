# ChatBI V1.3.0 Phase 5 Release Candidate Manifest

Status: `SUCCESSOR_IDENTITY_PENDING_COMMIT_AND_SAME_SHA_CERTIFICATION`

## Identity

- Version: `1.3.0`
- Phase 4 baseline: `89bdc12936be0555bdad8a85f06932fb7dc476ee`
- Candidate branch: `codex/v1.3.0-release-hardening-full-gate`
- Final candidate SHA: frozen by `scripts/phase5-build-release-rollback-manifests.py`
  after the successor commit exists; the exact value is written to the external
  Evidence manifest to avoid a self-referential Git commit.
- Rollback SHA: `89bdc12936be0555bdad8a85f06932fb7dc476ee`
- Migration head: `20260822_0012`
- Rollback migration target: `20260822_0012` (no downgrade; Phase 5 adds no migration)
- Main changed: `NO`
- Tag created: `NO`
- Phase 6 started: `NO`

## Frozen scope

Phase 1～4 product behavior is frozen. This candidate contains only release tests and Evidence, performance/security/fault hardening, dependency compatibility, release engineering and fixes demonstrated necessary by those gates. It must not redesign Router, Model Gateway, SQL Executor, Result Oracle, RAG, Agent, Conversation, AnswerEnvelope, Renderer or governance.

## Certification gates

Certification requires all Phase 5 task thresholds on one exact SHA: real Data100 and 10M cleanup, 20 authenticated users for at least 15 minutes across six routes, Weird50, Complex5, Multimodal10, provider/database/RAG/Sandbox fault recovery, restricted Docker proxy attacks, cost ledger thresholds, migration/cold starts, SBOM/license/secret/dependency audits, full browser and Phase 1～4 regressions, non-force remote push and same-SHA Phase5/Phase4/Phase3/IBM CI.

Contract validators, synthetic fault envelopes, historical results and pre-commit Evidence cannot certify this manifest. Any missing gate keeps `PHASE_5_GATE=FAIL` and `PHASE_6_ALLOWED=NO`.

## Immutable release identity

After the tracked successor commit is clean, run:

```powershell
python scripts/phase5-build-release-rollback-manifests.py `
  --final-sha (git rev-parse HEAD) `
  --evidence-root <external-evidence-root>\release
```

The generated `release-manifest.json` and `rollback-manifest.json` bind the
full final/rollback SHAs, local immutable image IDs or repository digests,
configuration hash, Compose SHA-256, migration head/target and the exact
precheck, stop, rollback, migration, start, health, verify and cleanup commands.
`SHA256SUMS.txt` authenticates both manifests. Generation fails on a dirty
worktree, a non-full SHA, multiple migration heads or invalid rollback ancestry.

The release configuration hash covers `.env.example`, the test-cost, model
policy/capability/pricing and Provider-health configurations, and
`docker-compose.yml`. It
never includes `.env`, Provider keys, database passwords or authentication
material.

## Evidence

The authoritative Evidence root and its `SHA256SUMS.txt` are external to the repository and are reported at final handoff. Secrets, cookies, database credentials, provider keys and raw private data must never enter the manifest, Git history or Evidence.
