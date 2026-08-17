from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import AppUser, AuditEvent, ResourceGrant, Workspace


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
    db: Session = Depends(get_db),
    x_chatbi_actor: str | None = Header(default=None, alias="X-ChatBI-Actor"),
) -> Principal:
    actor = (x_chatbi_actor or "admin@chatbi.local").strip().lower()
    user = db.scalar(select(AppUser).where(AppUser.email == actor))
    if user is not None:
        if user.status != "ACTIVE":
            principal = Principal(user.id, user.workspace_id, user.email, user.display_name, user.role)
            record_audit(db, principal, action="AUTHENTICATE", resource_type="WORKSPACE", status="DENIED", details={"reason": "USER_DISABLED"})
            db.commit()
            raise HTTPException(status_code=403, detail="User is disabled")
        return Principal(user.id, user.workspace_id, user.email, user.display_name, user.role)
    if x_chatbi_actor:
        workspace_id = db.scalar(select(Workspace.id).order_by(Workspace.created_at))
        principal = Principal(None, workspace_id, actor, actor, "UNKNOWN")
        record_audit(db, principal, action="AUTHENTICATE", resource_type="WORKSPACE", status="DENIED", details={"reason": "UNKNOWN_ACTOR"})
        db.commit()
        raise HTTPException(status_code=401, detail="Unknown actor")
    workspace_id = db.scalar(select(Workspace.id).order_by(Workspace.created_at))
    return Principal(None, workspace_id, actor, "Local Administrator", "ADMIN")


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
