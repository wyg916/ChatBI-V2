from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    display_name: str
    role: str
    status: str
    last_active_at: datetime | None = None


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    actor_email: str
    action: str
    resource_type: str
    resource_id: str | None = None
    status: str
    details: dict
    created_at: datetime


class RoleRead(BaseModel):
    name: str
    permissions: list[str]
    user_count: int


class SecurityOverview(BaseModel):
    current_actor: UserRead | None
    user_count: int
    role_count: int
    active_user_count: int
    audit_event_count: int
    users: list[UserRead]
    roles: list[RoleRead]
    audit_events: list[AuditEventRead]
