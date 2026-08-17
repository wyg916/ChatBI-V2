from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.access import Principal, get_principal, record_audit
from app.core.auth import new_session_token, token_digest, verify_password
from app.core.config import get_settings
from app.db.session import get_db
from app.models import AppUser, AuthSession, LoginAttempt
from app.schemas.auth import LoginRequest, SessionResponse, SessionUser


router = APIRouter(prefix="/auth", tags=["authentication"])


def _fingerprint(value: str) -> str:
    key = get_settings().datasource_secret_key.encode("utf-8") or b"chatbi-auth"
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _session_payload(user: AppUser, expires_at: datetime) -> SessionResponse:
    return SessionResponse(
        authenticated=True,
        user=SessionUser(
            id=user.id,
            workspace_id=user.workspace_id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
        ),
        expires_at=expires_at.isoformat(),
    )


@router.post("/login", response_model=SessionResponse)
def login(data: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> SessionResponse:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    identity = data.email.strip().lower()
    identity_hash = _fingerprint(identity)
    ip_hash = _fingerprint(_client_ip(request))
    window_start = now - timedelta(minutes=settings.login_window_minutes)
    failures = db.scalar(select(func.count(LoginAttempt.id)).where(
        LoginAttempt.identity_hash == identity_hash,
        LoginAttempt.client_ip_hash == ip_hash,
        LoginAttempt.succeeded.is_(False),
        LoginAttempt.created_at >= window_start,
    )) or 0
    if failures >= settings.login_max_failures:
        raise HTTPException(status_code=429, detail="Too many login attempts")

    user = db.scalar(select(AppUser).where(func.lower(AppUser.email) == identity))
    succeeded = bool(user and user.status == "ACTIVE" and verify_password(data.password, user.password_hash))
    db.add(LoginAttempt(identity_hash=identity_hash, client_ip_hash=ip_hash, succeeded=succeeded, created_at=now))
    if not succeeded or user is None:
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = new_session_token()
    ttl = timedelta(days=settings.remember_session_ttl_days) if data.remember else timedelta(minutes=settings.session_ttl_minutes)
    expires_at = now + ttl
    session = AuthSession(
        user_id=user.id,
        workspace_id=user.workspace_id,
        token_hash=token_digest(token),
        expires_at=expires_at,
        last_seen_at=now,
        created_at=now,
        user_agent=(request.headers.get("user-agent") or "")[:512],
        client_ip_hash=ip_hash,
    )
    db.add(session)
    principal = Principal(user.id, user.workspace_id, user.email, user.display_name, user.role)
    record_audit(db, principal, action="LOGIN", resource_type="AUTH_SESSION", resource_id=session.id)
    db.commit()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=int(ttl.total_seconds()),
        expires=expires_at,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return _session_payload(user, expires_at)


@router.get("/me", response_model=SessionResponse)
def me(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> SessionResponse:
    user = db.get(AppUser, principal.user_id)
    if user is None or principal.session_expires_at is None:
        raise HTTPException(status_code=401, detail="Invalid session")
    return _session_payload(user, principal.session_expires_at)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Response:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if token:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(token)))
        if session and session.user_id == principal.user_id:
            session.revoked_at = datetime.now(timezone.utc)
            record_audit(db, principal, action="LOGOUT", resource_type="AUTH_SESSION", resource_id=session.id)
            db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/", samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
