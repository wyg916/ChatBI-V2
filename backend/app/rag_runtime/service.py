from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.models import (
    AppUser,
    KnowledgeAcl,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeSource,
    Workspace,
)
from app.rag_runtime.legacy_selected_source import (
    LegacyCandidate,
    RETRIEVAL_MODE,
    prompt_injection_detected,
    rank_candidates as legacy_rank_candidates,
)



class IdentityDenied(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeIdentity:
    workspace_id: str
    user_id: str
    roles: frozenset[str]


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: str
    document_version_id: str
    chunk_id: str
    title: str
    text: str
    source: str
    locator: str
    score: float


def validate_identity(db: Session, identity: RuntimeIdentity) -> None:
    if db.get(Workspace, identity.workspace_id) is None:
        raise IdentityDenied("UNKNOWN_WORKSPACE")
    user = db.scalar(
        select(AppUser).where(
            AppUser.id == identity.user_id,
            AppUser.workspace_id == identity.workspace_id,
            AppUser.status == "ACTIVE",
        )
    )
    if user is None:
        raise IdentityDenied("UNKNOWN_WORKSPACE_USER")
    if user.role not in identity.roles:
        raise IdentityDenied("ROLE_IDENTITY_MISMATCH")


def retrieve(
    db: Session,
    *,
    query: str,
    identity: RuntimeIdentity,
    limit: int,
    scenario_id: str = "charging_ops",
) -> tuple[RetrievedChunk, ...]:
    validate_identity(db, identity)
    # A malicious request must not be allowed to use even otherwise legitimate
    # governed evidence as fuel for prompt injection. Fail closed before any
    # retrieval run or ranking is performed.
    if prompt_injection_detected(query):
        return ()
    canonical_scenario_id = "charging_ops" if scenario_id in {"chatbi-v1", "charging_ops"} else scenario_id
    acl_predicates = [
        (KnowledgeAcl.principal_type == "WORKSPACE")
        & (KnowledgeAcl.principal_value == identity.workspace_id),
        (KnowledgeAcl.principal_type == "USER")
        & (KnowledgeAcl.principal_value == identity.user_id),
    ]
    if identity.roles:
        acl_predicates.append(
            (KnowledgeAcl.principal_type == "ROLE")
            & KnowledgeAcl.principal_value.in_(tuple(identity.roles))
        )
    rows = db.execute(
        select(
            KnowledgeChunk,
            KnowledgeDocumentVersion,
            KnowledgeDocument,
            KnowledgeSource,
        )
        .join(
            KnowledgeDocumentVersion,
            KnowledgeDocumentVersion.id == KnowledgeChunk.document_version_id,
        )
        .join(
            KnowledgeDocument,
            KnowledgeDocument.id == KnowledgeDocumentVersion.document_id,
        )
        .join(KnowledgeSource, KnowledgeSource.id == KnowledgeDocument.source_id)
        .where(
            KnowledgeDocument.workspace_id == identity.workspace_id,
            KnowledgeDocumentVersion.status == "ACTIVE",
            KnowledgeSource.status == "ACTIVE",
            exists(
                select(KnowledgeAcl.id).where(
                    KnowledgeAcl.document_version_id == KnowledgeDocumentVersion.id,
                    KnowledgeAcl.permission == "READ",
                    or_(*acl_predicates),
                )
            ),
        )
    ).all()
    candidates: list[LegacyCandidate] = []
    for chunk, version, document, source in rows:
        if prompt_injection_detected(chunk.content):
            continue
        document_metadata = document.metadata_payload or {}
        if str(document_metadata.get("scenario_id") or "charging_ops") != canonical_scenario_id:
            continue
        metadata = chunk.metadata_payload or {}
        locator = chunk.locator or {}
        candidates.append(LegacyCandidate(
            document_id=document.id,
            document_version_id=version.id,
            chunk_id=chunk.id,
            title=document.title,
            content=chunk.content,
            source_path=document.source_path,
            source=f"{source.name}:{document.source_path}",
            locator=str(locator.get("section") or f"chunk:{chunk.ordinal}"),
            ordinal=chunk.ordinal,
            section=str(locator.get("section") or metadata.get("section") or "") or None,
            content_sha256=chunk.content_sha256,
        ))
    if not candidates:
        return ()
    ranked = legacy_rank_candidates(query, candidates, limit=limit)
    return tuple(
        RetrievedChunk(
            document_id=item.candidate.document_id,
            document_version_id=item.candidate.document_version_id,
            chunk_id=item.candidate.chunk_id,
            title=item.candidate.title,
            text=item.candidate.content,
            source=item.candidate.source,
            locator=item.candidate.locator,
            score=item.score,
        )
        for item in ranked
    )


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
