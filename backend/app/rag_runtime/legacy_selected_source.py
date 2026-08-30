from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from types import ModuleType, SimpleNamespace
from typing import Any


SOURCE_COMMIT = "b2573a9dc1881a54581c5c556fb4a8c34046f9c3"
SOURCE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "vendor"
    / "legacy_energy_rag"
    / SOURCE_COMMIT
)
LOCK_PATH = SOURCE_ROOT / "LOCK.json"
DIRECT_REUSE_STATUS = "PASS_OWNER_ATTESTED_VENDORED_RUNTIME"
RETRIEVAL_MODE = "legacy_owner_authorized_bm25_vector_rrf_rerank"

_STATE_LOCK = RLock()
_MODULES: tuple[ModuleType, ModuleType, ModuleType] | None = None
_RUNTIME_CALLS = 0


class SelectedSourceIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class LegacyCandidate:
    document_id: str
    document_version_id: str
    chunk_id: str
    title: str
    content: str
    source_path: str
    source: str
    locator: str
    ordinal: int
    section: str | None
    content_sha256: str


@dataclass(frozen=True)
class LegacyRankedChunk:
    candidate: LegacyCandidate
    score: float
    keyword_score: float
    vector_score: float
    rrf_score: float


def selected_source_status() -> dict[str, Any]:
    manifest = _verify_integrity()
    return {
        "direct_reuse": DIRECT_REUSE_STATUS,
        "source_commit": manifest["source_commit"],
        "selected_paths": [item["source_path"] for item in manifest["files"]],
        "runtime_calls": legacy_runtime_call_count(),
        "integrity": "PASS",
        "external_dependencies": manifest["external_dependencies"],
        "secret_references": manifest["secret_references"],
    }


def legacy_runtime_call_count() -> int:
    with _STATE_LOCK:
        return _RUNTIME_CALLS


def reset_legacy_runtime_call_count() -> None:
    global _RUNTIME_CALLS
    with _STATE_LOCK:
        _RUNTIME_CALLS = 0


def prompt_injection_detected(content: str) -> bool:
    _, _, security = _load_modules()
    return bool(security.prompt_injection_detected(content))


def rank_candidates(
    query: str,
    candidates: list[LegacyCandidate],
    *,
    limit: int,
) -> tuple[LegacyRankedChunk, ...]:
    global _RUNTIME_CALLS
    indexer, reranker, _ = _load_modules()
    rows: list[tuple[Any, Any, Any, Any]] = []
    by_id = {item.chunk_id: item for item in candidates}
    for item in candidates:
        chunk = SimpleNamespace(
            chunk_id=item.chunk_id,
            ordinal=item.ordinal,
            section=item.section,
            content=item.content,
            content_sha256=item.content_sha256,
        )
        version = SimpleNamespace(document_version_id=item.document_version_id)
        document = SimpleNamespace(
            document_id=item.document_id,
            title=item.title,
            source_path=item.source_path,
        )
        tokens = indexer.tokenize(f"{item.title}\n{item.section or ''}\n{item.content}")
        vector = indexer.feature_hash_vector(tokens)
        index = SimpleNamespace(
            embedding_model=indexer.EMBEDDING_MODEL,
            embedding_version=indexer.EMBEDDING_VERSION,
            dimensions=indexer.EMBEDDING_DIMENSIONS,
            vector_json=json.dumps(vector, separators=(",", ":")),
            vector_norm=round(math.sqrt(sum(value * value for value in vector)), 8),
            term_frequency_json=json.dumps(Counter(tokens), ensure_ascii=False, sort_keys=True),
            token_count=len(tokens),
            content_sha256=item.content_sha256,
        )
        rows.append((chunk, version, document, index))
    ranked = reranker.rank_candidates(query, rows, limit=limit)
    with _STATE_LOCK:
        _RUNTIME_CALLS += 1
    return tuple(
        LegacyRankedChunk(
            candidate=by_id[item.chunk.chunk_id],
            score=float(item.score),
            keyword_score=float(item.keyword_score),
            vector_score=float(item.vector_score),
            rrf_score=float(item.rrf_score),
        )
        for item in ranked
    )


