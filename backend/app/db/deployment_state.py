"""Sanitized deployment state for Doctor and backup/restore verification.

The output intentionally excludes passwords, secret hashes, Provider keys,
message bodies, SQL text, and attachment contents. It performs no Provider
network call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.model_gateway.configuration import configured_providers
from app.models import (
    AppUser,
    ChatMessage,
    Conversation,
    Dashboard,
    OrchestrationProfile,
    Project,
    ProviderRuntimeSetting,
    ResourceGrant,
    VerifiedAnswer,
    Workspace,
    WorkspaceInvitation,
    WorkspaceSetting,
)


PROVIDER_IDS = ("mimo", "deepseek", "kimi")


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _rows(db: Session, columns: Iterable[Any], order_column: Any) -> list[list[Any]]:
    statement = select(*columns).order_by(order_column)
    return [[_json_value(value) for value in row] for row in db.execute(statement).all()]


def metadata_snapshot(db: Session, *, migration_head: str | None = None) -> dict[str, Any]:
    """Return non-secret counts plus a stable fingerprint of governed metadata."""

    if migration_head is None:
        migration_head = str(db.scalar(text("SELECT version_num FROM alembic_version")) or "UNKNOWN")

    counts = {
        "workspace": db.scalar(select(func.count()).select_from(Workspace)) or 0,
        "user": db.scalar(select(func.count()).select_from(AppUser)) or 0,
        "rbac_grant": db.scalar(select(func.count()).select_from(ResourceGrant)) or 0,
        "workspace_setting": db.scalar(select(func.count()).select_from(WorkspaceSetting)) or 0,
        "provider_runtime_setting": db.scalar(select(func.count()).select_from(ProviderRuntimeSetting)) or 0,
        "invitation": db.scalar(select(func.count()).select_from(WorkspaceInvitation)) or 0,
        "project": db.scalar(select(func.count()).select_from(Project)) or 0,
        "conversation": db.scalar(select(func.count()).select_from(Conversation)) or 0,
        "chat_message": db.scalar(select(func.count()).select_from(ChatMessage)) or 0,
        "verified_answer": db.scalar(select(func.count()).select_from(VerifiedAnswer)) or 0,
        "dashboard": db.scalar(select(func.count()).select_from(Dashboard)) or 0,
        "orchestration_profile": db.scalar(select(func.count()).select_from(OrchestrationProfile)) or 0,
    }
    identity = {
        "workspace": _rows(db, (Workspace.id, Workspace.name), Workspace.id),
        "user": _rows(
            db,
            (AppUser.id, AppUser.workspace_id, AppUser.email, AppUser.display_name, AppUser.role, AppUser.status),
            AppUser.id,
        ),
        "rbac_grant": _rows(
            db,
            (
                ResourceGrant.id,
                ResourceGrant.user_id,
                ResourceGrant.resource_type,
                ResourceGrant.resource_id,
                ResourceGrant.can_read,
                ResourceGrant.can_query,
            ),
            ResourceGrant.id,
        ),
        "workspace_setting": _rows(
            db,
            (
                WorkspaceSetting.workspace_id,
                WorkspaceSetting.query_security,
                WorkspaceSetting.workspace_config,
                WorkspaceSetting.appearance,
                WorkspaceSetting.version,
            ),
            WorkspaceSetting.workspace_id,
        ),
        "provider_runtime_setting": _rows(
            db,
            (
                ProviderRuntimeSetting.id,
                ProviderRuntimeSetting.workspace_id,
                ProviderRuntimeSetting.provider_id,
                ProviderRuntimeSetting.enabled,
                ProviderRuntimeSetting.healthy,
                ProviderRuntimeSetting.health_message,
                ProviderRuntimeSetting.priority,
                ProviderRuntimeSetting.cost_policy,
            ),
            ProviderRuntimeSetting.id,
        ),
        "invitation": _rows(
            db,
            (
                WorkspaceInvitation.id,
                WorkspaceInvitation.workspace_id,
                WorkspaceInvitation.email,
                WorkspaceInvitation.role,
                WorkspaceInvitation.status,
                WorkspaceInvitation.expires_at,
                WorkspaceInvitation.revoked_at,
                WorkspaceInvitation.accepted_at,
            ),
            WorkspaceInvitation.id,
        ),
        "project": _rows(db, (Project.id, Project.workspace_id, Project.user_id, Project.name), Project.id),
        "conversation": _rows(
            db,
            (Conversation.id, Conversation.workspace_id, Conversation.user_id, Conversation.project_id, Conversation.title),
            Conversation.id,
        ),
        "chat_message": _rows(
            db,
            (ChatMessage.id, ChatMessage.conversation_id, ChatMessage.workspace_id, ChatMessage.role, ChatMessage.status, ChatMessage.route),
            ChatMessage.id,
        ),
        "verified_answer": _rows(
            db,
            (
                VerifiedAnswer.id,
                VerifiedAnswer.workspace_id,
                VerifiedAnswer.status,
                VerifiedAnswer.query_run_id,
                VerifiedAnswer.result_signature,
                VerifiedAnswer.semantic_model_id,
                VerifiedAnswer.datasource_id,
                VerifiedAnswer.oracle_status,
            ),
            VerifiedAnswer.id,
        ),
        "dashboard": _rows(
            db,
            (Dashboard.id, Dashboard.workspace_id, Dashboard.name, Dashboard.status, Dashboard.card_count),
            Dashboard.id,
        ),
        "orchestration_profile": _rows(
            db,
            (
                OrchestrationProfile.id,
                OrchestrationProfile.workspace_id,
                OrchestrationProfile.code,
                OrchestrationProfile.status,
                OrchestrationProfile.allowed_tools,
                OrchestrationProfile.max_steps,
                OrchestrationProfile.max_tool_calls,
            ),
            OrchestrationProfile.id,
        ),
    }
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "migration_head": migration_head,
        "candidate_version": os.getenv("CHATBI_RELEASE_VERSION", get_settings().app_version),
        "git_sha": os.getenv("CHATBI_GIT_SHA", "UNAVAILABLE"),
        "counts": counts,
        "metadata_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "secrets_included": False,
    }


def provider_configuration_state(db: Session) -> list[dict[str, Any]]:
    """Return configured/runtime state without contacting any Provider."""

    configured = configured_providers(get_settings())
    workspace_id = db.scalar(select(Workspace.id).order_by(Workspace.id).limit(1))
    runtime = {
        item.provider_id: item
        for item in db.scalars(
            select(ProviderRuntimeSetting).where(
                ProviderRuntimeSetting.workspace_id == workspace_id,
                ProviderRuntimeSetting.provider_id.in_(PROVIDER_IDS),
            )
        )
    }
    result: list[dict[str, Any]] = []
    for provider_id in PROVIDER_IDS:
        state = runtime.get(provider_id)
        is_configured = provider_id in configured
        enabled = state.enabled if state is not None else is_configured
        if not is_configured:
            health = "CREDENTIAL_MISSING"
            reachability = "NOT_TESTED"
        elif state is None or state.healthy is None:
            health = "NOT_CHECKED"
            reachability = "NOT_TESTED"
        elif state.healthy:
            health = "HEALTHY"
            reachability = "LAST_RECORDED_SUCCESS"
        else:
            health = "UNHEALTHY"
            reachability = "LAST_RECORDED_FAILURE"
        result.append(
            {
                "provider": provider_id,
                "configured": is_configured,
                "enabled": enabled,
                "health": health,
                "reachability": reachability,
            }
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("snapshot", "providers"))
    args = parser.parse_args()
    with SessionLocal() as db:
        payload = metadata_snapshot(db) if args.command == "snapshot" else provider_configuration_state(db)
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
