from fastapi import APIRouter, Depends

from app.core.access import require_permission
from app.core.config import get_settings
from chatbi_agent_contracts import AgentRole, ToolName
from chatbi_rag_adapter import LiveRagAdapter
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


@router.get("/query-capabilities", dependencies=[Depends(require_permission("query.ask"))])
def query_capabilities():
    settings = get_settings()
    rag = LiveRagAdapter(
        base_url=settings.legacy_rag_base_url,
        shared_secret=settings.rag_shared_secret.get_secret_value(),
        retry_count=settings.rag_retry_count,
    )
    return {
        "routes": ["DATA_QUERY", "KNOWLEDGE_QUERY", "HYBRID_ANALYSIS", "COMPLEX_ANALYSIS"],
        "rag": {
            "mode": settings.rag_mode,
            "live_bridge": rag.health(timeout_ms=settings.rag_health_timeout_ms),
            "workspace_identity_signed": bool(settings.rag_shared_secret.get_secret_value()),
            "fail_closed": True,
        },
        "multi_agent": {
            "mode": settings.agent_mode,
            "roles": [role.value for role in AgentRole],
            "tools": [tool.value for tool in ToolName],
            "budgets": {
                "max_steps": settings.agent_max_steps,
                "max_tool_calls": settings.agent_max_tool_calls,
                "max_replan": settings.agent_max_replan,
                "max_agent_depth": settings.agent_max_depth,
                "timeout_ms": settings.agent_timeout_ms,
            },
        },
    }
