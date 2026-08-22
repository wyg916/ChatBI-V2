from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


_INJECTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(?:all\s+)?previous\s+instructions",
        r"忽略.{0,12}(?:之前|以上|系统).{0,8}(?:指令|提示)",
        r"(?:system|developer)\s*prompt",
        r"(?:绕过|跳过|disable).{0,16}(?:权限|guard|acl|安全)",
        r"(?:exfiltrate|reveal).{0,24}(?:secret|credential|prompt)",
    )
)
_PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_ID_CARD = re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_CREDENTIAL = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\b\s*[:=]\s*['\"]?([^\s'\"]{6,})"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")


class PromptInjectionDetected(ValueError):
    pass


def contains_prompt_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in _INJECTION_PATTERNS)


def reject_prompt_injection(values: Iterable[str]) -> None:
    if any(contains_prompt_injection(value) for value in values):
        raise PromptInjectionDetected("PROMPT_INJECTION_DETECTED")


@dataclass(frozen=True)
class SensitiveTextResult:
    classification: str
    categories: tuple[str, ...]
    redacted_text: str


def classify_and_redact(text: str) -> SensitiveTextResult:
    categories: list[str] = []
    if _PHONE.search(text):
        categories.append("PHONE")
    if _ID_CARD.search(text):
        categories.append("NATIONAL_ID")
    if _EMAIL.search(text):
        categories.append("EMAIL")
    if _CREDENTIAL.search(text) or _BEARER.search(text):
        categories.append("CREDENTIAL")
    redacted = _PHONE.sub(lambda match: f"{match.group(1)[:3]}****{match.group(1)[-4:]}", text)
    redacted = _ID_CARD.sub(lambda match: f"{match.group(1)[:6]}********{match.group(1)[-4:]}", redacted)
    redacted = _EMAIL.sub("<REDACTED_EMAIL>", redacted)
    redacted = _CREDENTIAL.sub(lambda match: match.group(0).split(":", 1)[0].split("=", 1)[0] + "=<REDACTED_CREDENTIAL>", redacted)
    redacted = _BEARER.sub("Bearer <REDACTED_CREDENTIAL>", redacted)
    classification = "HIGH" if any(value in categories for value in ("PHONE", "NATIONAL_ID", "CREDENTIAL")) else ("MEDIUM" if categories else "NONE")
    return SensitiveTextResult(classification, tuple(categories), redacted)


def remove_injection_lines(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not contains_prompt_injection(line)
    ).strip()
