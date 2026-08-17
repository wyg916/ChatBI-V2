from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from math import log

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


_WORD = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]+")
_INJECTION = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"忽略.{0,12}(之前|以上|系统).{0,8}(指令|提示)",
        r"(system|developer)\s*prompt",
        r"(绕过|跳过|disable).{0,16}(权限|guard|acl|安全)",
        r"(exfiltrate|reveal).{0,24}(secret|credential|prompt)",
    )
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
) -> tuple[RetrievedChunk, ...]:
    validate_identity(db, identity)
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
    query_tokens = _tokens(query)
    if not query_tokens:
        return ()
    ranked: list[tuple[float, RetrievedChunk]] = []
    for chunk, version, document, source in rows:
        if any(pattern.search(chunk.content) for pattern in _INJECTION):
            continue
        metadata = chunk.metadata_payload or {}
        searchable = " ".join(
            (document.title, chunk.content, " ".join(metadata.get("keywords", [])))
        )
        candidate_tokens = _tokens(searchable)
        overlap = query_tokens.intersection(candidate_tokens)
        if not overlap:
            continue
        coverage = len(overlap) / max(1, len(query_tokens))
        specificity = sum(1.0 + log(1 + len(token)) for token in overlap)
        score = min(1.0, 0.55 * coverage + 0.45 * specificity / (specificity + 4.0))
        locator = chunk.locator or {}
        ranked.append(
            (
                score,
                RetrievedChunk(
                    document_id=document.id,
                    document_version_id=version.id,
                    chunk_id=chunk.id,
                    title=document.title,
                    text=chunk.content,
                    source=f"{source.name}:{document.source_path}",
                    locator=str(locator.get("section") or f"chunk:{chunk.ordinal}"),
                    score=round(score, 6),
                ),
            )
        )
    ranked.sort(key=lambda item: (-item[0], item[1].chunk_id))
    return tuple(item[1] for item in ranked[:limit])


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tokens(text: str) -> frozenset[str]:
    tokens: set[str] = set()
    for raw in _WORD.findall(text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", raw):
            tokens.add(raw)
            tokens.update(raw[index : index + 2] for index in range(max(0, len(raw) - 1)))
        else:
            tokens.add(raw)
    return frozenset(token for token in tokens if token)
