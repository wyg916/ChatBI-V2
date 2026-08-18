# C test and security matrix

All gates run on the C integration SHA derived from `DAY1_FINAL_SHA`; candidate-branch evidence may inform thresholds but cannot satisfy them.

| Area | Test case | Numerical gate | Security assertion | Evidence |
|---|---|---:|---|---|
| PG catalog | Search schema/table/column and composite PK/FK | expected objects 100% | foreign Workspace objects 0 | `c-catalog-pg.json` |
| MySQL catalog | Same contract under MySQL dialect | expected objects 100% | no credential/browser exposure | `c-catalog-mysql.json` |
| Pagination/lazy load | First/middle/last pages; cancel stale request | duplicates/omissions 0; page size ≤200 | no unbounded response | browser trace |
| 10M browse | Open benchmark table and fetch 50-row page | p95 ≤2000 ms; returned rows ≤100 | full-table response 0 | `c-10m-browser.json` |
| Format | Valid/invalid PG and MySQL SQL | valid 100%; invalid 100% rejected | no execution/history write | backend test |
| Execute | SELECT/CTE, joins, aggregates, empty result | success 100% for corpus; limit ≤500 | Guard before connector | `c-execute.json` |
| Explain | PG/MySQL explain | expected plans 100%; timeout enforced | no ANALYZE/write; redacted errors | backend/E2E |
| Dangerous SQL | DDL/DML/CALL/COPY/file/program/multi-statement/system objects | block rate 1.0; actual writes 0 | audit rejection present 100% | `c-security.json` |
| Timeout/concurrency | Slow and parallel queries | configured timeout; no leak; 429/typed limit | connections/tasks return to baseline | load evidence |
| Masking | phone/email/token/password positives and safe negatives | sensitive leaks 0; false masking documented | policy applies to sample/result/export | backend test |
| History | Workspace+user isolation and pagination | own records 100%; foreign visible 0 | direct-ID IDOR 0 | backend test |
| Replay | Revoke grant or change catalog before replay | stale replay denied 100% | SQL re-guarded 100% | backend test |
| Verified SQL | Save/review/replay through B bridge | Oracle-passed saves 100%; failed saves 0 | `answer.manage` enforced | B+C E2E |
| Browser E2E | Real PG 10M and MySQL paths | 2/2 minimum; console/page/blocking errors 0 | authenticated session only | Playwright report |
| Migration | upgrade → base → upgrade from Day1 head | single head; 1/1 sequence PASS | unrelated tables unchanged | migration evidence |
| Phase 2 regression | Auth/Chat/Memory/Attachment/Open-ended | frozen thresholds unchanged | 401/403 and isolation unchanged | Phase 2 matrix |

## Mandatory malicious corpus

Include at least: `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `CALL`, `DO`, `COPY`, `LOAD DATA`, file functions, external program functions, comments hiding a second statement, semicolon chaining, CTE wrapping DML, system catalog overreach, unauthorized schema/table/column, oversized LIMIT, Unicode/comment obfuscation, and EXPLAIN/format parser differentials.

## Release decision

Any database write, credential exposure, Workspace/user leak, Guard bypass, multiple migration heads, or Phase 2 regression is `BLOCKED`. Performance or UX gaps without a safety violation are `PARTIAL`; they are never rewritten as PASS.
