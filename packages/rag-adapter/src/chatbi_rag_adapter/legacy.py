from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from collections.abc import Callable

import httpx

from chatbi_rag_contracts import (
    Citation,
    CitationVerification,
    RagExecutionContext,
    RagRequest,
    RagResult,
)


class RagAdapterError(RuntimeError):
    pass


class UnavailableRagAdapter:
    def retrieve(self, request: RagRequest) -> RagResult:
        raise RagAdapterError("legacy RAG runtime is not configured")


class LiveRagAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str = "",
        shared_secret: str = "",
        endpoint: str = "/api/v1/retrieve",
        require_workspace_echo: bool = True,
        retry_count: int = 1,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("legacy RAG base_url must use HTTP or HTTPS")
        self.base_url = base_url.rstrip("/")
        self.bearer_token = bearer_token
        self.shared_secret = shared_secret
        self.endpoint = endpoint
        self.require_workspace_echo = require_workspace_echo
        self.retry_count = max(0, min(retry_count, 2))
        self.client_factory = client_factory

    def retrieve(self, request: RagRequest) -> RagResult:
        headers = {
            "X-ChatBI-Workspace-Id": request.context.workspace_id,
            "X-ChatBI-User-Id": request.context.user_id,
            "X-ChatBI-Roles": ",".join(sorted(request.context.roles)),
            "X-ChatBI-Trace-Id": request.context.trace_id,
        }
        payload = {
            "query": request.query,
            "scenario_id": request.scenario_id,
            "limit": request.limit,
            "trace_id": request.context.trace_id,
            "chatbi_context": {
                "workspace_id": request.context.workspace_id,
                "user_id": request.context.user_id,
                "roles": sorted(request.context.roles),
                "allowed_datasources": sorted(request.context.allowed_datasources),
                "allowed_semantic_models": sorted(request.context.allowed_semantic_models),
                "allowed_tools": sorted(request.context.allowed_tools),
                "trace_id": request.context.trace_id,
                "timeout_ms": request.context.timeout_ms,
                "max_steps": request.context.max_steps,
                "token_budget": request.context.token_budget,
            },
        }
        body_bytes = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        timestamp = str(int(time.time()))
        if self.shared_secret:
            headers["X-ChatBI-Timestamp"] = timestamp
            headers["X-ChatBI-Signature"] = hmac.new(
                self.shared_secret.encode("utf-8"),
                timestamp.encode("ascii") + b"." + body_bytes,
                hashlib.sha256,
            ).hexdigest()
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        headers["Content-Type"] = "application/json"
        response = None
        last_error: Exception | None = None
        for attempt in range(self.retry_count + 1):
            try:
                with self.client_factory(
                    base_url=self.base_url,
                    timeout=request.context.timeout_ms / 1000,
                    follow_redirects=False,
                ) as client:
                    response = client.post(self.endpoint, content=body_bytes, headers=headers)
                    if response.status_code >= 500 and attempt < self.retry_count:
                        continue
                    response.raise_for_status()
                    break
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= self.retry_count:
                    raise RagAdapterError(
                        f"live RAG request failed: {type(exc).__name__}"
                    ) from exc
        if response is None:
            raise RagAdapterError(
                f"live RAG request failed: {type(last_error).__name__ if last_error else 'UNKNOWN'}"
            )
        echoed_workspace = response.headers.get("X-ChatBI-Workspace-Id")
        if self.require_workspace_echo and echoed_workspace != request.context.workspace_id:
            raise RagAdapterError("legacy RAG workspace identity was not echoed")
        body = response.json()
        raw_citations = body.get("citations") or []
        citations = tuple(self._citation(item, index) for index, item in enumerate(raw_citations, 1))
        refusal = body.get("refusal_reason")
        return RagResult(
            status="REFUSED" if refusal or not citations else "SUCCEEDED",
            citations=citations,
            answer=None,
            retrieval_mode=body.get("retrieval_mode"),
            refusal_reason=refusal,
            trace_id=str(body.get("trace_id") or request.context.trace_id),
            run_id=body.get("run_id"),
            adapter="chatbi-live-rag-http",
            metadata={
                "answer_guard_status": body.get("answer_guard_status"),
                "vector_status": body.get("vector_status"),
                "workspace_echo_verified": echoed_workspace == request.context.workspace_id,
            },
        )

    def health(self, *, timeout_ms: int = 1500) -> bool:
        try:
            with self.client_factory(
                base_url=self.base_url,
                timeout=timeout_ms / 1000,
                follow_redirects=False,
            ) as client:
                response = client.get("/health")
                return response.status_code == 200 and response.json().get("status") == "ok"
        except (httpx.HTTPError, ValueError):
            return False

    @staticmethod
    def _citation(item: dict, index: int) -> Citation:
        return Citation(
            citation_id=str(item.get("citation_id") or f"citation-{index}"),
            document_id=str(item.get("document_id") or ""),
            document_version_id=str(item.get("document_version_id") or ""),
            chunk_id=str(item.get("chunk_id") or ""),
            title=str(item.get("title") or ""),
            text=str(item.get("citation_text") or item.get("text") or ""),
            source=str(item.get("source") or ""),
            locator=item.get("locator"),
            score=float(item.get("retrieval_score") or item.get("score") or 0),
        )


class CitationVerifierV1:
    _INJECTION = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"忽略.{0,12}(之前|以上|系统).{0,8}(指令|提示)",
        r"(system|developer)\s*prompt",
        r"(绕过|跳过|disable).{0,16}(权限|guard|acl|安全)",
        r"(exfiltrate|reveal).{0,24}(secret|credential|prompt)",
    ))

    def verify(self, query: str, citations: tuple[Citation, ...]) -> CitationVerification:
        if not query.strip():
            return CitationVerification(passed=False, reason="EMPTY_QUERY")
        if not citations:
            return CitationVerification(passed=False, reason="NO_PUBLISHED_EVIDENCE")
        seen: set[str] = set()
        for item in citations:
            if not all((item.document_id, item.document_version_id, item.chunk_id, item.text, item.source)):
                return CitationVerification(passed=False, reason="INCOMPLETE_CITATION")
            if item.citation_id in seen:
                return CitationVerification(passed=False, reason="DUPLICATE_CITATION")
            if any(pattern.search(item.text) for pattern in self._INJECTION):
                return CitationVerification(passed=False, reason="PROMPT_INJECTION_EVIDENCE")
            seen.add(item.citation_id)
        return CitationVerification(passed=True, verified_ids=tuple(sorted(seen)))


class LegacyRagAdapter(LiveRagAdapter):
    """Deprecated import alias retained for one release; it uses the live bridge."""
