# Third-Party Notices

## SQLGlot

- Source repository: `https://github.com/tobymao/sqlglot`
- Pinned source revision: `9a8129b6f2667673f24713f4b49162ebae1f699d` (`v30.17.0`)
- Package version: `sqlglot==30.17.0`
- License: MIT
- Project files: `backend/requirements.txt`, `backend/app/query/sql_guard.py`
- Purpose: parse PostgreSQL/MySQL SQL into an AST, reject unsafe statements and unauthorized objects, normalize SQL, and enforce a row limit.
- Modification: no SQLGlot source file was copied or modified. ChatBI uses the published package only through the project-owned `SqlGuard` boundary.

Other pre-existing runtime packages remain pinned in the relevant package manifests. No third-party logo, brand asset, UI source, or restricted project source was introduced in Day 2.
