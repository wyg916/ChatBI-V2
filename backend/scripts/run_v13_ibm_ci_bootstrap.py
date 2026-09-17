"""Bootstrap the self-contained V1.3 IBM CI runtime.

The GitHub-hosted job provides only an ephemeral PostgreSQL administrator. This
script creates least-privilege application/query roles, loads the frozen demo
dataset, and exports per-run random ChatBI credentials through ``GITHUB_ENV``.
No generated credential is written to the repository or printed as evidence.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import secrets
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import quote

import psycopg
from psycopg import sql


PROJECT_ROOT = Path(__file__).resolve().parents[2]
POSTGRES_SEED = PROJECT_ROOT / "database" / "postgresql" / "demo_business.sql"
FIXED_SEED_DATE = date(2026, 8, 17)
FIXED_RESULT_TIMEZONE = "Asia/Shanghai"
APP_ROLE = "chatbi_app"
READER_ROLE = "chatbi_reader"
APP_DATABASE = "chatbi_v2"
SENSITIVE_ENV_KEYS = (
    "CHATBI_CI_POSTGRES_ADMIN_PASSWORD",
    "CHATBI_META_PASSWORD",
    "CHATBI_DEMO_POSTGRES_PASSWORD",
    "CHATBI_DEMO_MYSQL_PASSWORD",
    "CHATBI_DATASOURCE_SECRET_KEY",
    "CHATBI_RAG_SHARED_SECRET",
    "CHATBI_BOOTSTRAP_ADMIN_PASSWORD",
    "CHATBI_BOOTSTRAP_ANALYST_PASSWORD",
    "CHATBI_DATABASE_URL",
)
POPULATED_AUTHORIZATION = re.compile(
    r"(?i)\bauthorization\s*[:=]\s*(?:bearer\s+)?(?!<REDACTED>)[^\s\"',}]+"
)
CREDENTIAL_URL = re.compile(
    r"(?i)\b(?:postgres(?:ql)?(?:\+psycopg)?|mysql(?:\+pymysql)?)://"
    r"[^\s/:@]+:[^\s/@]+@"
)


def build_ephemeral_environment(*, host: str, port: int, database: str) -> dict[str, str]:
    """Return per-run credentials and deterministic runtime configuration."""
    meta_password = secrets.token_urlsafe(30)
    reader_password = secrets.token_urlsafe(30)
    admin_password = secrets.token_urlsafe(24)
    analyst_password = secrets.token_urlsafe(24)
    encoded_meta_password = quote(meta_password, safe="")
    return {
        "CHATBI_META_PASSWORD": meta_password,
        "CHATBI_DEMO_POSTGRES_PASSWORD": reader_password,
        "CHATBI_DEMO_MYSQL_PASSWORD": secrets.token_urlsafe(30),
        "CHATBI_DATASOURCE_SECRET_KEY": secrets.token_urlsafe(48),
        "CHATBI_RAG_SHARED_SECRET": secrets.token_urlsafe(48),
        "CHATBI_BOOTSTRAP_ADMIN_PASSWORD": admin_password,
        "CHATBI_BOOTSTRAP_ANALYST_PASSWORD": analyst_password,
        "CHATBI_DATABASE_URL": (
            f"postgresql+psycopg://{APP_ROLE}:{encoded_meta_password}@{host}:{port}/{database}"
        ),
        "CHATBI_DEMO_POSTGRES_HOST": host,
        "CHATBI_DEMO_POSTGRES_PORT": str(port),
        "CHATBI_DEMO_POSTGRES_DATABASE": database,
        "CHATBI_DEMO_POSTGRES_SCHEMA": "demo_business",
        "CHATBI_DEMO_POSTGRES_USERNAME": READER_ROLE,
    }


def frozen_seed_sql(seed_path: Path, fixed_date: date = FIXED_SEED_DATE) -> str:
    """Replace wall-clock SQL dates with the Golden-50 freeze date."""
    seed = seed_path.read_text(encoding="utf-8")
    rendered = re.sub(
        r"\bcurrent_date\b",
        f"DATE '{fixed_date.isoformat()}'",
        seed,
        flags=re.IGNORECASE,
    )
    if re.search(r"\bcurrent_date\b", rendered, flags=re.IGNORECASE):
        raise RuntimeError("CI_FIXED_SEED_DATE_REPLACEMENT_FAILED")
    return rendered


def export_github_environment(values: dict[str, str], path: Path) -> None:
    """Append validated single-line values to the runner-managed environment."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for key, value in values.items():
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
                raise ValueError(f"Invalid environment key: {key}")
            if "\n" in value or "\r" in value:
                raise ValueError(f"Environment value for {key} must be single-line")
            handle.write(f"{key}={value}\n")


