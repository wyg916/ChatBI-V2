from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from chatbi_rag_contracts import Citation


_CITATION = re.compile(r"\[citation:([^\]]+)\]", re.IGNORECASE)
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


@dataclass(frozen=True)
class GroundedAnswerVerification:
    passed: bool
    reason: str | None
    cited_ids: tuple[str, ...]
    factual_units: int = 0
    citation_accuracy: float = 0.0


class GroundedAnswerRejected(RuntimeError):
    pass


def evidence_payload(citations: Iterable[Citation]) -> list[dict[str, str]]:
    """Return the only knowledge payload that may cross the model boundary."""
    return [
        {
            "citation_id": item.citation_id,
            "document_id": item.document_id,
            "document_version_id": item.document_version_id,
            "chunk_id": item.chunk_id,
            "title": item.title,
            "text": item.text,
            "source": item.source,
            "locator": item.locator or "",
        }
        for item in citations
    ]


def verify_grounded_answer(answer: str, citations: Iterable[Citation]) -> GroundedAnswerVerification:
    citation_items = tuple(citations)
    allowed = {item.citation_id for item in citation_items}
    cited = tuple(dict.fromkeys(_CITATION.findall(answer)))
    factual_lines = tuple(
        line.strip()
        for line in answer.splitlines()
        if _CITATION.sub("", line).strip().strip("#*- ")
    )
    covered_lines = sum(
        1
        for line in factual_lines
        if any(identifier in allowed for identifier in _CITATION.findall(line))
    )
    accuracy = covered_lines / len(factual_lines) if factual_lines else 0.0
    if not answer.strip():
        return GroundedAnswerVerification(False, "EMPTY_ANSWER", cited, 0, 0.0)
    if any(pattern.search(answer) for pattern in _INJECTION):
        return GroundedAnswerVerification(False, "ANSWER_PROMPT_INJECTION", cited, len(factual_lines), accuracy)
    if not allowed:
        return GroundedAnswerVerification(False, "NO_AUTHORIZED_EVIDENCE", cited, len(factual_lines), accuracy)
    if not cited:
        return GroundedAnswerVerification(False, "ANSWER_HAS_NO_CITATION", cited, len(factual_lines), accuracy)
    if any(identifier not in allowed for identifier in cited):
        return GroundedAnswerVerification(False, "UNKNOWN_CITATION", cited, len(factual_lines), accuracy)
    if not factual_lines or covered_lines != len(factual_lines):
        return GroundedAnswerVerification(False, "UNCITED_FACTUAL_UNIT", cited, len(factual_lines), accuracy)
    return GroundedAnswerVerification(True, None, cited, len(factual_lines), 1.0)


def prompt_injection_evidence_used(citations: Iterable[Citation]) -> int:
    return sum(
        1
        for item in citations
        if any(pattern.search(item.text) for pattern in _INJECTION)
    )
