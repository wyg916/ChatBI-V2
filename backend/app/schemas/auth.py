from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^\s@]+@[^\s@]+$")
    password: str = Field(min_length=1, max_length=512)
    remember: bool = False


class SessionUser(BaseModel):
    id: str
    workspace_id: str
    email: str
    display_name: str
    role: str


class SessionResponse(BaseModel):
    authenticated: bool
    user: SessionUser
    expires_at: str