def _active_secret_values() -> list[str]:
    return [
        value
        for key in SENSITIVE_ENV_KEYS
        if len(value := os.getenv(key, "")) >= 6
    ]


def redact_evidence_text(text: str, secret_values: list[str]) -> str:
    """Remove exact generated secrets and populated credential patterns."""
    redacted = text
    for value in sorted(secret_values, key=len, reverse=True):
        redacted = redacted.replace(value, "<REDACTED>")
    redacted = POPULATED_AUTHORIZATION.sub("Authorization: <REDACTED>", redacted)
    redacted = CREDENTIAL_URL.sub("postgresql://<REDACTED>@", redacted)
    return redacted


def sanitize_artifacts(artifact_dir: Path, backend_log: Path | None = None) -> dict[str, object]:
    """Redact logs and fail closed if any artifact still contains credentials."""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    secret_values = _active_secret_values()
    if backend_log is not None and backend_log.exists():
        raw_log = backend_log.read_text(encoding="utf-8", errors="replace")
        (artifact_dir / "backend.log").write_text(
            redact_evidence_text(raw_log, secret_values), encoding="utf-8"
        )

    scanned_files = 0
    for path in sorted(artifact_dir.iterdir()):
        if not path.is_file() or path.name in {"SHA256SUMS.txt", "secret-scan.json"}:
            continue
        scanned_files += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        leaked_key = next(
            (
                key
                for key in SENSITIVE_ENV_KEYS
                if (value := os.getenv(key, "")) and value in text
            ),
            None,
        )
        if leaked_key:
            raise RuntimeError(
                f"CI_ARTIFACT_SECRET_SCAN_FAILED exact_value={leaked_key} file={path.name}"
            )
        if POPULATED_AUTHORIZATION.search(text):
            raise RuntimeError(f"CI_ARTIFACT_SECRET_SCAN_FAILED authorization file={path.name}")
        if CREDENTIAL_URL.search(text):
            raise RuntimeError(f"CI_ARTIFACT_SECRET_SCAN_FAILED credential_url file={path.name}")

    receipt: dict[str, object] = {
        "status": "PASS",
        "scanned_files": scanned_files,
        "exact_generated_secret_matches": 0,
        "populated_authorization_matches": 0,
        "credential_url_matches": 0,
        "raw_backend_log_uploaded": False,
        "backend_log_mode": "redacted_copy" if backend_log is not None else "not_requested",
    }
    (artifact_dir / "secret-scan.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return receipt


def _api_request(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    method: str,
    path: str,
    body: dict[str, object] | None = None,
) -> object:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=payload,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with opener.open(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[-1000:]
        raise RuntimeError(
            f"CI_API_PREPARE_FAILED {method} {path} HTTP {exc.code} {detail}"
        ) from exc


def prepare_live_api(base_url: str, email: str = "admin@chatbi.local") -> dict[str, object]:
    """Create an authenticated session and synchronize only the PostgreSQL catalog."""
    password = os.getenv("CHATBI_BOOTSTRAP_ADMIN_PASSWORD", "")
    if not password:
        raise RuntimeError("Missing ephemeral CHATBI_BOOTSTRAP_ADMIN_PASSWORD")
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    _api_request(
        opener,
        base_url,
        "POST",
        "/auth/login",
        {"email": email, "password": password},
    )
    sources = _api_request(opener, base_url, "GET", "/datasources")
    if not isinstance(sources, list):
        raise RuntimeError("CI_API_PREPARE_FAILED datasource response is not a list")
    postgres = next(
        (
            source
            for source in sources
            if isinstance(source, dict) and source.get("type") == "postgresql"
        ),
        None,
    )
    if postgres is None:
        raise RuntimeError("CI_API_PREPARE_FAILED PostgreSQL datasource not found")
    datasource_id = str(postgres["id"])
    tested = _api_request(opener, base_url, "POST", f"/datasources/{datasource_id}/test")
    synced = _api_request(opener, base_url, "POST", f"/datasources/{datasource_id}/sync")
    if not isinstance(tested, dict) or not tested.get("success"):
        raise RuntimeError("CI_API_PREPARE_FAILED PostgreSQL readonly connection test")
    if not isinstance(synced, dict) or not synced.get("success"):
        raise RuntimeError("CI_API_PREPARE_FAILED PostgreSQL catalog sync")
    return {
        "status": "PASS",
        "datasource_type": "postgresql",
        "connection_test": "PASS",
        "catalog_sync": "PASS",
    }


def _upsert_login_role(cursor: psycopg.Cursor, role: str, password: str) -> None:
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    statement = (
        "ALTER ROLE {} LOGIN PASSWORD {}"
        if cursor.fetchone()
        else "CREATE ROLE {} LOGIN PASSWORD {}"
    )
    cursor.execute(sql.SQL(statement).format(sql.Identifier(role), sql.Literal(password)))


def bootstrap_postgres(
    *,
    host: str,
    port: int,
    admin_user: str,
    admin_password: str | None,
    admin_database: str,
    app_database: str,
    values: dict[str, str],
    seed_path: Path,
    fixed_date: date,
) -> tuple[int, int]:
    """Create the isolated database, roles and reproducible demo schema."""
    connect_kwargs: dict[str, object] = {
        "host": host,
        "port": port,
        "user": admin_user,
        "autocommit": True,
    }
    if admin_password is not None:
        connect_kwargs["password"] = admin_password
    with psycopg.connect(dbname=admin_database, **connect_kwargs) as admin:
        with admin.cursor() as cursor:
            _upsert_login_role(cursor, APP_ROLE, values["CHATBI_META_PASSWORD"])
            _upsert_login_role(cursor, READER_ROLE, values["CHATBI_DEMO_POSTGRES_PASSWORD"])
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(
                    sql.Identifier(READER_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET statement_timeout = '30s'").format(
                    sql.Identifier(READER_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("ALTER ROLE {} SET timezone = {}").format(
                    sql.Identifier(READER_ROLE), sql.Literal(FIXED_RESULT_TIMEZONE)
                )
            )
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (app_database,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(app_database), sql.Identifier(APP_ROLE)
                    )
                )
            else:
                cursor.execute(
                    sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                        sql.Identifier(app_database), sql.Identifier(APP_ROLE)
                    )
                )

    with psycopg.connect(dbname=app_database, **connect_kwargs) as database:
        with database.cursor() as cursor:
            cursor.execute("DROP SCHEMA IF EXISTS demo_business CASCADE")
            cursor.execute(
                sql.SQL("CREATE SCHEMA demo_business AUTHORIZATION {}").format(
                    sql.Identifier(admin_user)
                )
            )
            cursor.execute(frozen_seed_sql(seed_path, fixed_date), prepare=False)
            cursor.execute("REVOKE ALL ON SCHEMA demo_business FROM PUBLIC")
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(app_database), sql.Identifier(READER_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA demo_business TO {}").format(
                    sql.Identifier(READER_ROLE)
                )
            )
            cursor.execute(
                sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA demo_business TO {}").format(
                    sql.Identifier(READER_ROLE)
                )
            )
            cursor.execute("SELECT count(*) FROM demo_business.orders")
            order_count = int(cursor.fetchone()[0])
            cursor.execute("SELECT count(*) FROM demo_business.daily_kpi")
            kpi_count = int(cursor.fetchone()[0])
    if (order_count, kpi_count) != (1095, 1825):
        raise RuntimeError(
            f"CI_FIXED_SEED_COUNT_INVALID orders={order_count} daily_kpi={kpi_count}"
        )
    return order_count, kpi_count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap isolated PostgreSQL for the IBM CI Gate"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--admin-user", default="chatbi_ci_admin")
    parser.add_argument(
        "--admin-password-env", default="CHATBI_CI_POSTGRES_ADMIN_PASSWORD"
    )
    parser.add_argument(
        "--allow-local-trust",
        action="store_true",
        help="Allow passwordless bootstrap only for an isolated loopback PostgreSQL service",
    )
    parser.add_argument("--admin-database", default="postgres")
    parser.add_argument("--app-database", default=APP_DATABASE)
    parser.add_argument("--fixed-date", type=date.fromisoformat, default=FIXED_SEED_DATE)
    parser.add_argument("--seed", type=Path, default=POSTGRES_SEED)
    parser.add_argument("--github-env", type=Path, default=os.getenv("GITHUB_ENV"))
    parser.add_argument("--sanitize-artifacts", type=Path)
    parser.add_argument("--backend-log", type=Path)
    parser.add_argument("--prepare-api")
    parser.add_argument(
        "--no-mask-commands",
        action="store_true",
        help="Do not emit GitHub add-mask commands (for local validation only)",
    )
    args = parser.parse_args()

    if args.sanitize_artifacts is not None:
        receipt = sanitize_artifacts(args.sanitize_artifacts, args.backend_log)
        print(f"CI_ARTIFACT_SECRET_SCAN={receipt['status']}")
        print(f"SCANNED_ARTIFACT_FILES={receipt['scanned_files']}")
        return 0
    if args.prepare_api is not None:
        prepared = prepare_live_api(args.prepare_api)
        print(f"CI_API_PREPARE={prepared['status']}")
        print("POSTGRES_READONLY_CONNECTION_TEST=PASS")
        print("POSTGRES_CATALOG_SYNC=PASS")
        return 0

    admin_password = os.getenv(args.admin_password_env) or None
    if admin_password is None and not args.allow_local_trust:
        raise RuntimeError(
            f"Missing ephemeral PostgreSQL admin password in {args.admin_password_env}"
        )
    if args.allow_local_trust and args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Local trust bootstrap is restricted to a loopback PostgreSQL host")
    if args.github_env is None:
        raise RuntimeError("GITHUB_ENV path is required for ephemeral credential handoff")

    values = build_ephemeral_environment(
        host=args.host,
        port=args.port,
        database=args.app_database,
    )
    order_count, kpi_count = bootstrap_postgres(
        host=args.host,
        port=args.port,
        admin_user=args.admin_user,
        admin_password=admin_password,
        admin_database=args.admin_database,
        app_database=args.app_database,
        values=values,
        seed_path=args.seed,
        fixed_date=args.fixed_date,
    )
    if not args.no_mask_commands:
        for value in values.values():
            print(f"::add-mask::{value}")
    export_github_environment(values, args.github_env)
    print("CI_POSTGRES_BOOTSTRAP=PASS")
    print(f"FIXED_SEED_DATE={args.fixed_date.isoformat()}")
    print(f"FIXED_RESULT_TIMEZONE={FIXED_RESULT_TIMEZONE}")
    print(f"POSTGRES_ORDERS={order_count} POSTGRES_DAILY_KPI={kpi_count}")
    print("EPHEMERAL_CREDENTIALS=GENERATED_MASKED_RUNNER_ENV_ONLY")
    print("PRODUCTION_DATABASE=NO PRODUCTION_SECRET=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
