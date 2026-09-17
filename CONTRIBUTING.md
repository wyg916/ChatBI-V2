# Contributing

Keep changes focused on ChatBI data access, semantics, safe queries, verifiable results, retrieval, answers, and dashboards. Use small pull requests describing behavior and validation.

Run `python -m compileall -q backend/app backend/alembic packages sandbox_runtime`. In `frontend`, run `npm ci` and `npm run build`. Runtime changes also require validation against your configured database and business definitions; report any checks that could not be completed.

Never commit credentials, local databases, generated assets, or personal documents. Third-party contributions must include license and provenance records. See [architecture](docs/ARCHITECTURE.md) and [security](SECURITY.md).
