from __future__ import annotations

import hashlib
import io
from dataclasses import asdict, dataclass
from statistics import fmean
from threading import Lock
from typing import Any, Iterable

from PIL import Image


OCR_VERSION = "chatbi-rapidocr-3.9.2-ppocrv6-v1"
_MIN_TEXT_SCORE = 0.45
_MAX_LINES_PER_PAGE = 256
_MAX_TOTAL_CHARS = 20_000
_ROTATIONS = (0, 90, 180, 270)
_engine: Any | None = None
_engine_lock = Lock()


class OcrUnavailable(RuntimeError):
    pass


class OcrEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class OcrPageEvidence:
    page: int
    text: str
    line_count: int
    mean_confidence: float
    min_confidence: float
    rotation_degrees: int
    image_sha256: str
    text_sha256: str
    engine_version: str = OCR_VERSION

    def receipt(self, *, include_text: bool = False) -> dict[str, Any]:
        payload = asdict(self)
        if not include_text:
            payload.pop("text")
        return payload


def _get_engine() -> Any:
    global _engine
    with _engine_lock:
        if _engine is None:
            try:
                from rapidocr import RapidOCR
            except ImportError as exc:
                raise OcrUnavailable("SCANNED_PDF_OCR_UNAVAILABLE") from exc
            try:
                _engine = RapidOCR()
            except Exception as exc:
                raise OcrUnavailable("SCANNED_PDF_OCR_INITIALIZATION_FAILED") from exc
        return _engine


def _rotated_png(data: bytes, degrees: int) -> bytes:
    if degrees == 0:
        return data
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.load()
            rotated = source.convert("RGB").rotate(degrees, expand=True)
            output = io.BytesIO()
            rotated.save(output, format="PNG", optimize=True)
            rotated.close()
            return output.getvalue()
    except Exception as exc:
        raise OcrEvidenceError("SCANNED_PDF_OCR_IMAGE_INVALID") from exc


def _recognize(engine: Any, image: bytes) -> tuple[tuple[str, ...], tuple[float, ...]]:
    try:
        with _engine_lock:
            result = engine(image)
    except Exception as exc:
        raise OcrEvidenceError("SCANNED_PDF_OCR_EXECUTION_FAILED") from exc
    raw_texts = tuple(getattr(result, "txts", ()) or ())
    raw_scores = tuple(getattr(result, "scores", ()) or ())
    accepted = [
        (str(text).strip(), max(0.0, min(1.0, float(score))))
        for text, score in zip(raw_texts, raw_scores, strict=False)
        if str(text).strip() and float(score) >= _MIN_TEXT_SCORE
    ][:_MAX_LINES_PER_PAGE]
    return tuple(text for text, _score in accepted), tuple(score for _text, score in accepted)


def _candidate_quality(texts: tuple[str, ...], scores: tuple[float, ...]) -> tuple[float, int, float]:
    weighted_chars = sum(len(text) * score for text, score in zip(texts, scores, strict=False))
    return weighted_chars, len(texts), fmean(scores) if scores else 0.0


def extract_scanned_pdf_ocr(pages: Iterable[bytes]) -> tuple[OcrPageEvidence, ...]:
    """Extract bounded, page-located local OCR evidence before any model call."""
    page_blobs = tuple(pages)
    if not page_blobs:
        raise OcrEvidenceError("SCANNED_PDF_OCR_PAGES_REQUIRED")
    engine = _get_engine()
    evidence: list[OcrPageEvidence] = []
    total_chars = 0
    for page_number, page in enumerate(page_blobs, start=1):
        candidates: list[tuple[tuple[float, int, float], int, tuple[str, ...], tuple[float, ...]]] = []
        texts, scores = _recognize(engine, page)
        candidates.append((_candidate_quality(texts, scores), 0, texts, scores))
        if not texts:
            for degrees in _ROTATIONS[1:]:
                rotated = _rotated_png(page, degrees)
                rotated_texts, rotated_scores = _recognize(engine, rotated)
                candidates.append((
                    _candidate_quality(rotated_texts, rotated_scores),
                    degrees,
                    rotated_texts,
                    rotated_scores,
                ))
        _quality, rotation, best_texts, best_scores = max(candidates, key=lambda item: item[0])
        if not best_texts:
            raise OcrEvidenceError(f"SCANNED_PDF_OCR_EMPTY_PAGE:{page_number}")
        text = "\n".join(best_texts)
        total_chars += len(text)
        if total_chars > _MAX_TOTAL_CHARS:
            raise OcrEvidenceError("SCANNED_PDF_OCR_TEXT_LIMIT")
        evidence.append(OcrPageEvidence(
            page=page_number,
            text=text,
            line_count=len(best_texts),
            mean_confidence=round(fmean(best_scores), 6),
            min_confidence=round(min(best_scores), 6),
            rotation_degrees=rotation,
            image_sha256=hashlib.sha256(page).hexdigest(),
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        ))
    return tuple(evidence)