def _verify_integrity() -> dict[str, Any]:
    try:
        manifest = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectedSourceIntegrityError("legacy RAG lock is unavailable") from exc
    if manifest.get("source_commit") != SOURCE_COMMIT:
        raise SelectedSourceIntegrityError("legacy RAG source commit mismatch")
    for item in manifest.get("files", []):
        path = SOURCE_ROOT / str(item["vendored_path"])
        try:
            source_bytes = path.read_bytes()
        except OSError as exc:
            raise SelectedSourceIntegrityError(f"missing selected source: {path.name}") from exc
        # Git may materialize a text blob with CRLF in a fresh Windows clone.
        # The lock SHA is over the canonical LF source. Canonicalizing only CRLF
        # preserves cross-platform integrity while every content-byte change still
        # fails closed. Lone CR bytes are deliberately not normalized.
        digest = hashlib.sha256(source_bytes.replace(b"\r\n", b"\n")).hexdigest()
        if digest != item.get("sha256"):
            raise SelectedSourceIntegrityError(f"selected source checksum mismatch: {path.name}")
    return manifest


def _load_modules() -> tuple[ModuleType, ModuleType, ModuleType]:
    global _MODULES
    with _STATE_LOCK:
        if _MODULES is not None:
            return _MODULES
        _verify_integrity()
        app_package = importlib.import_module("app")
        models_package = importlib.import_module("app.models")
        placeholder = ModuleType("app.models.knowledge")
        for name in (
            "KnowledgeChunk",
            "KnowledgeChunkIndex",
            "KnowledgeDocument",
            "KnowledgeDocumentVersion",
        ):
            setattr(placeholder, name, type(name, (), {}))
        knowledge_package = ModuleType("app.knowledge")
        knowledge_package.__path__ = []  # type: ignore[attr-defined]
        aliases = {
            "app.knowledge": knowledge_package,
            "app.models.knowledge": placeholder,
        }
        sentinel = object()
        previous_modules = {key: sys.modules.get(key, sentinel) for key in aliases}
        previous_knowledge = getattr(app_package, "knowledge", sentinel)
        previous_model_knowledge = getattr(models_package, "knowledge", sentinel)
        try:
            sys.modules.update(aliases)
            setattr(app_package, "knowledge", knowledge_package)
            setattr(models_package, "knowledge", placeholder)
            indexer = _load_exact_module(
                "app.knowledge.indexer", SOURCE_ROOT / "app" / "knowledge" / "indexer.py"
            )
            sys.modules["app.knowledge.indexer"] = indexer
            setattr(knowledge_package, "indexer", indexer)
            reranker = _load_exact_module(
                "app.knowledge.reranker", SOURCE_ROOT / "app" / "knowledge" / "reranker.py"
            )
            security = _load_exact_module(
                "app.knowledge.security", SOURCE_ROOT / "app" / "knowledge" / "security.py"
            )
            _MODULES = (indexer, reranker, security)
        finally:
            for key in (
                "app.knowledge.reranker",
                "app.knowledge.security",
                "app.knowledge.indexer",
                *aliases.keys(),
            ):
                previous = previous_modules.get(key, sentinel)
                if previous is sentinel:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = previous  # type: ignore[assignment]
            _restore_attribute(app_package, "knowledge", previous_knowledge, sentinel)
            _restore_attribute(models_package, "knowledge", previous_model_knowledge, sentinel)
        if _MODULES is None:
            raise SelectedSourceIntegrityError("legacy RAG selected source failed to load")
        return _MODULES


def _load_exact_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SelectedSourceIntegrityError(f"cannot load selected source: {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _restore_attribute(target: Any, name: str, previous: Any, sentinel: object) -> None:
    if previous is sentinel:
        try:
            delattr(target, name)
        except AttributeError:
            pass
    else:
        setattr(target, name, previous)
