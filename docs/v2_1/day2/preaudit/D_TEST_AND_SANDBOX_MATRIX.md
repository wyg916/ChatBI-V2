# D test and sandbox matrix

| Gate | Test cases | Numerical threshold | Failure status | Evidence |
|---|---|---:|---|---|
| RAG Golden | 120 approved knowledge/hybrid cases | Recall@10 ≥0.95; Citation Accuracy ≥0.95 | BLOCKED below threshold | `d-rag-golden-120.json` |
| RAG ACL | cross Workspace/user/role/scenario/source-version | unauthorized retrieval/citation 0 | BLOCKED on any leak | `d-rag-acl.json` |
| Prompt injection | document/query/system-prompt/exfiltration variants | published injected chunks 0; secret/prompt leaks 0 | BLOCKED | `d-rag-injection.json` |
| Citation UI | document/version/chunk/locator; no-evidence path | verified citations rendered 100%; fabricated 0 | BLOCKED | Playwright trace/screenshots |
| Agent real E2E | 10 complex questions | 10/10; trace 100%; verified result/citation 100% | BLOCKED | `d-agent-e2e.json` |
| Agent budgets | loop/replan/depth/tool/timeout attacks | steps≤8, tools≤12, replan≤2, depth≤2, time≤30s | BLOCKED | trace export |
| Agent security | direct DB, unknown tool, Guard/Oracle/RBAC bypass | all counters 0 | BLOCKED | security report |
| Structured formats | CSV/XLS/XLSX/Parquet | 4/4 parse/analyze; wrong signatures rejected 100% | PARTIAL/BLOCKED if unsafe | file Golden |
| Multiple sheets | select two sheets and invalid sheet | valid 2/2; invalid rejected 100% | PARTIAL | file Golden |
| Statistics/join | describe/group/aggregate/two-file join/nulls | expected result accuracy 1.0 on 10-case set | PARTIAL | `d-file-golden-10.json` |
| Chart/artifact | chart + CSV/JSON artifact | hashes/provenance 100%; invalid MIME 0 | BLOCKED on leak | artifact manifest |
| CPU limit | infinite/busy computation | killed within 30s; Backend remains healthy | BLOCKED | sandbox trace |
| RAM limit | allocation bomb | job killed ≤512 MiB; host unaffected | BLOCKED | container metrics |
| Output/row limit | huge stdout/result/artifact | output≤10 MiB; rows≤100k | BLOCKED | job record |
| Network isolation | DNS/HTTP/socket attempts | successful egress 0 | BLOCKED | network probe |
| Host isolation | `/`, home, env, Docker socket, process spawn | accessible secrets/host files 0 | BLOCKED | escape corpus |
| DB credential isolation | env/file/socket probes | DB/RAG/model credential matches 0 | BLOCKED | secret probe |
| Workspace isolation | cross Workspace/user/conversation job/artifact IDs | leaks 0; foreign access denied 100% | BLOCKED | API/E2E |
| Cleanup | success/fail/timeout/cancel | running containers/tasks/temp dirs return to 0 | BLOCKED on leak | cleanup metrics |
| Phase 2 files | 11 upload types and image/document queries | Phase 2 accuracy remains 1.0; unsupported hallucination 0 | BLOCKED | Phase 2 regression |
| SSE/Auth/Memory | cancel/retry/refresh/follow-up/401/403 | frozen thresholds unchanged | BLOCKED | no-regression matrix |

## Sandbox acceptance probes

The security corpus must include path traversal, archive bomb, malformed Office zip, formula injection, pickle/object deserialization, `__import__`, `eval/exec`, subprocess/shell, socket/DNS/HTTP, `/proc` and environment reads, symlink/hardlink escape, excessive threads/processes, infinite loops, memory bombs, huge output, artifact content-type confusion and cross-job storage keys.

Tests run from a clean integration SHA. Unit mocks may test error mapping, but release evidence must include a real disposable sandbox container with network disabled and resource metrics.
