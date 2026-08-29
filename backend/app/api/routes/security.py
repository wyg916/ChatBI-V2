import csv
import io
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.access import ROLE_PERMISSIONS, Principal, record_audit, require_permission
from app.core.auth import hash_password, token_digest
from app.db.session import get_db
from app.models import (
    AppUser, AuditEvent, Dashboard, DataSource, ResourceGrant, SemanticModel,
    VerifiedAnswer, WorkspaceInvitation,
)
from app.schemas.security import (
    AuditEventRead, AuditPage, InvitationCreate, InvitationCreated, InvitationRead,
    PermissionResourceRead, ResourcePermissionRead, ResourcePermissionUpdate,
    RoleRead, SecurityOverview, UserCreate, UserRead, UserUpdate,
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
    permission_resources = [
        PermissionResourceRead(resource_type="DATASOURCE", resource_id=item.id, name=item.name)
        for item in db.scalars(
            select(DataSource).where(DataSource.workspace_id == principal.workspace_id).order_by(DataSource.name)
        )
    ] + [
        PermissionResourceRead(resource_type="SEMANTIC_MODEL", resource_id=item.id, name=item.name)
        for item in db.scalars(
            select(SemanticModel).where(SemanticModel.workspace_id == principal.workspace_id).order_by(SemanticModel.name)
        )
    ] + [
        PermissionResourceRead(resource_type="ANSWER", resource_id=item.id, name=item.question)
        for item in db.scalars(
            select(VerifiedAnswer)
            .where(VerifiedAnswer.workspace_id == principal.workspace_id)
            .order_by(VerifiedAnswer.question, VerifiedAnswer.id)
        )
    ] + [
        PermissionResourceRead(resource_type="DASHBOARD", resource_id=item.id, name=item.name)
        for item in db.scalars(
            select(Dashboard).where(Dashboard.workspace_id == principal.workspace_id).order_by(Dashboard.name)
        )
    ]
    workspace_user_ids = select(AppUser.id).where(AppUser.workspace_id == principal.workspace_id)
    resource_grants = list(db.scalars(
        select(ResourceGrant)
        .where(ResourceGrant.user_id.in_(workspace_user_ids))
        .order_by(ResourceGrant.user_id, ResourceGrant.resource_type, ResourceGrant.resource_id)
    ))
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
        permission_resources=permission_resources,
        resource_grants=[ResourcePermissionRead.model_validate(item) for item in resource_grants],
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


def _permission_resource(
    db: Session, principal: Principal, resource_type: str, resource_id: str,
) -> DataSource | SemanticModel | VerifiedAnswer | Dashboard:
    resource_class = {
        "DATASOURCE": DataSource,
        "SEMANTIC_MODEL": SemanticModel,
        "ANSWER": VerifiedAnswer,
        "DASHBOARD": Dashboard,
    }.get(resource_type)
    if resource_class is None:
        raise HTTPException(status_code=422, detail="RESOURCE_TYPE_NOT_MANAGEABLE")
    resource = db.get(resource_class, resource_id)
    if resource is None or resource.workspace_id != principal.workspace_id:
        raise HTTPException(status_code=404, detail="Permission resource not found")
    return resource


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.manage")),
):
    email = payload.email.strip().lower()
    display_name = payload.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=422, detail="Display name cannot be blank")
    if db.scalar(select(AppUser.id).where(func.lower(AppUser.email) == email)):
        raise HTTPException(status_code=409, detail="USER_ALREADY_EXISTS")
    now = datetime.now(timezone.utc)
    user = AppUser(
        workspace_id=principal.workspace_id,
        email=email,
        display_name=display_name,
        role=payload.role,
        status="ACTIVE",
        password_hash=hash_password(payload.password),
        password_changed_at=now,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="USER_ALREADY_EXISTS") from exc
    record_audit(
        db,
        principal,
        action="CREATE_MEMBER",
        resource_type="USER",
        resource_id=user.id,
        details={"email": email, "display_name": display_name, "role": payload.role},
    )
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


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


@router.get("/users/{user_id}/resource-permissions", response_model=list[ResourcePermissionRead])
def list_resource_permissions(
    user_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.manage")),
):
    user = _workspace_user(db, principal, user_id)
    return list(db.scalars(
        select(ResourceGrant)
        .where(ResourceGrant.user_id == user.id)
        .order_by(ResourceGrant.resource_type, ResourceGrant.resource_id)
    ))


@router.put(
    "/users/{user_id}/resource-permissions/{resource_type}/{resource_id}",
    response_model=ResourcePermissionRead,
)
def set_resource_permission(
    user_id: str,
    resource_type: str,
    resource_id: str,
    payload: ResourcePermissionUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.manage")),
):
    user = _workspace_user(db, principal, user_id)
    normalized_type = resource_type.upper()
    resource = _permission_resource(db, principal, normalized_type, resource_id)
    if user.role == "ADMIN":
        raise HTTPException(status_code=409, detail="ADMIN_HAS_IMPLICIT_RESOURCE_ACCESS")
    if payload.can_query and not payload.can_read:
        raise HTTPException(status_code=422, detail="QUERY_PERMISSION_REQUIRES_READ")
    if not payload.can_read and not payload.can_query:
        raise HTTPException(status_code=422, detail="USE_DELETE_TO_REVOKE_PERMISSION")
    grant = db.scalar(select(ResourceGrant).where(
        ResourceGrant.user_id == user.id,
        ResourceGrant.resource_type == normalized_type,
        ResourceGrant.resource_id == resource.id,
    ))
    if grant is None:
        grant = ResourceGrant(
            user_id=user.id,
            resource_type=normalized_type,
            resource_id=resource.id,
        )
        db.add(grant)
    grant.can_read = payload.can_read
    grant.can_query = payload.can_query
    db.flush()
    record_audit(
        db,
        principal,
        action="SET_RESOURCE_PERMISSION",
        resource_type=normalized_type,
        resource_id=resource.id,
        details={
            "target_user_id": user.id,
            "can_read": grant.can_read,
            "can_query": grant.can_query,
        },
    )
    db.commit()
    db.refresh(grant)
    return ResourcePermissionRead.model_validate(grant)


@router.delete(
    "/users/{user_id}/resource-permissions/{resource_type}/{resource_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_resource_permission(
    user_id: str,
    resource_type: str,
    resource_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.manage")),
):
    user = _workspace_user(db, principal, user_id)
    normalized_type = resource_type.upper()
    resource = _permission_resource(db, principal, normalized_type, resource_id)
    if user.role == "ADMIN":
        raise HTTPException(status_code=409, detail="ADMIN_HAS_IMPLICIT_RESOURCE_ACCESS")
    grant = db.scalar(select(ResourceGrant).where(
        ResourceGrant.user_id == user.id,
        ResourceGrant.resource_type == normalized_type,
        ResourceGrant.resource_id == resource.id,
    ))
    if grant is not None:
        db.delete(grant)
    record_audit(
        db,
        principal,
        action="REVOKE_RESOURCE_PERMISSION",
        resource_type=normalized_type,
        resource_id=resource.id,
        details={"target_user_id": user.id},
    )
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
