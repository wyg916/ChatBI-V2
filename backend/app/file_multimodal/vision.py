from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Any, Mapping

from PIL import Image, ImageOps

from .contracts import VisualEvidence, VisualEvidenceCacheKey
from .security import classify_and_redact, contains_prompt_injection, remove_injection_lines


PREPROCESS_VERSION = "chatbi-vision-preprocess-v1"
_FORMAT_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


class ImagePreprocessError(ValueError):
    pass


@dataclass(frozen=True)
class ImageTile:
    ordinal: int
    left: int
    top: int
    right: int
    bottom: int
    png_bytes: bytes
    sha256: str


@dataclass(frozen=True)
class PreparedImage:
    file_sha256: str
    preprocess_sha256: str
    original_width: int
    original_height: int
    width: int
    height: int
    normalized_mime: str
    normalized_bytes: bytes
    tiles: tuple[ImageTile, ...]
    premium_triggers: frozenset[str]
    sensitive_classification: str
    sensitive_categories: tuple[str, ...]
    sanitized_detected_text: str
    injection_detected: bool
    exif_removed: bool
    orientation_normalized: bool


@dataclass(frozen=True)
class VisionInvocationRequest:
    workspace_id: str
    trace_id: str
    provider_alias: str
    normalized_images: tuple[bytes, ...]
    prompt: str
    premium_triggers: frozenset[str]
    cache_key: VisualEvidenceCacheKey
    raw_image_included_for_deepseek: bool = False


@dataclass(frozen=True)
class DeepSeekVisualRequest:
    workspace_id: str
    trace_id: str
    visual_evidence: Mapping[str, Any]
    raw_images: tuple[bytes, ...] = ()


def _validate_image_mime(data: bytes, declared_mime: str) -> tuple[Image.Image, str]:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:
        raise ImagePreprocessError("INVALID_IMAGE") from exc
    actual_mime = _FORMAT_MIME.get((image.format or "").upper())
    if actual_mime is None or actual_mime != declared_mime.lower():
        image.close()
        raise ImagePreprocessError("IMAGE_MIME_SIGNATURE_MISMATCH")
    return image, actual_mime


def _png_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    clean = Image.new(image.mode, image.size)
    clean.paste(image)
    if clean.mode not in {"RGB", "RGBA", "L"}:
        clean = clean.convert("RGB")
    clean.save(output, format="PNG", optimize=True)
    return output.getvalue()


def preprocess_image(
    data: bytes,
    declared_mime: str,
    *,
    detected_text: str = "",
    image_count: int = 1,
    small_text_hint: bool = False,
    max_dimension: int = 2048,
    tile_size: int = 1600,
    tile_overlap: int = 128,
) -> PreparedImage:
    image, _ = _validate_image_mime(data, declared_mime)
    original_width, original_height = image.size
    exif = image.getexif()
    orientation = int(exif.get(274, 1)) if exif else 1
    normalized = ImageOps.exif_transpose(image)
    if normalized.mode not in {"RGB", "RGBA", "L"}:
        normalized = normalized.convert("RGB")
    width, height = normalized.size
    if max(width, height) > max_dimension:
        scale = max_dimension / max(width, height)
        normalized = normalized.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))),
            Image.Resampling.LANCZOS,
        )
    width, height = normalized.size

    step = max(1, tile_size - tile_overlap)
    tiles: list[ImageTile] = []
    if width > tile_size or height > tile_size:
        ordinal = 0
        for top in range(0, height, step):
            for left in range(0, width, step):
                right, bottom = min(width, left + tile_size), min(height, top + tile_size)
                if right - left < 64 or bottom - top < 64:
                    continue
                tile_bytes = _png_bytes(normalized.crop((left, top, right, bottom)))
                tiles.append(ImageTile(
                    ordinal=ordinal, left=left, top=top, right=right, bottom=bottom,
                    png_bytes=tile_bytes, sha256=hashlib.sha256(tile_bytes).hexdigest(),
                ))
                ordinal += 1

    injection = contains_prompt_injection(detected_text)
    safe_text = remove_injection_lines(detected_text) if injection else detected_text.strip()
    sensitive = classify_and_redact(safe_text)
    triggers: set[str] = set()
    if image_count > 1:
        triggers.add("multi_image")
    if min(original_width, original_height) < 480 or small_text_hint:
        triggers.add("low_quality_document")
    if tiles:
        triggers.add("large_image_tiles")
    if injection:
        triggers.add("image_prompt_injection")
    if sensitive.classification != "NONE":
        triggers.add("sensitive_image")

    normalized_bytes = _png_bytes(normalized)
    image.close()
    normalized.close()
    return PreparedImage(
        file_sha256=hashlib.sha256(data).hexdigest(),
        preprocess_sha256=hashlib.sha256(normalized_bytes).hexdigest(),
        original_width=original_width,
        original_height=original_height,
        width=width,
        height=height,
        normalized_mime="image/png",
        normalized_bytes=normalized_bytes,
        tiles=tuple(tiles),
        premium_triggers=frozenset(triggers),
        sensitive_classification=sensitive.classification,
        sensitive_categories=sensitive.categories,
        sanitized_detected_text=sensitive.redacted_text,
        injection_detected=injection,
        exif_removed=True,
        orientation_normalized=orientation != 1,
    )


def build_vision_request(
    *,
    workspace_id: str,
    trace_id: str,
    prepared: PreparedImage,
    prompt: str,
    vision_prompt_version: str,
    mimo_model_version: str,
    kimi_model_version: str,
) -> VisionInvocationRequest:
    premium = bool(prepared.premium_triggers & {
        "multi_image", "low_quality_document", "large_image_tiles",
    })
    provider_alias = "kimi.vision" if premium else "mimo.vision"
    model_version = kimi_model_version if premium else mimo_model_version
    cache_key = VisualEvidenceCacheKey(
        workspace_id=workspace_id,
        file_sha256=prepared.file_sha256,
        vision_prompt_version=vision_prompt_version,
        provider_model_version=model_version,
        preprocess_version=PREPROCESS_VERSION,
    )
    images = tuple(tile.png_bytes for tile in prepared.tiles) or (prepared.normalized_bytes,)
    return VisionInvocationRequest(
        workspace_id=workspace_id,
        trace_id=trace_id,
        provider_alias=provider_alias,
        normalized_images=images,
        prompt=prompt,
        premium_triggers=prepared.premium_triggers,
        cache_key=cache_key,
    )


def build_deepseek_visual_request(
    *, workspace_id: str, trace_id: str, evidence: VisualEvidence
) -> DeepSeekVisualRequest:
    return DeepSeekVisualRequest(
        workspace_id=workspace_id,
        trace_id=trace_id,
        visual_evidence={
            "cache_key": evidence.cache_key.digest(),
            "provider": evidence.provider,
            "model": evidence.model,
            "claims": [
                {
                    "claim": claim.claim,
                    "value": claim.value,
                    "locator": claim.locator.__dict__,
                    "confidence": claim.confidence,
                }
                for claim in evidence.claims
            ],
            "sanitized_text": evidence.sanitized_text,
            "sensitive_classification": evidence.sensitive_classification,
            "injection_detected": evidence.injection_detected,
            "visual_evidence_signature": evidence.signature(),
        },
    )
