from __future__ import annotations

import math
import re
from collections import Counter
from hashlib import sha256
from threading import Lock
from time import perf_counter

from app.query.contracts import QueryContext
from app.semantic_runtime.contracts import CatalogCandidate, OpenChatBIState


_BUSINESS_TOKENS = (
    "销售额", "净销售额", "销售", "收入", "净利润", "利润", "订单", "有效订单", "客户", "活跃客户",
    "产品", "品类", "地区", "区域", "退款", "取消", "应收", "账龄", "趋势", "同比", "环比", "贡献度",
    "租户", "月份", "时间", "状态", "折扣", "异常", "华东", "华北", "华南", "华中", "西部",
)

_CATALOG_SYNONYMS = {
    "month": "月份 月度 按月 趋势 同比 环比 异常",
    "region": "地区 区域",
    "product": "产品 商品",
    "category": "品类 类别",
    "customer": "客户",
    "customer_tier": "客户等级 客户层级",
    "aging_bucket": "账龄",
    "net_sales": "净销售额 销售额 收入 营收",
    "net_profit": "净利润 利润 毛利",
    "refund_amount": "退款金额 退款",
    "cancelled_orders": "取消订单 取消订单数",
    "outstanding_amount": "未结应收 应收余额 应收",
}


def _tokens(value: str) -> list[str]:
    lowered = value.lower()
    tokens = re.findall(r"[a-z0-9_]+", lowered)
    tokens.extend(token for token in _BUSINESS_TOKENS if token in value)
    chinese_runs = re.findall(r"[\u4e00-\u9fff]+", value)
    for run in chinese_runs:
        tokens.extend(run[index:index + 2] for index in range(max(0, len(run) - 1)))
    return tokens


def _vector(value: str) -> Counter[str]:
    normalized = re.sub(r"\s+", "", value.lower())
    grams = [normalized[index:index + 2] for index in range(max(1, len(normalized) - 1))]
    return Counter(grams or [normalized])


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    common = set(left) & set(right)
    numerator = sum(left[item] * right[item] for item in common)
    denominator = math.sqrt(sum(value * value for value in left.values())) * math.sqrt(sum(value * value for value in right.values()))
    return numerator / denominator if denominator else 0.0


