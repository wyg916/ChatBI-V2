# Day 1 semantic performance baseline

- Executed at: `2026-08-18T13:08:34.885434+00:00`
- Git SHA: `ac1f43506e7cd2a51bf8db11af7233606ef6eb63`
- Command: `python backend/scripts/run_v21_semantic_cases.py --env-file <local-env> --datasource-id <datasource-id> --semantic-model-id <semantic-model-id> --output temp/day1/semantic-cases.json`
- Test count: `20` coverage cases plus `20` Golden value checks
- Catalog / Schema Linking p95: `6.292` ms
- Wren Golden result consistency: `1.0`
- Runtime call rates: OpenChatBI `1.0`, SuperSonic `1.0`, Wren `1.0`
- Raw evidence: `temp/day1/semantic-cases.json`
- Failures: `NONE`
- Blockers: `NONE`
- Frozen Zone intersections: `.env.example, backend/app/core/config.py, backend/app/query/oracle.py, backend/app/query/service.py, backend/app/semantic/engine.py, docker-compose.yml, frontend/src/pages/AskExperience.tsx`
- Migration impact: `NONE`
- License impact: clean-room compatible adapters; no upstream source, UI, logo, or binary copied.
- Rollback: set `CHATBI_SEMANTIC_RUNTIME_MODE=local` and restart the backend.
