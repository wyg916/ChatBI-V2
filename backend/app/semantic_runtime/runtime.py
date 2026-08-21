from __future__ import annotations

from functools import lru_cache
from time import perf_counter
from typing import Literal

from app.core.config import Settings, get_settings
from app.query.contracts import QueryContext, SQLPlan
from app.query.nl2sql import Nl2SqlRouter
from app.semantic_runtime.contracts import SemanticRuntimeError, SemanticRuntimeTrace
from app.semantic_runtime.openchatbi import OpenChatBILinker
from app.semantic_runtime.supersonic import SuperSonicSemanticPipeline
from app.semantic_runtime.wren import WrenRuntimeAdapter


class SemanticRuntime:
    """Default DATA_QUERY semantic chain with an explicit local rollback mode."""

    def __init__(
        self,
        settings: Settings | None = None,
        router: Nl2SqlRouter | None = None,
        *,
        upstream_reuse_mode: Literal["selected_source", "clean_room"] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.upstream_reuse_mode = upstream_reuse_mode or self.settings.semantic_upstream_reuse_mode
        self.local_router = router or Nl2SqlRouter(settings=self.settings)
        upstream_reuse = self.upstream_reuse_mode == "selected_source"
        self.openchatbi = OpenChatBILinker(upstream_reuse=upstream_reuse)
        self.supersonic = SuperSonicSemanticPipeline()
        self.wren = WrenRuntimeAdapter(self.local_router, upstream_reuse=upstream_reuse)

    def capabilities(self) -> dict:
        return {
            "mode": self.settings.semantic_runtime_mode,
            "upstream_reuse_mode": self.upstream_reuse_mode,
            "default_chain": ["openchatbi", "supersonic", "wren", "sqlglot", "query_executor", "result_oracle"],
            "rollback": "CHATBI_SEMANTIC_RUNTIME_MODE=local",
            "ab_switch": "SemanticRuntime(upstream_reuse_mode='selected_source'|'clean_room')",
            "runtime_available": True,
        }

    def plan(self, *, question: str, context: QueryContext) -> tuple[SQLPlan, SemanticRuntimeTrace]:
        if self.settings.semantic_runtime_mode == "local":
            started = perf_counter()
            plan = self.local_router.plan(question=question, context=context)
            return plan, SemanticRuntimeTrace(
                mode="local", openchatbi_called=False, supersonic_called=False, wren_called=False,
                call_chain=["LocalSemanticEngine", "SQLGlot", "QueryExecutor", "ResultOracle"],
                stage_latency_ms={"local_semantic_engine": round((perf_counter() - started) * 1000, 3)},
            )

        latency: dict[str, float] = {}
        started = perf_counter()
        linking = self.openchatbi.link(question=question, context=context)
        latency["openchatbi"] = round((perf_counter() - started) * 1000, 3)
        started = perf_counter()
        try:
            semantic_query = self.supersonic.parse(question=question, context=context, linking=linking)
        except SemanticRuntimeError as exc:
            latency["supersonic"] = round((perf_counter() - started) * 1000, 3)
            exc.trace = SemanticRuntimeTrace(
                mode="wren", openchatbi_called=True, supersonic_called=True, wren_called=False,
                call_chain=["OpenChatBI", "SuperSonic:BLOCKED"], stage_latency_ms=latency,
                schema_linking=linking,
                upstream_runtime_call_count={"openchatbi": linking.upstream_call_count, "wrenai": 0},
            )
            raise
        latency["supersonic"] = round((perf_counter() - started) * 1000, 3)
        started = perf_counter()
        mdl = self.wren.compile_mdl(context)
        dry_plan = self.wren.dry_plan(semantic_query=semantic_query, mdl=mdl)
        plan = self.wren.translate(
            question=question, context=context, semantic_query=semantic_query, dry_plan=dry_plan,
        )
        latency["wren"] = round((perf_counter() - started) * 1000, 3)
        trace = SemanticRuntimeTrace(
            mode="wren", openchatbi_called=True, supersonic_called=True, wren_called=True,
            call_chain=["OpenChatBI", "SuperSonic", "WrenAI", "SQLGlot", "QueryExecutor", "ResultOracle"],
            stage_latency_ms=latency, schema_linking=linking, semantic_query=semantic_query,
            wren_mdl=mdl, wren_dry_plan=dry_plan,
            upstream_runtime_call_count={
                "openchatbi": linking.upstream_call_count,
                "wrenai": mdl.upstream_call_count + dry_plan.upstream_call_count,
            },
        )
        return plan, trace


@lru_cache(maxsize=1)
def default_semantic_runtime() -> SemanticRuntime:
    """Return the process-wide semantic runtime used by API requests."""
    return SemanticRuntime()
