"""Idempotent deployment bootstrap for a migrated ChatBI metadata database.

This module deliberately does not provision PostgreSQL or bypass datasource APIs.
It only creates the default Workspace, local login identities, and the governed
RAG/Agent runtime records owned by ChatBI. Demo business resources remain opt-in.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import hash_password, verify_password
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import AppUser
from app.models.entities import utcnow
from app.services.datasources import default_workspace
from app.services.runtime_seed import seed_v1_runtime
from app.services.seed import seed_demo_semantic_model


BOOTSTRAP_USERS = (
    ("admin@chatbi.local", "ChatBI Administrator", "ADMIN", "bootstrap_admin_password"),
    ("analyst@chatbi.local", "ChatBI Analyst", "ANALYST", "bootstrap_analyst_password"),
)


def bootstrap_database(db: Session, *, demo_seed: bool = False) -> dict[str, int | str]:
    """Create deployment-owned baseline records and return non-secret counts."""

    settings = get_settings()
    workspace = default_workspace(db)
    created_users = 0
    updated_passwords = 0

    for email, display_name, role, password_setting in BOOTSTRAP_USERS:
        password = getattr(settings, password_setting).get_secret_value()
        if not password:
            raise ValueError(f"CHATBI_{password_setting.upper()} is required")
        user = db.scalar(select(AppUser).where(AppUser.email == email))
        if user is None:
            user = AppUser(
                workspace_id=workspace.id,
                email=email,
                display_name=display_name,
                role=role,
                status="ACTIVE",
                password_hash=hash_password(password),
                password_changed_at=utcnow(),
            )
            db.add(user)
            created_users += 1
        else:
            if user.workspace_id != workspace.id:
                raise ValueError(f"Bootstrap identity {email} belongs to another Workspace")
            user.display_name = display_name
            user.role = role
            user.status = "ACTIVE"
            if not user.password_hash or not verify_password(password, user.password_hash):
                user.password_hash = hash_password(password)
                user.password_changed_at = utcnow()
                updated_passwords += 1
    db.commit()

    if demo_seed:
        model = seed_demo_semantic_model(db)
        workspace = db.get(type(workspace), model.workspace_id) or workspace
    seed_v1_runtime(db, workspace.id)

    user_count = len(list(db.scalars(select(AppUser).where(AppUser.workspace_id == workspace.id))))
    return {
        "workspace_id": workspace.id,
        "created_users": created_users,
        "updated_passwords": updated_passwords,
        "user_count": user_count,
        "demo_seed": "ENABLED" if demo_seed else "DISABLED",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo-seed", action="store_true", help="install the optional local demo dataset bindings")
    args = parser.parse_args()
    with SessionLocal() as db:
        result = bootstrap_database(db, demo_seed=args.demo_seed)
    print("DEPLOYMENT_BOOTSTRAP=PASS")
    print(f"WORKSPACE_BOOTSTRAP=PASS USER_COUNT={result['user_count']}")
    print(f"DEMO_SEED={result['demo_seed']}")


if __name__ == "__main__":
    main()
