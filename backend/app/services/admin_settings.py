from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.access import Principal, record_audit
from app.core.config import get_settings
from app.model_gateway import ModelGateway, RequestContext
from app.model_gateway.configuration import PROVIDER_DEFINITIONS, configured_providers, load_control_config
from app.model_gateway.ledger import bind_model_invocation_session
from app.models import (
    AppUser, DataSource, ProviderRuntimeSetting, SemanticModel, Workspace,
    WorkspaceSetting,
)
from app.schemas.admin import (
    AppearanceSettings, ProviderCatalog, ProviderStatus, QuerySecuritySettings,
    SettingsPatch, SettingsRead, SystemInformation, WorkspaceConfigSettings,
    WorkspaceSummary,
)


def _defaults(workspace: Workspace) -> tuple[dict, dict, dict]:
    settings = get_settings()
    return (
        QuerySecuritySettings(
            query_timeout_ms=settings.query_timeout_ms,
            max_rows=settings.query_row_limit,
        ).model_dump(),
        WorkspaceConfigSettings(workspace_name=workspace.name).model_dump(),
        AppearanceSettings().model_dump(),
    )


def _setting(db: Session, workspace: Workspace, *, create: bool = False) -> WorkspaceSetting | None:
    row = db.get(WorkspaceSetting, workspace.id)
    if row is None and create:
        query, workspace_config, appearance = _defaults(workspace)
        row = WorkspaceSetting(
            workspace_id=workspace.id, query_security=query,
            workspace_config=workspace_config, appearance=appearance,
        )
        db.add(row)
        db.flush()
    return row


def read_settings(db: Session, principal: Principal) -> SettingsRead:
    workspace = db.get(Workspace, principal.workspace_id)
    if workspace is None:
        raise LookupError("Workspace is unavailable")
    row = _setting(db, workspace)
    query, workspace_config, appearance = _defaults(workspace)
    if row is not None:
        query.update(row.query_security or {})
        workspace_config.update(row.workspace_config or {})
        appearance.update(row.appearance or {})
    workspace_config["workspace_name"] = workspace.name
    roles = dict(db.execute(
        select(AppUser.role, func.count(AppUser.id))
        .where(AppUser.workspace_id == workspace.id)
        .group_by(AppUser.role)
    ).all())
    datasources = list(db.scalars(select(DataSource).where(DataSource.workspace_id == workspace.id).order_by(DataSource.name)))
    semantic_models = list(db.scalars(select(SemanticModel).where(SemanticModel.workspace_id == workspace.id).order_by(SemanticModel.name)))
    return SettingsRead(
        query_security=QuerySecuritySettings.model_validate(query),
        workspace=WorkspaceConfigSettings.model_validate(workspace_config),
        appearance=AppearanceSettings.model_validate(appearance),
        workspace_summary=WorkspaceSummary(
            id=workspace.id, name=workspace.name, member_count=sum(roles.values()), roles=roles,
            status=workspace_config.get("status", "ACTIVE"),
            isolation="WORKSPACE_ID + BACKEND_RBAC",
            datasources=[{"id": item.id, "name": item.name, "status": item.status} for item in datasources],
            semantic_models=[{"id": item.id, "name": item.name, "status": item.status, "datasource_id": item.datasource_id} for item in semantic_models],
        ),
        version=row.version if row else 1,
        updated_at=row.updated_at if row else None,
    )


def update_settings(db: Session, principal: Principal, patch: SettingsPatch) -> SettingsRead:
    workspace = db.get(Workspace, principal.workspace_id)
    if workspace is None:
        raise LookupError("Workspace is unavailable")
    row = _setting(db, workspace, create=True)
    assert row is not None
    if patch.expected_version is not None and patch.expected_version != row.version:
        raise ValueError("SETTINGS_VERSION_CONFLICT")
    changed: list[str] = []
    if patch.query_security is not None:
        row.query_security = patch.query_security.model_dump()
        changed.append("query_security")
    if patch.workspace is not None:
        payload = patch.workspace.model_dump()
        for key, model_class in (("default_datasource_id", DataSource), ("default_semantic_model_id", SemanticModel)):
            resource_id = payload.get(key)
            if resource_id:
                resource = db.get(model_class, resource_id)
                if resource is None or resource.workspace_id != workspace.id:
                    raise ValueError(f"INVALID_{key.upper()}")
        workspace.name = patch.workspace.workspace_name
        row.workspace_config = payload
        changed.append("workspace")
    if patch.appearance is not None:
        row.appearance = patch.appearance.model_dump()
        changed.append("appearance")
    if not changed:
        raise ValueError("NO_SETTINGS_CHANGES")
    row.version += 1
    row.updated_by = principal.user_id
    record_audit(
        db, principal, action="UPDATE_SETTINGS", resource_type="WORKSPACE",
        resource_id=workspace.id, details={"sections": changed, "version": row.version},
    )
    db.commit()
    return read_settings(db, principal)


