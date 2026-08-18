from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from collections import Counter
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
    scenario_id: str = "charging_ops",
) -> tuple[RetrievedChunk, ...]:
    validate_identity(db, identity)
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
    query_tokens = _tokens(query)
    if not query_tokens:
        return ()
    candidates: list[tuple[RetrievedChunk, frozenset[str], Counter[str]]] = []
    for chunk, version, document, source in rows:
        if any(pattern.search(chunk.content) for pattern in _INJECTION):
            continue
        document_metadata = document.metadata_payload or {}
        if str(document_metadata.get("scenario_id") or "charging_ops") != canonical_scenario_id:
            continue
        metadata = chunk.metadata_payload or {}
        searchable = " ".join(
            (document.title, chunk.content, " ".join(metadata.get("keywords", [])))
        )
        candidate_tokens = _tokens(searchable)
        token_counts = Counter(_WORD.findall(searchable.lower()))
        if not query_tokens.intersection(candidate_tokens):
            continue
        locator = chunk.locator or {}
        candidates.append((RetrievedChunk(
            document_id=document.id,
            document_version_id=version.id,
            chunk_id=chunk.id,
            title=document.title,
            text=chunk.content,
            source=f"{source.name}:{document.source_path}",
            locator=str(locator.get("section") or f"chunk:{chunk.ordinal}"),
            score=0,
        ), candidate_tokens, token_counts))
    if not candidates:
        return ()

    document_frequency = Counter(token for _, tokens, _ in candidates for token in query_tokens if token in tokens)
    bm25_scores: dict[str, float] = {}
    vector_scores: dict[str, float] = {}
    for item, tokens, counts in candidates:
        bm25_scores[item.chunk_id] = sum(
            (counts.get(token, 0) / (counts.get(token, 0) + 1.2))
            * log((len(candidates) + 1) / (document_frequency[token] + 0.5) + 1)
            for token in query_tokens
        )
        vector_scores[item.chunk_id] = len(query_tokens & tokens) / max(1, len(query_tokens | tokens))
    bm25_rank = {item.chunk_id: index for index, (item, _, _) in enumerate(sorted(candidates, key=lambda row: (-bm25_scores[row[0].chunk_id], row[0].chunk_id)), 1)}
    vector_rank = {item.chunk_id: index for index, (item, _, _) in enumerate(sorted(candidates, key=lambda row: (-vector_scores[row[0].chunk_id], row[0].chunk_id)), 1)}
    reranked: list[tuple[float, RetrievedChunk]] = []
    for item, tokens, _ in candidates:
        rrf = 1 / (60 + bm25_rank[item.chunk_id]) + 1 / (60 + vector_rank[item.chunk_id])
        coverage = len(query_tokens & tokens) / max(1, len(query_tokens))
        final = min(1.0, rrf * 15 + coverage * 0.5)
        reranked.append((final, RetrievedChunk(**{**item.__dict__, "score": round(final, 6)})))
    reranked.sort(key=lambda row: (-row[0], row[1].chunk_id))
    return tuple(item for _, item in reranked[:limit])


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
