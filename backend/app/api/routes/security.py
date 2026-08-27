import csv
import io
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.access import ROLE_PERMISSIONS, Principal, record_audit, require_permission
from app.core.auth import token_digest
from app.db.session import get_db
from app.models import AppUser, AuditEvent, WorkspaceInvitation
from app.schemas.security import (
    AuditEventRead, AuditPage, InvitationCreate, InvitationCreated, InvitationRead,
    RoleRead, SecurityOverview, UserRead, UserUpdate,
)


router = APIRouter(prefix="/security", tags=["security and audit"])


@router.get("/overview", response_model=SecurityOverview)
def security_overview(
    user_query: str = "",
    user_status: str = Query(default="ALL", pattern="^(ALL|ACTIVE|DISABLED)$"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("audit.read")),
):
    users_statement = select(AppUser).where(AppUser.workspace_id == principal.workspace_id)
    if user_query.strip():
        keyword = f"%{user_query.strip()}%"
        users_statement = users_statement.where(or_(
            AppUser.display_name.ilike(keyword),
            AppUser.email.ilike(keyword),
            AppUser.role.ilike(keyword),
        ))
    if user_status != "ALL":
        users_statement = users_statement.where(AppUser.status == user_status)
    users = list(db.scalars(users_statement.order_by(AppUser.created_at, AppUser.email)))
    now = datetime.now(timezone.utc)
    expired = list(db.scalars(select(WorkspaceInvitation).where(
        WorkspaceInvitation.workspace_id == principal.workspace_id,
        WorkspaceInvitation.status == "PENDING", WorkspaceInvitation.expires_at <= now,
    )))
    for invite in expired:
        invite.status = "EXPIRED"
    if expired:
        db.commit()
    events = list(db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == principal.workspace_id).order_by(AuditEvent.created_at.desc()).limit(100)))
    invitations = list(db.scalars(select(WorkspaceInvitation).where(WorkspaceInvitation.workspace_id == principal.workspace_id).order_by(WorkspaceInvitation.created_at.desc())))
    counts = dict(db.execute(select(AppUser.role, func.count(AppUser.id)).where(AppUser.workspace_id == principal.workspace_id).group_by(AppUser.role)).all())
    current = db.get(AppUser, principal.user_id)
    return SecurityOverview(
        current_actor=UserRead.model_validate(current) if current and current.workspace_id == principal.workspace_id else None,
        user_count=db.scalar(select(func.count(AppUser.id)).where(AppUser.workspace_id == principal.workspace_id)) or 0,
        role_count=len(ROLE_PERMISSIONS),
        active_user_count=db.scalar(select(func.count(AppUser.id)).where(AppUser.workspace_id == principal.workspace_id, AppUser.status == "ACTIVE")) or 0,
        audit_event_count=db.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.workspace_id == principal.workspace_id)) or 0,
        users=[UserRead.model_validate(item) for item in users],
        roles=[RoleRead(name=name, permissions=sorted(permissions), user_count=counts.get(name, 0)) for name, permissions in ROLE_PERMISSIONS.items()],
        audit_events=[AuditEventRead.model_validate(item) for item in events],
        invitations=[InvitationRead.model_validate(item) for item in invitations],
    )


