# Day 2 Acceptance Evidence

- `golden-results.json`: frozen Golden 20 per-case PostgreSQL results plus MySQL basic 5.
- `security-results.json`: 38 dangerous SQL API cases and real read-only account write attempts.
- `migration-results.json`: local PostgreSQL isolated-schema single-head and upgrade → base → upgrade cycle.
- `seed-idempotence.json`: two consecutive metadata/semantic seed runs with unchanged counts.
- `ask-result-1440x900.png`: real PostgreSQL result page at the approved reference viewport.
- `cold-starts.json`: two consecutive starts from stopped Compose state.
- `test-summary.json`: final Backend, Frontend, E2E, Golden and environment gate summary.

The simulated business data remains in the user's local PostgreSQL/MySQL installations. Docker Compose contains only Backend and Frontend services and no database volume.
