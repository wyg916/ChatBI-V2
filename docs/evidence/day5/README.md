# Day 5 Final Release Evidence

This directory contains sanitized, reproducible release-gate summaries. It contains no API key, password, token, database dump, or private local path.

- `cold-start.json`: isolated metadata cold start, bootstrap, Ask and Golden50.
- `provider-live-smoke.json`: Kimi, MiMo and DeepSeek Discovery/Auth/Chat/SQLPlan/Guard status without credentials.
- `migration-results.json`: isolated PostgreSQL upgrade/base/upgrade and single-head validation.
- `one-click-runs.json`: two starts from fully stopped state.
- `parallel-e2e-final.json`: two 5-worker Playwright rounds with retries disabled.
- `rollback-simulation.json`: safe Day4-to-final rollback and restore using temporary source/schema.
- `final-regression.json`: final Backend, Frontend, Golden, E2E, security, migration and UI summary.
- `rag-golden-120.json`: 120 live signed RAG queries plus workspace authorization rejection checks.
- `complex-e2e-10.json`: ten verified complex-analysis traces with SQL, signatures, citations and latency.
- `cold-start-rag-agent-run1.json` / `cold-start-rag-agent-run2.json`: two full stopped-state starts at migration `0008`.
- `rollback-rag-agent-simulation.json`: Day4 migration rollback and final RAG/Agent schema restoration.
- `rag-agent-license-gate.json`: independent implementation, source-copy, submodule and tracked-secret audit.
- `rag-multiagent-final-acceptance.json`: compact final gate summary.

Raw command output is intentionally not committed when it can contain machine-specific details. The compact JSON records are the public evidence index; tests and scripts remain runnable from the repository.
