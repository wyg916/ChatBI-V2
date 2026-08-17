import re

from chatbi_agent_contracts import QuestionRoute

from app.integration.model_gateway import ModelGateway, ModelUnavailable


_KNOWLEDGE_MARKERS = ("定义", "口径", "制度", "规则", "文档", "知识", "说明", "含义", "为什么这样算", "依据")
_DATA_MARKERS = ("多少", "趋势", "同比", "环比", "排名", "收入", "营收", "销售额", "成本", "利润", "订单", "客户", "地区", "月份", "季度", "今年", "去年", "最大", "最小", "差距")
_COMPLEX_MARKERS = ("综合分析", "深度分析", "诊断原因", "归因分析", "制定分析步骤", "多维分析", "异常原因")
_GENERAL_MARKERS = ("你好", "你是谁", "谢谢", "帮助", "怎么使用", "hello", "hi")
_SQL_STATEMENT = re.compile(r"^(?:with|select|drop|delete|update|insert|alter|create|truncate|call|copy)\b", re.IGNORECASE)
_UNSUPPORTED = re.compile(
    r"(?:删除|修改|写入|更新|创建)\s*(?:数据库|表|订单|客户)|绕过.*权限|(?:查看|访问).*其他工作空间|"
    r"(?:drop|delete|update|insert|alter|create)\s+",
    re.IGNORECASE,
)


class QuestionRouter:
    def __init__(self, gateway: ModelGateway | None = None):
        self.gateway = gateway or ModelGateway()

    def classify(
        self,
        question: str,
        requested: QuestionRoute | None = None,
        *,
        history_summary: str = "",
        attachment_kinds: set[str] | None = None,
    ) -> QuestionRoute:
        if requested is not None:
            return requested
        kinds = attachment_kinds or set()
        if "IMAGE" in kinds:
            return QuestionRoute.MULTIMODAL_QUERY
        if kinds:
            return QuestionRoute.FILE_QUERY
        normalized = question.strip()
        # Explicit SQL must reach the deterministic SQL Guard so that read-only
        # statements can run and unsafe statements return a precise rejection.
        if _SQL_STATEMENT.search(normalized):
            return QuestionRoute.DATA_QUERY
        if _UNSUPPORTED.search(normalized):
            return QuestionRoute.UNSUPPORTED
        if any(marker in question for marker in _COMPLEX_MARKERS):
            return QuestionRoute.COMPLEX_ANALYSIS
        has_knowledge = any(marker in question for marker in _KNOWLEDGE_MARKERS)
        has_data = any(marker in question for marker in _DATA_MARKERS)
        if has_data and has_knowledge:
            return QuestionRoute.HYBRID_ANALYSIS
        if has_knowledge:
            return QuestionRoute.KNOWLEDGE_QUERY
        if has_data:
            return QuestionRoute.DATA_QUERY
        if any(marker.lower() in normalized.lower() for marker in _GENERAL_MARKERS):
            return QuestionRoute.GENERAL_CHAT
        if len(normalized) < 3 or normalized in {"看看", "分析一下", "怎么样", "查一下"}:
            return QuestionRoute.CLARIFICATION
        try:
            return QuestionRoute(self.gateway.classify(normalized, history_summary=history_summary))
        except (ModelUnavailable, ValueError):
            return QuestionRoute.GENERAL_CHAT
