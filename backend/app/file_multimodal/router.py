from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .analysis import requires_pandasai_runtime
from .contracts import AttachmentKind, ParsedAttachment


class FileMultimodalRoute(StrEnum):
    FILE_DETERMINISTIC = "FILE_DETERMINISTIC"
    FILE_PANDASAI_SANDBOX = "FILE_PANDASAI_SANDBOX"
    DOCUMENT_RAG = "DOCUMENT_RAG"
    VISION = "VISION"


@dataclass(frozen=True)
class AttachmentRouteDecision:
    route: FileMultimodalRoute
    reason: str
    requires_sandbox: bool = False
    requires_vision: bool = False


def route_attachment(question: str, attachments: list[ParsedAttachment]) -> AttachmentRouteDecision:
    if not attachments:
        raise ValueError("ATTACHMENT_REQUIRED")
    if any(item.kind in {AttachmentKind.IMAGE, AttachmentKind.SCANNED_PDF} or item.requires_vision for item in attachments):
        return AttachmentRouteDecision(FileMultimodalRoute.VISION, "IMAGE_OR_SCANNED_PDF", requires_vision=True)
    if any(item.kind == AttachmentKind.STRUCTURED for item in attachments):
        if requires_pandasai_runtime(question):
            return AttachmentRouteDecision(
                FileMultimodalRoute.FILE_PANDASAI_SANDBOX,
                "COMPLEX_FILE_ANALYSIS",
                requires_sandbox=True,
            )
        return AttachmentRouteDecision(FileMultimodalRoute.FILE_DETERMINISTIC, "FIXED_SAFE_OPERATOR")
    return AttachmentRouteDecision(FileMultimodalRoute.DOCUMENT_RAG, "TEXT_DOCUMENT")
