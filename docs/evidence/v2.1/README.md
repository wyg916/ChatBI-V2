# V2.1 Evaluation / Golden / Feedback Evidence

- `eval-golden-release-gate.json`: isolated PostgreSQL metadata schema run; Golden 50, eight Result Oracle dimensions and dangerous SQL gate.
- `eval-feedback-release-gate.json`: final gate after SQLBot feedback replay; includes `FEEDBACK_REPLAY_RATE=1.0`.
- `golden-50-postgres-mysql.json`: original Day 4 compatibility runner against the isolated Backend, PostgreSQL 50/50 and MySQL 10/10.
- `test-summary.json`: commands, test counts, independent ports/schema and final acceptance summary.

All evidence was produced through Backend API calls on port `18080`, with metadata in PostgreSQL schema `chatbi_eval_feedback_v21_0818`. PostgreSQL/MySQL business schemas were queried through existing read-only datasource accounts. No Docker service, main metadata schema, main worktree or main task port was changed.
