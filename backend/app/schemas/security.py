from datetime import datetime
from typing import Literal

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


class PermissionResourceRead(BaseModel):
    resource_type: Literal["DATASOURCE", "SEMANTIC_MODEL", "ANSWER", "DASHBOARD"]
    resource_id: str
    name: str


class ResourcePermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    resource_type: Literal["DATASOURCE", "SEMANTIC_MODEL", "ANSWER", "DASHBOARD"]
    resource_id: str
    can_read: bool
    can_query: bool


class ResourcePermissionUpdate(BaseModel):
    can_read: bool = True
    can_query: bool = False


class SecurityOverview(BaseModel):
    current_actor: UserRead | None
    user_count: int
    role_count: int
    active_user_count: int
    audit_event_count: int
    users: list[UserRead]
    roles: list[RoleRead]
    audit_events: list[AuditEventRead]
    invitations: list["InvitationRead"] = Field(default_factory=list)
    permission_resources: list[PermissionResourceRead] = Field(default_factory=list)
    resource_grants: list[ResourcePermissionRead] = Field(default_factory=list)


class UserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(ADMIN|ANALYST)$")
    status: str | None = Field(default=None, pattern="^(ACTIVE|DISABLED)$")


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    display_name: str = Field(min_length=1, max_length=128)
    role: str = Field(default="ANALYST", pattern="^(ADMIN|ANALYST)$")
    password: str = Field(min_length=10, max_length=512)


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