def _workspace_user(db: Session, principal: Principal, user_id: str) -> AppUser:
    user = db.get(AppUser, user_id)
    if user is None or user.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _active_admin_count(db: Session, workspace_id: str) -> int:
    return db.scalar(select(func.count(AppUser.id)).where(
        AppUser.workspace_id == workspace_id, AppUser.role == "ADMIN", AppUser.status == "ACTIVE",
    )) or 0


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: str, payload: UserUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.manage")),
):
    user = _workspace_user(db, principal, user_id)
    if payload.role is None and payload.status is None:
        raise HTTPException(status_code=422, detail="No changes supplied")
    removes_active_admin = user.role == "ADMIN" and user.status == "ACTIVE" and (
        payload.role == "ANALYST" or payload.status == "DISABLED"
    )
    if removes_active_admin and _active_admin_count(db, user.workspace_id) <= 1:
        raise HTTPException(status_code=409, detail="LAST_ACTIVE_ADMIN_PROTECTED")
    if user.id == principal.user_id and (payload.role == "ANALYST" or payload.status == "DISABLED"):
        raise HTTPException(status_code=409, detail="ADMIN_SELF_LOCKOUT_PROTECTED")
    changes: dict[str, dict[str, str]] = {}
    if payload.role is not None and payload.role != user.role:
        changes["role"] = {"before": user.role, "after": payload.role}
        user.role = payload.role
    if payload.status is not None and payload.status != user.status:
        changes["status"] = {"before": user.status, "after": payload.status}
        user.status = payload.status
    if not changes:
        return UserRead.model_validate(user)
    record_audit(db, principal, action="UPDATE_USER", resource_type="USER", resource_id=user.id, details={"changes": changes})
    db.commit()
    return UserRead.model_validate(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_user(
    user_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.manage")),
):
    user = _workspace_user(db, principal, user_id)
    if user.id == principal.user_id:
        raise HTTPException(status_code=409, detail="ADMIN_SELF_REMOVAL_PROTECTED")
    if user.role == "ADMIN" and user.status == "ACTIVE" and _active_admin_count(db, user.workspace_id) <= 1:
        raise HTTPException(status_code=409, detail="LAST_ACTIVE_ADMIN_PROTECTED")
    record_audit(db, principal, action="REMOVE_MEMBER", resource_type="USER", resource_id=user.id, details={"email": user.email, "role": user.role})
    db.delete(user)
    db.commit()


@router.post("/invitations", response_model=InvitationCreated, status_code=status.HTTP_201_CREATED)
def create_invitation(
    payload: InvitationCreate, request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.manage")),
):
    email = payload.email.strip().lower()
    if db.scalar(select(AppUser.id).where(AppUser.workspace_id == principal.workspace_id, func.lower(AppUser.email) == email)):
        raise HTTPException(status_code=409, detail="USER_ALREADY_MEMBER")
    now = datetime.now(timezone.utc)
    pending = db.scalar(select(WorkspaceInvitation).where(
        WorkspaceInvitation.workspace_id == principal.workspace_id,
        func.lower(WorkspaceInvitation.email) == email,
        WorkspaceInvitation.status == "PENDING",
        WorkspaceInvitation.expires_at > now,
    ))
    if pending:
        raise HTTPException(status_code=409, detail="ACTIVE_INVITATION_EXISTS")
    token = token_urlsafe(32)
    invite = WorkspaceInvitation(
        workspace_id=principal.workspace_id, email=email, role=payload.role,
        token_hash=token_digest(token), expires_at=now + timedelta(days=payload.expires_in_days),
        created_by=principal.user_id,
    )
    db.add(invite)
    db.flush()
    record_audit(db, principal, action="INVITE_MEMBER", resource_type="INVITATION", resource_id=invite.id, details={"email": email, "role": payload.role, "expires_in_days": payload.expires_in_days})
    db.commit()
    base = str(request.base_url).rstrip("/")
    return InvitationCreated.model_validate({
        **InvitationRead.model_validate(invite).model_dump(),
        "invite_url": f"{base}/invite/{token}",
    })


@router.post("/invitations/{invitation_id}/revoke", response_model=InvitationRead)
def revoke_invitation(
    invitation_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.manage")),
):
    invite = db.get(WorkspaceInvitation, invitation_id)
    if invite is None or invite.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invite.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"INVITATION_{invite.status}")
    invite.status = "REVOKED"
    invite.revoked_at = datetime.now(timezone.utc)
    record_audit(db, principal, action="REVOKE_INVITATION", resource_type="INVITATION", resource_id=invite.id, details={"email": invite.email})
    db.commit()
    return InvitationRead.model_validate(invite)


def _audit_statement(principal: Principal, query: str, action: str, actor: str, resource: str, event_status: str, start_at: datetime | None, end_at: datetime | None):
    statement = select(AuditEvent).where(AuditEvent.workspace_id == principal.workspace_id)
    if query.strip():
        keyword = f"%{query.strip()}%"
        statement = statement.where(or_(AuditEvent.actor_email.ilike(keyword), AuditEvent.action.ilike(keyword), AuditEvent.resource_type.ilike(keyword), AuditEvent.resource_id.ilike(keyword)))
    if action:
        statement = statement.where(AuditEvent.action == action)
    if actor:
        statement = statement.where(AuditEvent.actor_email.ilike(f"%{actor.strip()}%"))
    if resource:
        statement = statement.where(AuditEvent.resource_type == resource)
    if event_status:
        statement = statement.where(AuditEvent.status == event_status)
    if start_at:
        statement = statement.where(AuditEvent.created_at >= start_at)
    if end_at:
        statement = statement.where(AuditEvent.created_at <= end_at)
    return statement


@router.get("/audit", response_model=AuditPage)
def audit_page(
    query: str = "", action: str = "", actor: str = "", resource: str = "", event_status: str = "",
    start_at: datetime | None = None, end_at: datetime | None = None,
    page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("audit.read")),
):
    statement = _audit_statement(principal, query, action, actor, resource, event_status, start_at, end_at)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = list(db.scalars(statement.order_by(AuditEvent.created_at.desc()).offset((page - 1) * page_size).limit(page_size)))
    return AuditPage(items=[AuditEventRead.model_validate(item) for item in items], page=page, page_size=page_size, total=total)


@router.get("/audit/export")
def export_audit(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("audit.read")),
):
    items = list(db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == principal.workspace_id).order_by(AuditEvent.created_at.desc()).limit(10000)))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["created_at", "actor", "action", "resource_type", "resource_id", "status", "details"])
    for item in items:
        writer.writerow([item.created_at.isoformat(), item.actor_email, item.action, item.resource_type, item.resource_id or "", item.status, str(item.details)])
    record_audit(db, principal, action="EXPORT_AUDIT", resource_type="AUDIT", details={"row_count": len(items)})
    db.commit()
    return StreamingResponse(iter([output.getvalue().encode("utf-8-sig")]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=chatbi-audit.csv"})
