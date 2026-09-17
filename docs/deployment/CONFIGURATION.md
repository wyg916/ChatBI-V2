# Configuration

ChatBI reads server-side values from `.env` or an explicit `-EnvFile`. The Browser never receives database credentials or Provider keys.

| Setting | Class | Purpose |
|---|---|---|
| `CHATBI_DATABASE_URL` | REQUIRED | PostgreSQL SQLAlchemy URL for ChatBI metadata |
| `CHATBI_DATABASE_SCHEMA` | ENTERPRISE_OVERRIDE | Isolated metadata schema; required for guarded metadata Reset |
| `CHATBI_DATASOURCE_SECRET_KEY` | REQUIRED | Encrypts datasource secrets; generated locally |
| `CHATBI_RAG_SHARED_SECRET` | REQUIRED | Signs Backend-to-RAG requests; generated locally |
| `CHATBI_BOOTSTRAP_ADMIN_PASSWORD` | REQUIRED | Initial local administrator password; generated locally |
| `CHATBI_BOOTSTRAP_ANALYST_PASSWORD` | REQUIRED | Initial local analyst password; generated locally |
| `COMPOSE_PROJECT_NAME` | DEFAULT | Scopes all Compose resources |
| `CHATBI_BACKEND_IMAGE` / `CHATBI_FRONTEND_IMAGE` / `CHATBI_SANDBOX_IMAGE` | ENTERPRISE_OVERRIDE | Optional immutable/private image names; defaults are project-scoped |
| `CHATBI_DEPLOYMENT_MODE` | DEFAULT | `local` or operator-defined private mode label |
| `CHATBI_ENVIRONMENT` | DEFAULT | Runtime safety mode; Showcase sets `development`, enterprise defaults to `local` |
| `CHATBI_GIT_SHA` | DEFAULT | Exact candidate/runtime source identity; never a credential |
| `CHATBI_RELEASE_VERSION` | DEFAULT | Candidate/release display identity |
| `CHATBI_FRONTEND_BUILD` | DEFAULT | Frontend build identity reported by System Info |
| `CHATBI_BIND_HOST` | DEFAULT | IPv4 host address for published Compose ports; default/Enterprise remains `0.0.0.0`, while Local Showcase forces `127.0.0.1` |
| `CHATBI_FRONTEND_PORT` | DEFAULT | Frontend published port, default 5173 |
| `CHATBI_BACKEND_PORT` | DEFAULT | Backend published port, default 8000 |
| `CHATBI_RAG_PORT` | DEFAULT | RAG published port, default 8001 |
| `CHATBI_CORS_ALLOW_ORIGINS` | REQUIRED | Exact browser origins when sessions use credentials |
| `CHATBI_STORAGE_ROOT` | DEFAULT | Bind directory for attachment storage |
| `CHATBI_BACKUP_ROOT` | DEFAULT | Bind directory for metadata dumps and storage archives |
| `CHATBI_SEED_DEMO_SEMANTIC_MODEL` | OPTIONAL | Enable only for local demo experience |
| `CHATBI_MODEL_PROVIDER` | OPTIONAL | `auto`, `deterministic`, or a named Provider |
| `CHATBI_PROVIDER_USAGE_UNRESTRICTED` | OPTIONAL | For MiMo, DeepSeek and Kimi only, bypass ChatBI internal estimated-cost, Kimi admission, candidate-count and retry-count routing caps; generic/future Providers stay governed, and credentials, health, safety and Provider-side quotas are never bypassed |
| `CHATBI_MIMO_API_KEY` | OPTIONAL | MiMo server-side credential |
| `CHATBI_DEEPSEEK_API_KEY` | OPTIONAL | DeepSeek server-side credential |
| `CHATBI_KIMI_API_KEY` | OPTIONAL | Kimi server-side credential |
| `CHATBI_RAG_MODE` | DEFAULT | V1 default `on`; diagnostic modes remain supported |
| `CHATBI_AGENT_MODE` | DEFAULT | V1 default `on`; bounded orchestration only |
| `CHATBI_DOCKER_SOCKET_PATH` | LOCAL_DEPLOYMENT | Docker socket used by the restricted Sandbox proxy |

