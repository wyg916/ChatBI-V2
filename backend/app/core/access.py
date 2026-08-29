from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.auth import token_digest
from app.core.config import get_settings
from app.models import AppUser, AuditEvent, AuthSession, Conversation, Dashboard, DataSource, QueryRun, ResourceGrant, SemanticModel, VerifiedAnswer


ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "ADMIN": frozenset({
        "workspace.read", "datasource.read", "datasource.manage", "semantic.read", "semantic.manage",
        "query.ask", "answer.read", "answer.manage", "dashboard.read", "dashboard.manage",
        "evaluation.read", "evaluation.run", "settings.read", "settings.manage", "audit.read",
        "conversation.manage", "conversation.share", "project.manage",
    }),
    "ANALYST": frozenset({
        "workspace.read", "datasource.read", "semantic.read", "query.ask", "answer.read",
        "answer.manage", "dashboard.read", "dashboard.manage", "evaluation.read", "evaluation.run",
        "conversation.manage", "conversation.share", "project.manage",
    }),
}

_ACTIVITY_WRITE_INTERVAL = timedelta(seconds=60)


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


def grant_created_resource(
    db: Session,
    principal: Principal,
    *,
    resource_type: str,
    resource_id: str,
) -> None:
    """Give a non-admin creator durable access to their new resource."""

    if principal.role == "ADMIN" or not principal.user_id:
        return
    db.add(ResourceGrant(
        user_id=principal.user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        can_read=True,
        can_query=True,
    ))


def _request_token(request: Request) -> str:
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
    return token


def _principal_from_identity(db: Session, session: AuthSession, user: AppUser) -> Principal:
    now = datetime.now(timezone.utc)
    # The identity row has already been loaded by the caller's single joined
    # authentication query. Keep the checks here shared without issuing a
    # second lookup.
    if session.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Invalid session")
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise HTTPException(status_code=401, detail="Session expired")
    if user.workspace_id != session.workspace_id:
        raise HTTPException(status_code=401, detail="Invalid session identity")
    principal = Principal(
        user.id, user.workspace_id, user.email, user.display_name, user.role,
        session_id=session.id, session_expires_at=expires_at,
    )
    if user.status != "ACTIVE":
        record_audit(db, principal, action="AUTHENTICATE", resource_type="WORKSPACE", status="DENIED", details={"reason": "USER_DISABLED"})
        db.commit()
        raise HTTPException(status_code=403, detail="User is disabled")
    last_seen_at = session.last_seen_at
    if last_seen_at.tzinfo is None:
        last_seen_at = last_seen_at.replace(tzinfo=timezone.utc)
    # Session validation is read-heavy. Updating the same user/session rows on
    # every SSE/API request serializes an otherwise concurrent workload. A
    # bounded activity heartbeat preserves the product/audit signal without a
    # hot-row write for every request.
    if now - last_seen_at >= _ACTIVITY_WRITE_INTERVAL:
        session.last_seen_at = now
        user.last_active_at = now
        db.commit()
    return principal


def get_principal(
    request: Request,
    db: Session = Depends(get_db),
) -> Principal:
    token = _request_token(request)
    identity = db.execute(
        select(AuthSession, AppUser)
        .join(AppUser, AppUser.id == AuthSession.user_id)
        .where(AuthSession.token_hash == token_digest(token))
    ).first()
    if identity is None:
        raise HTTPException(status_code=401, detail="Invalid session")
    session, user = identity
    return _principal_from_identity(db, session, user)


def get_conversation_principal(
    request: Request,
    db: Session,
    *,
    conversation_id: str,
    permission: str = "query.ask",
) -> Principal:
    """Authenticate and authorize one conversation in a single joined read."""
    token = _request_token(request)
    identity = db.execute(
        select(AuthSession, AppUser, Conversation.id)
        .join(AppUser, AppUser.id == AuthSession.user_id)
        .outerjoin(
            Conversation,
            and_(
                Conversation.id == conversation_id,
                Conversation.workspace_id == AuthSession.workspace_id,
                Conversation.user_id == AppUser.id,
            ),
        )
        .where(AuthSession.token_hash == token_digest(token))
    ).first()
    if identity is None:
        raise HTTPException(status_code=401, detail="Invalid session")
    session, user, authorized_conversation_id = identity
    principal = _principal_from_identity(db, session, user)
    if not principal.allows(permission):
        record_audit(
            db, principal, action="ACCESS_CHECK", resource_type="PERMISSION",
            resource_id=permission, status="DENIED", details={"role": principal.role},
        )
        db.commit()
        raise HTTPException(status_code=403, detail=f"Permission denied: {permission}")
    if authorized_conversation_id is None:
        raise HTTPException(status_code=403, detail="Conversation access denied")
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
    if not principal.workspace_id:
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
    if not principal.user_id:
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


def ensure_query_run_access(
    db: Session,
    principal: Principal,
    run: QueryRun,
    *,
    require_owner: bool = True,
) -> None:
    """Authorize a persisted QueryRun through all of its bound resources.

    QueryRun identifiers appear in answers, evaluation and audit views, so
    workspace membership alone is not an access boundary.  Analysts must retain
    query rights to both bound resources and, for private run operations, own
    the original server-authenticated request.  Administrators retain their
    workspace-wide operational view.
    """

    if run.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=403, detail="Query run access denied")
    ensure_resource_access(
        db,
        principal,
        resource_type="DATASOURCE",
        resource_id=run.datasource_id,
        query=True,
    )
    ensure_resource_access(
        db,
        principal,
        resource_type="SEMANTIC_MODEL",
        resource_id=run.semantic_model_id,
        query=True,
    )
    if principal.role == "ADMIN" or not require_owner:
        return
    request_context = (run.context_payload or {}).get("request_context")
    owner_id = request_context.get("user_id") if isinstance(request_context, dict) else None
    if owner_id and owner_id == principal.user_id:
        return
    record_audit(
        db,
        principal,
        action="RESOURCE_ACCESS",
        resource_type="QUERY_RUN",
        resource_id=run.id,
        status="DENIED",
        details={"reason": "QUERY_RUN_OWNER_MISMATCH"},
    )
    db.commit()
    raise HTTPException(status_code=403, detail="Query run access denied")