def _provider_error(exc: Exception) -> tuple[str, str]:
    message = str(exc)
    lowered = message.lower()
    if "401" in lowered or "403" in lowered or "auth" in lowered:
        return "AUTH_FAILED", "Provider rejected the server credential"
    if "404" in lowered or "model" in lowered and "not found" in lowered:
        return "MODEL_NOT_FOUND", "Configured model was not found"
    if any(token in lowered for token in ("connect", "dns", "timeout", "unreachable")):
        return "ENDPOINT_UNREACHABLE", "Provider endpoint is unreachable"
    return "PROVIDER_CHECK_FAILED", message[:200]


def provider_catalog(db: Session, principal: Principal) -> ProviderCatalog:
    settings = get_settings()
    configured = configured_providers(settings)
    runtime = {
        item.provider_id: item
        for item in db.scalars(select(ProviderRuntimeSetting).where(ProviderRuntimeSetting.workspace_id == principal.workspace_id))
    }
    capabilities = load_control_config("model_capabilities.yaml")["providers"]
    policy = load_control_config("model_policy.yaml")
    order: list[str] = []
    for values in policy["provider_order"].values():
        for provider_id in values:
            if provider_id not in order:
                order.append(provider_id)
    definitions = {item.provider_id: item for item in PROVIDER_DEFINITIONS}
    items: list[ProviderStatus] = []
    for provider_id in ["mimo", "deepseek", "kimi", "openai-compatible"]:
        definition = definitions[provider_id]
        resolved = configured.get(provider_id)
        state = runtime.get(provider_id)
        is_configured = resolved is not None
        enabled = state.enabled if state is not None else is_configured
        items.append(ProviderStatus(
            id=provider_id, provider_id=provider_id, model_id=resolved.model_name if resolved else None,
            model_name=resolved.model_name if resolved else None,
            display_name=definition.display_name, configured=is_configured, enabled=enabled,
            active=False,
            healthy=state.healthy if state else None,
            health_message=state.health_message if state and state.health_message else ("NOT_CHECKED" if is_configured else "CREDENTIAL_MISSING"),
            last_checked_at=state.last_checked_at if state else None,
            capabilities=list((capabilities.get(provider_id) or {}).get("capabilities") or []),
            priority=(order.index(provider_id) + 1) if provider_id in order else 100,
            cost_policy="PREMIUM" if provider_id == "kimi" else "STANDARD",
            credential_source="SERVER_ENVIRONMENT", protocol="openai-chat-completions", external_model=True,
        ))
    items.append(ProviderStatus(
        id="deterministic", provider_id="deterministic", model_id="deterministic-semantic-v1",
        model_name="deterministic-semantic-v1", display_name="Local Semantic Runtime",
        configured=True, enabled=True, active=False, healthy=True, health_message="LOCAL_READY", last_checked_at=None,
        capabilities=["semantic_fallback"], priority=999, cost_policy="FREE",
        credential_source="NOT_REQUIRED", protocol="local", external_model=False,
    ))
    active = next((item.provider_id for item in sorted(items, key=lambda item: item.priority) if item.enabled and item.configured), "deterministic")
    items = [item.model_copy(update={"active": item.provider_id == active}) for item in items]
    return ProviderCatalog(active_provider=active, selection_strategy="capability-complexity-cost", items=items)


