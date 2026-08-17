from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.access import ROLE_PERMISSIONS, Principal, require_permission
from app.db.session import get_db
from app.models import AppUser, AuditEvent
from app.schemas.security import AuditEventRead, RoleRead, SecurityOverview, UserRead


router = APIRouter(prefix="/security", tags=["security and audit"])


@router.get("/overview", response_model=SecurityOverview)
def security_overview(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("audit.read")),
):
    users = list(db.scalars(select(AppUser).order_by(AppUser.created_at, AppUser.email)))
    events = list(db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(100)))
    counts = dict(db.execute(select(AppUser.role, func.count(AppUser.id)).group_by(AppUser.role)).all())
    current = next((item for item in users if item.id == principal.user_id), None)
    return SecurityOverview(
        current_actor=UserRead.model_validate(current) if current else None,
        user_count=len(users),
        role_count=len(ROLE_PERMISSIONS),
        active_user_count=sum(item.status == "ACTIVE" for item in users),
        audit_event_count=db.scalar(select(func.count(AuditEvent.id))) or 0,
        users=[UserRead.model_validate(item) for item in users],
        roles=[RoleRead(name=name, permissions=sorted(permissions), user_count=counts.get(name, 0)) for name, permissions in ROLE_PERMISSIONS.items()],
        audit_events=[AuditEventRead.model_validate(item) for item in events],
    )
