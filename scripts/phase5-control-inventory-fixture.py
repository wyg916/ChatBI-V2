from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models import AppUser

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.performance.run_v13_phase5_api_load import BootstrapReceipt, MetadataBootstrap


TOKEN_RE = re.compile(r"^[0-9a-f]{12}$")
PASSWORD_ENV = "CHATBI_CONTROL_FIXTURE_BASE_PASSWORD"
DATABASE_ENV = "CHATBI_PHASE5_DATABASE_URL"


def _identity(token: str) -> tuple[str, str]:
    if not TOKEN_RE.fullmatch(token):
        raise ValueError("control fixture token must be exactly 12 lowercase hex characters")
    base_password = os.getenv(PASSWORD_ENV, "")
    if len(base_password) < 10:
        raise RuntimeError(f"{PASSWORD_ENV} is required and must contain at least 10 characters")
    return (
        f"phase5controls+{token}@load.chatbi.invalid",
        f"{base_password}-{token}-ControlInventory",
    )


def _engine(database_url: str, schema: str):
    return create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema}"},
    )


def create_fixture(*, database_url: str, schema: str, workspace_id: str, token: str) -> dict:
    email, password = _identity(token)
    engine = _engine(database_url, schema)
    try:
        with Session(engine) as session, session.begin():
            existing = session.scalar(select(AppUser).where(AppUser.email == email))
            if existing is not None:
                raise RuntimeError("CONTROL_FIXTURE_COLLISION")
            session.add(AppUser(
                workspace_id=workspace_id,
                email=email,
                display_name="Phase5 Control Inventory",
                role="ADMIN",
                status="ACTIVE",
                password_hash=hash_password(password),
            ))
    finally:
        engine.dispose()
    return {
        "schema_version": "chatbi.v13.phase5.control-inventory-fixture.v1",
        "status": "CREATED",
        "temporary_users": 1,
        "role": "ADMIN",
        "credential_persisted": False,
    }


def cleanup_fixture(
    *,
    database_url: str,
    schema: str,
    workspace_id: str,
    datasource_id: str,
    semantic_model_id: str,
    token: str,
) -> dict:
    email, _password = _identity(token)
    engine = _engine(database_url, schema)
    try:
        with Session(engine) as session:
            users = list(session.scalars(select(AppUser).where(AppUser.email == email)))
    finally:
        engine.dispose()
    if len(users) != 1:
        raise RuntimeError("CONTROL_FIXTURE_SCOPE_NOT_EXACT")
    bootstrap = MetadataBootstrap(
        database_url,
        metadata_schema=schema,
        workspace_id=workspace_id,
        datasource_id=datasource_id,
        semantic_model_id=semantic_model_id,
        request_prefix=f"phase5api-{token}-",
    )
    try:
        cleanup = bootstrap.cleanup(BootstrapReceipt(
            metadata_schema=schema,
            user_ids=(str(users[0].id),),
            users_created=1,
            grants_created=0,
        ))
    finally:
        bootstrap.close()
    return {
        "schema_version": "chatbi.v13.phase5.control-inventory-fixture-cleanup.v1",
        "status": "PASS" if cleanup.get("metadata_absence_verified") else "FAIL",
        "temporary_users": 1,
        "paid_provider_calls": 0,
        "paid_cost_cny": 0.0,
        "credential_persisted": False,
        "cleanup": cleanup,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or clean a run-scoped Phase5 control inventory admin")
    parser.add_argument("mode", choices=("create", "cleanup"))
    parser.add_argument("--schema", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--datasource-id", required=True)
    parser.add_argument("--semantic-model-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    database_url = os.getenv(DATABASE_ENV, "")
    if not database_url:
        raise SystemExit(f"{DATABASE_ENV} is required")
    if args.mode == "create":
        result = create_fixture(
            database_url=database_url,
            schema=args.schema,
            workspace_id=args.workspace_id,
            token=args.token,
        )
    else:
        result = cleanup_fixture(
            database_url=database_url,
            schema=args.schema,
            workspace_id=args.workspace_id,
            datasource_id=args.datasource_id,
            semantic_model_id=args.semantic_model_id,
            token=args.token,
        )
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(args.output)
    print(json.dumps({key: result[key] for key in ("status", "temporary_users", "credential_persisted")}))
    return 0 if result["status"] in {"CREATED", "PASS"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
