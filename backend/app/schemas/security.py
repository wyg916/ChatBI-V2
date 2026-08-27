from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    invitations: list["InvitationRead"] = []


class UserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(ADMIN|ANALYST)$")
    status: str | None = Field(default=None, pattern="^(ACTIVE|DISABLED)$")


class InvitationCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: str = Field(pattern="^(ADMIN|ANALYST)$")
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime


class InvitationCreated(InvitationRead):
    invite_url: str


class AuditPage(BaseModel):
    items: list[AuditEventRead]
    page: int
    page_size: int
    total: int