def test_provider(db: Session, principal: Principal, provider_id: str) -> ProviderStatus:
    if provider_id not in {"mimo", "deepseek", "kimi", "openai-compatible"}:
        raise ValueError("UNKNOWN_PROVIDER")
    configured = configured_providers(get_settings())
    if provider_id not in configured:
        raise RuntimeError("CREDENTIAL_MISSING")
    state = db.scalar(select(ProviderRuntimeSetting).where(
        ProviderRuntimeSetting.workspace_id == principal.workspace_id,
        ProviderRuntimeSetting.provider_id == provider_id,
    ))
    if state is None:
        # A connectivity check is observational.  On the first check preserve
        # the catalog's configured-by-default routing state instead of letting
        # the model default (False) silently disable the provider.
        state = ProviderRuntimeSetting(
            workspace_id=principal.workspace_id,
            provider_id=provider_id,
            enabled=True,
        )
        db.add(state)
    now = datetime.now(timezone.utc)
    try:
        context = RequestContext(
            request_id=f"MODEL-PROBE-{uuid4()}", trace_id=f"TRACE-MODEL-PROBE-{uuid4()}",
            question="health probe", user_id=principal.user_id or principal.email,
            workspace_id=principal.workspace_id or "SYSTEM", roles=frozenset({principal.role}), route="MODEL_HEALTH",
        )
        with bind_model_invocation_session(db):
            ModelGateway(
                provider_overrides={provider_id: configured[provider_id]}, respect_runtime_enabled=False,
            ).probe(provider_id, context=context)
        state.healthy = True
        state.health_message = "HEALTHY"
        audit_status = "SUCCESS"
    except Exception as exc:
        code, message = _provider_error(exc)
        state.healthy = False
        state.health_message = f"{code}: {message}"
        audit_status = "FAILED"
    state.last_checked_at = now
    state.updated_by = principal.user_id
    record_audit(db, principal, action="TEST_MODEL", resource_type="MODEL_PROVIDER", resource_id=provider_id, status=audit_status, details={"healthy": state.healthy, "code": state.health_message.split(":", 1)[0]})
    db.commit()
    return next(item for item in provider_catalog(db, principal).items if item.provider_id == provider_id)


def set_provider_enabled(db: Session, principal: Principal, provider_id: str, enabled: bool) -> ProviderStatus:
    if enabled:
        if provider_id not in {definition.provider_id for definition in PROVIDER_DEFINITIONS}:
            raise ValueError("UNKNOWN_PROVIDER")
        if provider_id not in configured_providers(get_settings()):
            raise RuntimeError("CREDENTIAL_MISSING")
    state = db.scalar(select(ProviderRuntimeSetting).where(
        ProviderRuntimeSetting.workspace_id == principal.workspace_id,
        ProviderRuntimeSetting.provider_id == provider_id,
    ))
    if state is None:
        state = ProviderRuntimeSetting(workspace_id=principal.workspace_id, provider_id=provider_id)
        db.add(state)
    state.enabled = enabled
    state.updated_by = principal.user_id
    record_audit(db, principal, action="TOGGLE_MODEL", resource_type="MODEL_PROVIDER", resource_id=provider_id, details={"enabled": enabled})
    db.commit()
    return next(item for item in provider_catalog(db, principal).items if item.provider_id == provider_id)


def _remote_health(url: str, path: str = "/health") -> str:
    try:
        response = httpx.get(url.rstrip("/") + path, timeout=0.8)
        return "HEALTHY" if response.is_success else f"HTTP_{response.status_code}"
    except httpx.HTTPError:
        return "UNREACHABLE"


def system_information(db: Session, principal: Principal) -> SystemInformation:
    settings = get_settings()
    try:
        db.execute(text("SELECT 1"))
        database_status = "HEALTHY"
    except Exception:
        database_status = "UNHEALTHY"
    try:
        migration_head = str(db.scalar(text("SELECT version_num FROM alembic_version")) or "UNKNOWN")
    except Exception:
        migration_head = "UNAVAILABLE"
    catalog = provider_catalog(db, principal)
    gateway = "READY" if any(item.configured and item.enabled for item in catalog.items) else "NO_PROVIDER"
    return SystemInformation(
        app_version=settings.app_version,
        git_sha=os.getenv("CHATBI_GIT_SHA", "UNAVAILABLE"),
        release_version=os.getenv("CHATBI_RELEASE_VERSION", settings.app_version),
        backend_health="HEALTHY",
        frontend_build=os.getenv("CHATBI_FRONTEND_BUILD", "UNAVAILABLE"),
        database_status=database_status,
        migration_head=migration_head,
        rag_status=_remote_health(settings.legacy_rag_base_url),
        sandbox_status=_remote_health(settings.sandbox_controller_url, "/healthz"),
        model_gateway_status=gateway,
    )
