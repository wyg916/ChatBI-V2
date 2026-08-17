from fastapi import APIRouter, Depends

from app.core.access import require_permission
from app.core.config import get_settings
from app.query.nl2sql import model_provider_catalog

router = APIRouter(tags=["system"])


@router.get("/version")
def version() -> dict[str, str]:
    settings = get_settings()
    return {"name": settings.app_name, "version": settings.app_version, "environment": settings.environment}


@router.get("/model-providers", dependencies=[Depends(require_permission("settings.read"))])
def model_providers():
    """Return server-side provider status without exposing credentials."""
    return model_provider_catalog()
