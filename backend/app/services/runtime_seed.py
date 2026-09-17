from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    OrchestrationProfile,
    PromptTemplate,
    PromptVersion,
    ToolBinding,
)


MIGRATION_BATCH = "CHATBI-V1-RAG-MULTIAGENT"
V1_TOOLS = (
    "QUERY_DATA",
    "RETRIEVE_KNOWLEDGE",
    "VERIFY_RESULT",
    "VERIFY_CITATION",
    "GENERATE_CHART",
    "GENERATE_INSIGHT",
)

PROMPTS: dict[str, tuple[str, str]] = {
    "rag.query_rewrite": (
        "Normalize the business question into metric, dimension, time, filter and glossary terms. Never add facts.",
        "RAG query normalization",
    ),
    "rag.citation": (
        "Return only claims supported by authorized citation chunks and preserve document, version and chunk identity.",
        "Citation-grounded knowledge response",
    ),
    "analysis.hybrid": (
        "Combine only Result Oracle-passed data evidence with citation-verified knowledge evidence. Mark missing evidence.",
        "Verified data and knowledge fusion",
    ),
    "agent.planner": (
        "Use the fixed ChatBI V1 role plan and approved six-tool catalogue within configured budgets. Do not expose reasoning.",
        "Bounded orchestration planning",
    ),
    "agent.verification": (
        "Publish data only after SQL Guard and Result Oracle pass; publish knowledge only after citation verification.",
        "Result and citation verification",
    ),
    "agent.insight": (
        "Generate a concise business conclusion from verified evidence only, followed by chart and trace references.",
        "Verified business insight",
    ),
}

def seed_v1_runtime(db: Session, workspace_id: str) -> None:
    profile = db.scalar(
        select(OrchestrationProfile).where(
            OrchestrationProfile.workspace_id == workspace_id,
            OrchestrationProfile.code == "chatbi-v1-complex-analysis",
        )
    )
    if profile is None:
        profile = OrchestrationProfile(
            workspace_id=workspace_id,
            code="chatbi-v1-complex-analysis",
            status="ACTIVE",
            allowed_tools=list(V1_TOOLS),
            max_steps=8,
            max_tool_calls=12,
            max_replan=2,
            max_agent_depth=2,
            timeout_ms=30000,
            token_budget=6000,
            migration_batch_id=MIGRATION_BATCH,
        )
        db.add(profile)
        db.flush()
    for tool in V1_TOOLS:
        if db.scalar(
            select(ToolBinding.id).where(
                ToolBinding.orchestration_profile_id == profile.id,
                ToolBinding.tool_name == tool,
            )
        ) is None:
            db.add(
                ToolBinding(
                    orchestration_profile_id=profile.id,
                    tool_name=tool,
                    enabled=True,
                    configuration={"network_access": False, "direct_db_access": False},
                    migration_batch_id=MIGRATION_BATCH,
                )
            )

    for code, (content, purpose) in PROMPTS.items():
        template = db.scalar(
            select(PromptTemplate).where(
                PromptTemplate.workspace_id == workspace_id,
                PromptTemplate.code == code,
            )
        )
        if template is None:
            template = PromptTemplate(
                workspace_id=workspace_id,
                code=code,
                purpose=purpose,
                status="ACTIVE",
                migration_batch_id=MIGRATION_BATCH,
            )
            db.add(template)
            db.flush()
        version = db.scalar(
            select(PromptVersion).where(
                PromptVersion.prompt_template_id == template.id,
                PromptVersion.version == 1,
            )
        )
        if version is None:
            db.add(
                PromptVersion(
                    prompt_template_id=template.id,
                    version=1,
                    status="ACTIVE",
                    content=content,
                    source="CHATBI_V1_REIMPLEMENTED",
                    checksum_sha256=_sha256(content),
                    source_commit=None,
                    migration_batch_id=MIGRATION_BATCH,
                )
            )
    db.commit()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
