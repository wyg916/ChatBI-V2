# Day 2 Phase 2 no-regression matrix

The Phase 2 protected result is a baseline, not evidence for a later SHA. These gates must be rerun after B, after C, after D and on `DAY2_FINAL_SHA`.

| Capability | Frozen baseline | Required regression | Threshold | Likely conflict sources | Evidence / rollback |
|---|---|---|---|---|---|
| OPEN_ENDED_CHAT | 60/60; runtime and trace 60/60 | Phase 2 60 manifest through unified Chat/SSE | 60/60; fixed-answer paths 0; unsupported hallucination 0 | Day1 semantic/SSE, D chat | `phase2-open-ended-<wave>.json`; revert current wave |
| CHAT_UI | fixed message scroll/composer/result order | 1366×768, 1440×900, 1920×1080; stop/retry/scroll | console/page/blocking errors 0; core clipping 0 | C router, D citation/file UI | Playwright trace/screenshots |
| ENTER_AND_IME | Enter, Shift+Enter, Chinese IME | composer keyboard/composition E2E | sends exactly once; composition premature send 0 | AskExperience/chat API changes | Playwright trace |
| FILE_DOCUMENT_IMAGE | 11 formats; file/image accuracy 1.0 | CSV/XLS/XLSX/Parquet/PDF/DOCX/TXT/MD/PNG/JPG/WEBP upload/query/delete | 11/11; unsupported type rejected; host path leaks 0 | D parser/sandbox | `phase2-file-<wave>.json` |
| MULTIMODAL | real image query accuracy 1.0 | image upload → Vision response → follow-up | accuracy 1.0; fake answer 0 | D FILE route/router | E2E + trace |
| AUTH_SESSION | anonymous/invalid 401; cross Workspace 403; bypass 0 | login/me/logout/expiry/revoke, protected APIs, dynamic E2E auth | expected 401/403 100%; bypass 0 | B Playwright/routes, C/D APIs | `phase2-auth-<wave>.json` |
| SHORT_TERM_MEMORY | follow-up context 10/10 | refresh recovery, 10 follow-ups, user/workspace isolation | inheritance 10/10; cross-session leakage 0 | Day1/D chat service | backend/E2E evidence |
| ATTACHMENT_ISOLATION | user/Workspace/conversation scoped | direct IDs, active list, delete, sandbox job/artifact propagation | cross-scope leak 0; foreign denial 100% | D attachments/jobs/artifacts | `phase2-attachment-<wave>.json` |

## Minimum per-wave command set

- Backend Phase 2 auth/chat/attachment, security, open-ended manifest and migration tests.
- Frontend typecheck, build, Ask/Login/route tests.
- Authenticated Playwright Phase 2 chat/multimodal spec.
- When Query core changes: QueryPipeline, SQL Guard, Executor, ResultOracle and router coverage.
- When D changes: RAG Golden 120, complex E2E 10, file Golden/sandbox and citation UI.

The exact commands must be refreshed from the test tree at `DAY1_FINAL_SHA`; filenames in the old integration conflict policy are a minimum, not a substitute for newly added Day1 tests.
