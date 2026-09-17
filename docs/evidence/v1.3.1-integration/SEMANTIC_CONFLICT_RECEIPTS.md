# V1.3.1 semantic conflict receipts

These receipts cover behavior conflicts that did not necessarily produce Git
conflict markers. They are separate from `CONFLICT_RESOLUTION_RECEIPTS.md`.

## 1. Showcase orchestration versus deployment helpers

- AREA: `scripts/showcase.ps1` and `scripts/deployment/ChatBI.Deployment.ps1`
- C_BEHAVIOR: fixed local Showcase ports, credentials, deterministic Level0 mode, and demo reset.
- B_BEHAVIOR: selected EnvFile, project-scoped Compose lifecycle, reusable deployment modes, and fail-fast configuration.
- FINAL_BEHAVIOR: Showcase explicitly fixes its local-only mode while delegating lifecycle work through B's scoped helpers and selected EnvFile.
- WHY: preserves A/C's one-click experience without allowing Showcase to stop or configure another deployment.

## 2. Environment precedence

- AREA: configuration loading
- C_BEHAVIOR: mode-specific process overrides protect Showcase ports, providers, credentials, and Level0.
- B_BEHAVIOR: `.env`/EnvFile supplies enterprise deployment configuration.
- FINAL_BEHAVIOR: explicit Process or CLI > selected mode EnvFile > default `.env` > safe hardcoded default.
- WHY: the caller's explicit mode must not be silently overwritten by a file.

## 3. Docker image identity

- AREA: canonical Compose and Showcase build/start
- C_BEHAVIOR: build identity and release/Git metadata.
- B_BEHAVIOR: project-scoped Backend and Sandbox images.
- FINAL_BEHAVIOR: `CHATBI_BACKEND_IMAGE`, `CHATBI_FRONTEND_IMAGE`, and one resolved `CHATBI_SANDBOX_IMAGE` flow through Compose, controller, proxy, worker, Showcase, and Enterprise.
- WHY: prevents cross-project tag collisions and controller/worker image drift.

## 4. Migration expectations

- AREA: migration and rollback validation scripts
- C_BEHAVIOR: V1.3.1 adds `20260828_0013` with `20260822_0012` as its parent.
- B_BEHAVIOR: release checks were authored when `20260822_0012` was the candidate head.
- FINAL_BEHAVIOR: candidate head is `20260828_0013`; the V1.3 rollback target remains historical `20260822_0012`.
- WHY: preserves V1.3.0 history while validating the V1.3.1 forward migration.

## 5. Doctor provider state

- AREA: `scripts/doctor.ps1` and deployment-state inspection
- C_BEHAVIOR: provider enabled/health state is persisted and administrator-visible.
- B_BEHAVIOR: Doctor only counted configured provider keys and never made paid calls.
- FINAL_BEHAVIOR: Doctor reports configured, enabled, persisted health, and reachability-configuration state from one sanitized metadata probe; live calls remain zero.
- WHY: a configured key is not the same as an enabled or health-checked provider.

## 6. Backup and restore contract

- AREA: `scripts/backup.ps1`, `scripts/restore.ps1`, and deployment metadata
- C_BEHAVIOR: settings, provider runtime state, invitations, RBAC, and workspace state persist at migration `0013`.
- B_BEHAVIOR: V1 backup/restore used a checksum manifest around the earlier deployment metadata.
- FINAL_BEHAVIOR: V2 manifest binds dump SHA-256, `0013`, candidate version, Git SHA, sanitized counts, and a stable metadata fingerprint; restore verifies the same governed state.
- WHY: SQL restore success alone cannot prove that administrator and authorization state survived.

SEMANTIC_CONFLICT_COUNT=6
UNRESOLVED_SEMANTIC_CONFLICT_COUNT=0
