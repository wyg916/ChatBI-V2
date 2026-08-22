from __future__ import annotations

from threading import Lock
from typing import Protocol, runtime_checkable

from .contracts import VisualEvidence, VisualEvidenceCacheKey


@runtime_checkable
class VisualEvidenceCache(Protocol):
    def get(self, key: VisualEvidenceCacheKey) -> VisualEvidence | None: ...

    def put(self, evidence: VisualEvidence) -> None: ...


class InMemoryVisualEvidenceCache:
    """Process-local reference cache; production persistence may implement the Protocol."""

    def __init__(self) -> None:
        self._items: dict[str, VisualEvidence] = {}
        self._lock = Lock()

    def get(self, key: VisualEvidenceCacheKey) -> VisualEvidence | None:
        with self._lock:
            return self._items.get(key.digest())

    def put(self, evidence: VisualEvidence) -> None:
        with self._lock:
            self._items[evidence.cache_key.digest()] = evidence
