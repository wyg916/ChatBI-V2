from __future__ import annotations

import hashlib
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    KnowledgeAcl,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIngestionRun,
    KnowledgeSource,
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

KNOWLEDGE: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "revenue",
        "收入口径与退款处理",
        ("收入", "营收", "销售额", "revenue", "退款", "已支付", "口径"),
    ),
    (
        "profit",
        "利润与成本口径",
        ("利润", "毛利", "成本", "profit", "cost", "口径"),
    ),
    (
        "orders",
        "订单量与有效订单口径",
        ("订单", "订单量", "订单数", "有效订单", "order count", "取消"),
    ),
    (
        "region",
        "区域经营维度说明",
        ("地区", "区域", "省份", "region", "经营区域", "维度"),
    ),
    (
        "time",
        "同比环比与时间窗口",
        ("同比", "环比", "时间", "月份", "季度", "年度", "增长率"),
    ),
    (
        "verification",
        "ChatBI 可验证结果发布规则",
        ("验证", "SQL Guard", "Result Oracle", "引用", "citation", "审计", "只读"),
    ),
)


def seed_v1_runtime(db: Session, workspace_id: str) -> None:
    source = db.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.workspace_id == workspace_id,
            KnowledgeSource.name == "ChatBI V1 Business Glossary",
        )
    )
    if source is None:
        source = KnowledgeSource(
            workspace_id=workspace_id,
            name="ChatBI V1 Business Glossary",
            source_type="CHATBI_AUTHORED",
            status="ACTIVE",
            migration_batch_id=MIGRATION_BATCH,
        )
        db.add(source)
        db.flush()

    created_documents = 0
    for topic, title, keywords in KNOWLEDGE:
        document = db.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.workspace_id == workspace_id,
                KnowledgeDocument.external_id == f"chatbi-v1-{topic}",
            )
        )
        content = _knowledge_content(topic)
        digest = _sha256(content)
        if document is None:
            document = KnowledgeDocument(
                source_id=source.id,
                workspace_id=workspace_id,
                external_id=f"chatbi-v1-{topic}",
                title=title,
                source_path=f"business-glossary/{topic}.md",
                metadata_payload={"topic": topic, "license": "project-authored"},
                migration_batch_id=MIGRATION_BATCH,
            )
            db.add(document)
            db.flush()
            created_documents += 1
        version = db.scalar(
            select(KnowledgeDocumentVersion).where(
                KnowledgeDocumentVersion.document_id == document.id,
                KnowledgeDocumentVersion.version == 1,
            )
        )
        if version is None:
            version = KnowledgeDocumentVersion(
                document_id=document.id,
                version=1,
                status="ACTIVE",
                content_sha256=digest,
                migration_batch_id=MIGRATION_BATCH,
            )
            db.add(version)
            db.flush()
        chunk = db.scalar(
            select(KnowledgeChunk).where(
                KnowledgeChunk.document_version_id == version.id,
                KnowledgeChunk.ordinal == 1,
            )
        )
        if chunk is None:
            db.add(
                KnowledgeChunk(
                    document_version_id=version.id,
                    ordinal=1,
                    content=content,
                    content_sha256=digest,
                    locator={"section": "definition"},
                    metadata_payload={"topic": topic, "keywords": list(keywords)},
                    migration_batch_id=MIGRATION_BATCH,
                )
            )
        acl = db.scalar(
            select(KnowledgeAcl).where(
                KnowledgeAcl.document_version_id == version.id,
                KnowledgeAcl.principal_type == "WORKSPACE",
                KnowledgeAcl.principal_value == workspace_id,
            )
        )
        if acl is None:
            db.add(
                KnowledgeAcl(
                    document_version_id=version.id,
                    principal_type="WORKSPACE",
                    principal_value=workspace_id,
                    permission="READ",
                    migration_batch_id=MIGRATION_BATCH,
                )
            )

    if db.scalar(
        select(KnowledgeIngestionRun.id).where(
            KnowledgeIngestionRun.workspace_id == workspace_id,
            KnowledgeIngestionRun.migration_batch_id == MIGRATION_BATCH,
        )
    ) is None:
        db.add(
            KnowledgeIngestionRun(
                source_id=source.id,
                workspace_id=workspace_id,
                status="SUCCEEDED",
                trace_id=f"SEED-{uuid4()}",
                counts={"documents": len(KNOWLEDGE), "chunks": len(KNOWLEDGE), "created": created_documents},
                migration_batch_id=MIGRATION_BATCH,
            )
        )

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


def _knowledge_content(topic: str) -> str:
    return {
        "revenue": "收入（营收、销售额）按已确认且有效订单的 revenue 求和；取消订单不计入，退款按实际冲减金额扣除。数据结果必须经过 SQL Guard 与 Result Oracle 后发布。",
        "profit": "利润（毛利）等于有效订单收入减订单直接成本，即 SUM(revenue - cost)。成本口径只包含订单直接成本，维度过滤必须与收入一致。",
        "orders": "订单量（订单数）统计有效订单记录数量；取消订单排除，退款订单仍保留订单事实但金额按退款规则处理。去重口径使用 order_id。",
        "region": "区域经营维度使用 regions.region_name，通过 orders.region_id 与 regions.region_id 多对一关联。地区、省份、区域均映射到该受控维度。",
        "time": "同比使用当前时间窗口与上年同期比较；环比使用当前窗口与紧邻上一窗口比较。月、季度和年度边界均按订单日期 order_date 的自然日历计算。",
        "verification": "ChatBI 只发布可验证结果：SQL 必须为单条只读 SELECT 或 WITH SELECT 并通过 SQL Guard；查询值必须通过 Result Oracle；知识结论必须包含通过 ACL 校验的文档版本与 chunk 引用；全部操作保留审计和结果签名。",
    }[topic]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
