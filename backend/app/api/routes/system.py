from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.access import Principal, require_permission
from app.core.config import get_settings
from app.db.session import get_db
from app.model_gateway.test_cost_control import TestCostController
from app.schemas.admin import AppearanceSettings, ProviderCatalog, ProviderPatch, ProviderStatus, SettingsPatch, SettingsRead, SystemInformation
from app.services.admin_settings import provider_catalog, read_settings, set_provider_enabled, system_information, test_provider, update_settings

router = APIRouter(tags=["system"])


@router.get("/version")
def version() -> dict[str, str]:
    settings = get_settings()
    return {"name": settings.app_name, "version": settings.app_version, "environment": settings.environment}


@router.get("/model-providers", response_model=ProviderCatalog)
def model_providers(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.read")),
):
    """Return server-side provider status without exposing credentials."""
    return provider_catalog(db, principal)


@router.post("/model-providers/{provider_id}/test", response_model=ProviderStatus)
def test_model_provider(
    provider_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.manage")),
):
    try:
        result = test_provider(db, principal, provider_id)
        if not result.healthy:
            raise RuntimeError(result.health_message)
        return result
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/model-providers/{provider_id}", response_model=ProviderStatus)
def update_model_provider(
    provider_id: str,
    payload: ProviderPatch,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.manage")),
):
    try:
        return set_provider_enabled(db, principal, provider_id, payload.enabled)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/settings", response_model=SettingsRead)
def get_workspace_settings(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.read")),
):
    return read_settings(db, principal)


@router.get("/appearance", response_model=AppearanceSettings)
def get_workspace_appearance(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("workspace.read")),
):
    return read_settings(db, principal).appearance


@router.patch("/settings", response_model=SettingsRead)
def patch_workspace_settings(
    payload: SettingsPatch,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.manage")),
):
    try:
        return update_settings(db, principal, payload)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/system-information", response_model=SystemInformation)
def get_system_information(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("settings.read")),
):
    return system_information(db, principal)


@router.get("/test-cost-control-status", dependencies=[Depends(require_permission("settings.read"))])
def test_cost_control_status() -> dict:
    """Return the served process identity required by paid-test preflight."""

    return TestCostController().runtime_identity()