The full copy-ready list with safe defaults is in `.env.example`.

## Configuration precedence

Lifecycle scripts use one deterministic order:

```text
explicit Process / CLI value
> explicitly selected mode EnvFile (-EnvFile)
> default repository .env
> hard-coded safe default
```

Importing an EnvFile fills only process variables that are not already set. This is required so Local Showcase can pin its project name, loopback bind host, ports, credentials, Demo Seed, development guard, and image identities even when the selected `.env` also contains enterprise defaults. Its explicit `ProviderMode` then selects `Auto` (live quality routing when a supported key exists, otherwise deterministic), `Live`, or `Deterministic`; normal starts preserve administrator Provider enable/disable state. Default and Enterprise commands should prefer a dedicated `-EnvFile` rather than mutating a shared file.

The normal deployment default remains `CHATBI_BIND_HOST=0.0.0.0` for operator-managed network exposure. Local Showcase always overrides it to `127.0.0.1`; its documented fixed demonstration credentials are therefore not published to LAN interfaces. Use a production identity provider, rotated secrets, TLS and an explicit network policy before exposing an enterprise deployment.

## PostgreSQL URL

Example shape only:

```text
postgresql+psycopg://<app-user>:<password>@host.docker.internal:5432/<database>
```

Use a dedicated application role. Do not use the `postgres` superuser. For an isolated schema, configure the connection's PostgreSQL `search_path` and set `CHATBI_DATABASE_SCHEMA` to the same exact schema.

`localhost` and `127.0.0.1` are rejected in `CHATBI_DATABASE_URL` because they refer to the Backend container itself.

## Managed spreadsheet readers

Excel/CSV imports materialize into a dedicated local PostgreSQL `excel_<id>` Schema and connect through a matching `chatbi_excel_<id>` read-only login. The application role remains `NOSUPERUSER`/`NOCREATEROLE`; a PostgreSQL administrator installs two identifier-constrained SECURITY DEFINER helpers once during local provisioning:

```powershell
.\scripts\bootstrap-local-databases.ps1 -SpreadsheetHelpersOnly
```

The script requests the PostgreSQL administrator password as a secure prompt, does not request MySQL for this mode, does not persist the administrator credential, and never prints it. The helpers live in the locked `chatbi_admin` Schema so a metadata-Schema rebuild does not remove them. Import fails closed with `SPREADSHEET_READER_PROVISIONER_UNAVAILABLE` when the helpers are absent. Deleting an imported datasource or explicitly resetting the Showcase removes its scoped role and Schema together.

## Secret generation

After `.env.example` is copied, Bootstrap replaces only the four `<GENERATED_BY_BOOTSTRAP>` values with cryptographically random local values. Existing values are preserved, so repeated Bootstrap is idempotent.

No secret is printed. Protect `.env`, use restrictive filesystem permissions on a server, and never commit it.

## Provider behavior

No Provider key is required for health, login, datasource onboarding, Schema Sync, or deterministic NL2SQL. `auto` uses a configured and runtime-enabled Provider when one is available and otherwise keeps the local deterministic route. Local Showcase `Auto`/`Live` sets `CHATBI_PROVIDER_USAGE_UNRESTRICTED=true`: MiMo, DeepSeek and Kimi remain available to capability/health routing without ChatBI estimated-cost, Kimi complexity-admission, candidate-count or retry-count caps. This does not bypass administrator enablement, credentials, circuit health, answer safety, SQL/Agent hard bounds, or Provider-side balance/quota/rate limits. Doctor reports Configured, Enabled, last recorded Health, and Reachability state without issuing a Provider request; reachability stays `NOT_TESTED` until an explicit model test or real call. UI and API capability responses expose the effective unrestricted state without exposing secrets.

## Fail-fast checks

`scripts/config.ps1` and `scripts/doctor.ps1` reject:

- malformed or duplicate dotenv entries;
- missing application secrets;
- missing/invalid PostgreSQL URL;
- container-unreachable localhost URLs;
- invalid or duplicate published ports;
- malformed Provider URLs;
- Demo Seed without its two local reader credentials;
- invalid Compose project names;
- a Compose configuration Docker itself cannot render.
