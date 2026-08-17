# Day 5 Final Release Evidence

This directory contains sanitized, reproducible release-gate summaries. It contains no API key, password, token, database dump, or private local path.

- `cold-start.json`: isolated metadata cold start, bootstrap, Ask and Golden50.
- `provider-live-smoke.json`: Kimi, MiMo and DeepSeek Discovery/Auth/Chat/SQLPlan/Guard status without credentials.
- `migration-results.json`: isolated PostgreSQL upgrade/base/upgrade and single-head validation.
- `one-click-runs.json`: two starts from fully stopped state.
- `parallel-e2e-final.json`: two 5-worker Playwright rounds with retries disabled.
- `rollback-simulation.json`: safe Day4-to-final rollback and restore using temporary source/schema.
- `final-regression.json`: final Backend, Frontend, Golden, E2E, security, migration and UI summary.

Raw command output is intentionally not committed when it can contain machine-specific details. The compact JSON records are the public evidence index; tests and scripts remain runnable from the repository.
