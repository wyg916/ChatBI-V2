# Day 2 gate matrix

All gates are definitions, not current results. Every gate depends on a clean unique `DAY1_FINAL_SHA` and `DAY2_PREAUDIT_REFRESH=PASS`.

| Gate | Input | User entry / formal runtime path | Test cases and numerical threshold | Security case | Evidence file | Failure state / rollback | Depends on Day1 |
|---|---|---|---|---|---|---|---|
| IBM_EVAL | B canonical three-commit chain; Golden 50; multi-ground-truth manifest | Evaluation Center → Backend evaluation API → refreshed QueryPipeline → IBM-compatible adapter → ResultOracle | Golden≥50; SQL execution≥0.98; result value≥0.95; five semantic dimensions≥0.95; PG 50/50 target, MySQL 10/10 target | dangerous SQL block rate=1.0; writes=0; cross-workspace records=0 | `docs/evidence/v2_1/day2/ibm-eval.json` | BLOCKED; revert B merge to `PRE_B_SHA` | YES |
| FEEDBACK_LOOP | B feedback/Verified SQL plus existing QueryFeedback/Answer | Evaluation feedback panel / Answer Library → review → recall → re-guarded replay → Oracle | correct/incorrect/review/replay corpus 100%; supplied replay 3/3; unreviewed candidates retrieved=0 | `answer.manage`/`evaluation.run`; IDOR=0; stored SQL never bypasses Guard | `.../feedback-loop.json` | BLOCKED on poisoning/bypass; revert B | YES |
| SQL_WORKSPACE | Refreshed C candidate; PG/MySQL catalogs; 10M schema | Data source detail → Data Workspace → catalog/sample or guarded SQL → history/Verified SQL | PG+MySQL E2E≥2; 10M 50-row sample p95≤2s; dangerous block=1.0; actual writes=0; history/replay/verify corpus=100% | session/RBAC/Workspace/user isolation; masking leaks=0; timeout/limit | `.../sql-workspace.json` | BLOCKED on safety; otherwise PARTIAL; revert C and C migration | YES |
| RAG_PRODUCT | Approved professional knowledge; current Golden 120; D ranking/citation UI delta | Ask → KNOWLEDGE/HYBRID → signed bridge → ACL → rank/rerank → Citation/Answer Guard → citation UI | cases≥120; Recall@10≥0.95; Citation Accuracy≥0.95; verified citations rendered 100% | unauthorized retrieval=0; injection leaks=0; no-evidence fabricated claims=0 | `.../rag-product.json` | BLOCKED; revert D; incident off is not releaseable | YES |
| AGENT_PRODUCT | Fixed roles/tools and 10 complex questions | Ask → COMPLEX_ANALYSIS → five-role bounded runtime → six tools → verification → SSE stages | real E2E≥10/10; trace=100%; steps≤8; tools≤12; replans≤2; depth≤2; latency≤30s | DB/Guard/Oracle/RBAC/unknown-tool bypass counters all 0 | `.../agent-product.json` | BLOCKED; revert D | YES |
| FILE_PRODUCT | Phase 2 attachments; file Golden 10; sandbox policy | Chat composer → FILE_QUERY → ownership check → parser → disposable sandbox → verified result/chart/artifact | 11 upload types remain accepted; structured compute Golden≥10/10; network/secret/escape successes=0; cleanup leaks=0 | user/Workspace/conversation/artifact isolation; CPU≤1, RAM≤512MiB, time≤30s, output≤10MiB | `.../file-product.json` | BLOCKED on sandbox/isolation; revert D/job-artifact migration | YES |
| GOLDEN_50 | Frozen Day4 Golden plus refreshed data signature | Evaluation Center / release runner → full Day2 integrated runtime | PG 50/50 target; MySQL 10/10; SQL execution≥0.98; result≥0.95; original Golden20 regression 20/20 | dangerous SQL 38/38; writes=0 | `.../golden-50-final.json` | BLOCKED; identify/revert latest failing wave | YES |

## Global release rules

- Evidence must identify one integration commit SHA and tree SHA. Results from B/C/D source branches cannot be stitched into a final PASS.
- Every wave runs targeted tests and Phase 2 no-regression before its integration commit is accepted.
- Final gate also requires Backend full, Frontend typecheck/test/build, single migration head upgrade-base-upgrade, full serial E2E, license/secret checks and two starts from stopped state.
- Any hard security, correctness, isolation or migration failure is `BLOCKED`. Incomplete evidence is `PARTIAL`, never PASS.
