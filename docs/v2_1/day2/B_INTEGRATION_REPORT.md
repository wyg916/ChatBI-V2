# Day 2 Wave B Integration Report

- Status: PASS
- Tested code SHA: `d3582dc5054da48f1f4b0dff365b8e05224f368a`
- Pre-B SHA: `787b09cacf166f5f468e0e9140361946385ed212`
- Canonical B tip: `5690d9d0ec04be0b21dfd642e0d8802ae1d5142a`
- Canonical B tree: `a805ccfa23db8231bca894bfee8a8856a14de347`
- Canonical commit count: 3
- Merge commit: `d3582dc5054da48f1f4b0dff365b8e05224f368a`
- Executed at: `2026-08-19T01:23:16+08:00`

## Result

IBM-style multiple-ground-truth evaluation, Golden 50, result comparison, eight-dimension error analysis, evaluation dashboard, CI release gate, SQLBot feedback, Verified SQL recall, review, and guarded replay are integrated. The live gate produced 50/50 SQL execution and result-value passes, 38/38 dangerous-SQL blocks, and a 1/1 feedback replay pass.

The integration additionally corrected four defects found only after combining B with Phase 2: authenticated release-gate login, `Principal` propagation into correction/replay QueryPipeline calls, workspace scoping of evaluation records, and cross-platform/container loading of the multiple-ground-truth overlay.

## Commands and counts

- `python -m pytest tests -q`: PASS, 178 collected tests.
- `npm test`: PASS, 11 files / 31 tests.
- `npm run typecheck`: PASS.
- `npm run build`: PASS, 735 transformed modules.
- `npm run e2e -- v21-eval-feedback.spec.ts --workers=1`: PASS, 2/2.
- `npm run e2e -- --workers=1`: PASS, 57/57.
- `run_v21_release_gate.py --require-feedback`: PASS, Golden 50 and feedback replay.
- `phase2_runtime_acceptance.py`: PASS, 60/60 routes, 60/60 trace, 10/10 follow-up, citations/file/image all 1.0.
- `alembic heads; downgrade -1; upgrade head; heads`: PASS, single head `20260818_0009` restored.

## Evidence

- `artifacts/v2_1/day2/b/eval-feedback-release-gate.json`, SHA-256 `1a24c66955d8efcd22ec34530cdffa22777e63509da661d9e2cf6d1d3dab1559`.
- `artifacts/v2_1/day2/b/phase2-runtime-acceptance.json`, SHA-256 `72776307110a038716486fff500c9f5c1543fe4a0d84e256882156ac85bb7b48`.
- `docs/v2_1/day2/IBM_EVAL_EVIDENCE.json`.
- `docs/v2_1/day2/GOLDEN50_RESULT.json`.
- `docs/v2_1/day2/FEEDBACK_LOOP_EVIDENCE.json`.

## Impact and controls

- Frozen Zone intersection: four files; see `B_FROZEN_SEMANTIC_MERGE_REPORT.md`.
- Migration impact: no B migration; existing single head retained and round-trip verified.
- License impact: IBM Text-to-SQL Evaluation Toolkit is used as an audited design/adapter reference; notices were updated without copying branded UI or restricted code.
- Security: authenticated workspace-scoped evaluation and feedback; corrected/replayed SQL re-enters SQLGlot Guard, Query Executor and Result Oracle with the caller principal.
- Failures: two corrected live-gate defects (missing image file/path; CRLF-sensitive hash) and one corrected E2E fixture-selection defect. No unresolved failure.
- Blockers: none.
- Rollback: revert the merge commit `d3582dc5054da48f1f4b0dff365b8e05224f368a`; no database downgrade is required for B.
