from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.auth import token_digest
from app.core.config import get_settings
from app.models import AppUser, AuditEvent, AuthSession, Dashboard, DataSource, QueryRun, ResourceGrant, SemanticModel, VerifiedAnswer


ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "ADMIN": frozenset({
        "workspace.read", "datasource.read", "datasource.manage", "semantic.read", "semantic.manage",
        "query.ask", "answer.read", "answer.manage", "dashboard.read", "dashboard.manage",
        "evaluation.read", "evaluation.run", "settings.read", "settings.manage", "audit.read",
    }),
    "ANALYST": frozenset({
        "workspace.read", "datasource.read", "semantic.read", "query.ask", "answer.read",
        "answer.manage", "dashboard.read", "dashboard.manage", "evaluation.read", "evaluation.run",
    }),
}


@dataclass(frozen=True)
class Principal:
    user_id: str | None
    workspace_id: str | None
    email: str
    display_name: str
    role: str
    session_id: str | None = None
    session_expires_at: datetime | None = None

    def allows(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS.get(self.role, frozenset())


def record_audit(
    db: Session,
    principal: Principal,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    status: str = "SUCCESS",
    details: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        workspace_id=principal.workspace_id,
        actor_user_id=principal.user_id,
        actor_email=principal.email,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        status=status,
        details=details or {},
    )
    db.add(event)
    return event


def get_principal(
    request: Request,
    db: Session = Depends(get_db),
) -> Principal:
    settings = get_settings()
    authorization = request.headers.get("authorization")
    token = request.cookies.get(settings.session_cookie_name)
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() != "bearer" or not value.strip():
            raise HTTPException(status_code=401, detail="Invalid authorization scheme")
        token = value.strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(token)))
    now = datetime.now(timezone.utc)
    if session is None or session.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Invalid session")
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise HTTPException(status_code=401, detail="Session expired")
    user = db.get(AppUser, session.user_id)
    if user is None or user.workspace_id != session.workspace_id:
        raise HTTPException(status_code=401, detail="Invalid session identity")
    principal = Principal(
        user.id, user.workspace_id, user.email, user.display_name, user.role,
        session_id=session.id, session_expires_at=expires_at,
    )
    if user.status != "ACTIVE":
        record_audit(db, principal, action="AUTHENTICATE", resource_type="WORKSPACE", status="DENIED", details={"reason": "USER_DISABLED"})
        db.commit()
        raise HTTPException(status_code=403, detail="User is disabled")
    session.last_seen_at = now
    user.last_active_at = now
    db.commit()
    return principal


def require_permission(permission: str) -> Callable:
    def dependency(
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> Principal:
        if not principal.allows(permission):
            record_audit(
                db, principal, action="ACCESS_CHECK", resource_type="PERMISSION",
                resource_id=permission, status="DENIED", details={"role": principal.role},
            )
            db.commit()
            raise HTTPException(status_code=403, detail=f"Permission denied: {permission}")
        return principal
    return dependency


def has_resource_access(db: Session, principal: Principal, *, resource_type: str, resource_id: str, query: bool = False) -> bool:
    if not principal.user_id or not principal.workspace_id:
        return False
    resource_classes = {
        "DATASOURCE": DataSource,
        "SEMANTIC_MODEL": SemanticModel,
        "QUERY_RUN": QueryRun,
        "ANSWER": VerifiedAnswer,
        "DASHBOARD": Dashboard,
    }
    resource_class = resource_classes.get(resource_type)
    if resource_class is not None:
        resource = db.get(resource_class, resource_id)
        if resource is not None and getattr(resource, "workspace_id", None) != principal.workspace_id:
            return False
    if principal.role == "ADMIN":
        return True
    if principal.user_id is None:
        return False
    grant = db.scalar(select(ResourceGrant).where(
        ResourceGrant.user_id == principal.user_id,
        ResourceGrant.resource_type == resource_type,
        ResourceGrant.resource_id == resource_id,
    ))
    return bool(grant and (grant.can_query if query else grant.can_read))


def ensure_resource_access(
    db: Session,
    principal: Principal,
    *,
    resource_type: str,
    resource_id: str,
    query: bool = False,
) -> None:
    if has_resource_access(db, principal, resource_type=resource_type, resource_id=resource_id, query=query):
        return
    record_audit(
        db, principal, action="RESOURCE_ACCESS", resource_type=resource_type,
        resource_id=resource_id, status="DENIED", details={"query": query, "role": principal.role},
    )
    db.commit()
    raise HTTPException(status_code=403, detail=f"Access denied for {resource_type.lower()}")
