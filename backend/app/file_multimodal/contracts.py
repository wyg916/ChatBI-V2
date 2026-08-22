from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class AttachmentKind(StrEnum):
    STRUCTURED = "STRUCTURED"
    DOCUMENT = "DOCUMENT"
    SCANNED_PDF = "SCANNED_PDF"
    IMAGE = "IMAGE"


@dataclass(frozen=True)
class EvidenceLocator:
    locator_type: str
    page: int | None = None
    paragraph: int | None = None
    table: int | None = None
    row: int | None = None
    column: str | None = None
    tile: int | None = None


@dataclass(frozen=True)
class TextEvidence:
    text: str
    locator: EvidenceLocator


@dataclass(frozen=True)
class TableData:
    name: str
    columns: tuple[str, ...]
    rows: tuple[Mapping[str, Any], ...]
    row_count: int


@dataclass(frozen=True)
class ParsedAttachment:
    filename: str
    extension: str
    mime_type: str
    file_sha256: str
    kind: AttachmentKind
    tables: tuple[TableData, ...] = ()
    text_evidence: tuple[TextEvidence, ...] = ()
    page_count: int = 0
    requires_vision: bool = False
    result_signature: str = ""


@dataclass(frozen=True)
class FileAnalysisResult:
    operation: str
    rows: tuple[Mapping[str, Any], ...]
    answer: str
    exact_for_full_file: bool
    result_signature: str
    source_signatures: tuple[str, ...]


@dataclass(frozen=True)
class VisualEvidenceCacheKey:
    workspace_id: str
    file_sha256: str
    vision_prompt_version: str
    provider_model_version: str
    preprocess_version: str

    def digest(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True)
class VisualClaim:
    claim: str
    value: str | int | float | None
    locator: EvidenceLocator
    confidence: float
    time_range: str | None = None
    dimension: str | None = None


@dataclass(frozen=True)
class VisualEvidence:
    cache_key: VisualEvidenceCacheKey
    provider: str
    model: str
    claims: tuple[VisualClaim, ...]
    sanitized_text: str = ""
    sensitive_classification: str = "NONE"
    injection_detected: bool = False
    preprocess_sha256: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def signature(self) -> str:
        return canonical_sha256(asdict(self))


@dataclass(frozen=True)
class DatabaseEvidence:
    metric: str
    value: Decimal
    time_range: str
    dimension: str
    business_definition: str
    query_run_id: str
    result_signature: str
    oracle_status: str


@dataclass(frozen=True)
class ImageDatabaseComparison:
    metric: str
    screenshot_value: Decimal
    database_value: Decimal
    difference: Decimal
    difference_rate: Decimal | None
    time_range: str
    dimension: str
    business_definition: str
    oracle_status: str
    visual_evidence_signature: str
    database_result_signature: str