class OpenChatBILinker:
    """Workspace-scoped hybrid catalog retrieval inspired by OpenChatBI's public contracts.

    This is a ChatBI-owned clean-room adapter. It uses no OpenChatBI internal code.
    """

    name = "openchatbi-clean-room"

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, int, str], OpenChatBIState] = {}
        self._lock = Lock()

    def link(self, *, question: str, context: QueryContext) -> OpenChatBIState:
        cache_key = (
            context.workspace_id,
            context.semantic_model_id,
            context.semantic_model_version,
            sha256(question.strip().lower().encode("utf-8")).hexdigest(),
        )
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached:
                return cached.model_copy(deep=True)

        started = perf_counter()
        documents: list[dict[str, object]] = []
        for item in context.candidate_tables:
            documents.append({"type": "table", "name": item.name, "qualified": item.qualified_name, "text": f"{item.name} {item.label} {' '.join(item.evidence)}"})
        for item in context.candidate_columns:
            documents.append({"type": "column", "name": item.name, "qualified": item.qualified_name, "text": f"{item.name} {item.label} {' '.join(item.evidence)}"})
        for item in context.metrics:
            documents.append({"type": "metric", "name": item["name"], "qualified": f"metric.{item['name']}", "text": f"{item['name']} {item.get('label', '')} {item.get('description', '')} {_CATALOG_SYNONYMS.get(item['name'], '')}"})
        for item in context.dimensions:
            documents.append({"type": "dimension", "name": item["name"], "qualified": item.get("source_column"), "text": f"{item['name']} {item.get('label', '')} {item.get('source_column', '')} {_CATALOG_SYNONYMS.get(item['name'], '')}"})
        for item in context.relationships:
            name = f"{item['left_entity']}->{item['right_entity']}"
            documents.append({"type": "relationship", "name": name, "qualified": name, "text": f"{name} {item.get('cardinality', '')} {item.get('join_keys', [])}"})
        for item in context.business_terms:
            documents.append({"type": "business_term", "name": item["term"], "qualified": item.get("mapped_object"), "text": f"{item['term']} {' '.join(item.get('synonyms', []))} {item.get('definition', '')}"})

        query_tokens = _tokens(question)
        query_counts = Counter(query_tokens)
        document_tokens = [_tokens(str(item["text"])) for item in documents]
        document_frequency = Counter(token for tokens in document_tokens for token in set(tokens))
        raw_bm25: list[float] = []
        average_length = sum(len(tokens) for tokens in document_tokens) / max(1, len(document_tokens))
        for tokens in document_tokens:
            counts = Counter(tokens)
            score = 0.0
            for token, query_frequency in query_counts.items():
                frequency = counts[token]
                if not frequency:
                    continue
                inverse_frequency = math.log(1 + (len(documents) - document_frequency[token] + 0.5) / (document_frequency[token] + 0.5))
                denominator = frequency + 1.2 * (0.25 + 0.75 * len(tokens) / max(1, average_length))
                score += query_frequency * inverse_frequency * frequency * 2.2 / denominator
            raw_bm25.append(score)
        maximum_bm25 = max(raw_bm25, default=0.0) or 1.0
        question_vector = _vector(question)
        candidates: list[CatalogCandidate] = []
        lowered = question.lower()
        for document, bm25 in zip(documents, raw_bm25):
            text = str(document["text"])
            bm25_score = min(1.0, bm25 / maximum_bm25)
            vector_score = min(1.0, _cosine(question_vector, _vector(text)))
            exact = any(token and token.lower() in lowered for token in [str(document["name"]), *str(document["text"]).split()[:3]])
            score = min(1.0, 0.52 * bm25_score + 0.38 * vector_score + (0.10 if exact else 0.0))
            evidence = [f"bm25:{bm25_score:.4f}", f"vector:{vector_score:.4f}"]
            if exact:
                evidence.append("exact_alias")
            candidates.append(CatalogCandidate(
                object_type=str(document["type"]), name=str(document["name"]),
                qualified_name=str(document["qualified"]) if document["qualified"] else None,
                score=round(score, 6), bm25_score=round(bm25_score, 6),
                vector_score=round(vector_score, 6), evidence=evidence,
            ))
        candidates.sort(key=lambda item: (-item.score, item.object_type, item.qualified_name or item.name))
        selected = candidates[:40]
        confidence = selected[0].score if selected else 0.0
        vague = bool(re.fullmatch(r".{0,4}(销售|数据|情况|业绩).{0,4}", question.strip()))
        clarification_required = confidence < 0.25 or vague
        state = OpenChatBIState(
            workspace_id=context.workspace_id,
            cache_scope=f"workspace:{context.workspace_id}:semantic:{context.semantic_model_id}:v{context.semantic_model_version}",
            candidates=selected,
            candidate_tables=[item for item in selected if item.object_type == "table"][:5],
            candidate_columns=[item for item in selected if item.object_type in {"column", "dimension"}][:12],
            candidate_metrics=[item for item in selected if item.object_type == "metric"][:8],
            candidate_relationships=[item for item in selected if item.object_type == "relationship"][:8],
            confidence=confidence,
            clarification_required=clarification_required,
            clarification_reason="指标、时间或分析粒度不明确" if clarification_required else None,
            elapsed_ms=round((perf_counter() - started) * 1000, 3),
            state_history=["START", "CATALOG_RETRIEVING", "HYBRID_RETRIEVAL", "SCHEMA_LINKED", "END"],
        )
        with self._lock:
            self._cache[cache_key] = state.model_copy(deep=True)
        return state

    def cache_scopes(self) -> set[str]:
        with self._lock:
            return {key[0] for key in self._cache}
