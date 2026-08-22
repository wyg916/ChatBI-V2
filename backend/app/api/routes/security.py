from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.access import ROLE_PERMISSIONS, Principal, require_permission
from app.db.session import get_db
from app.models import AppUser, AuditEvent
from app.schemas.security import AuditEventRead, RoleRead, SecurityOverview, UserRead


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
    events = list(db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == principal.workspace_id).order_by(AuditEvent.created_at.desc()).limit(100)))
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
    )
