from chatbi_agent_contracts import QuestionRoute


_KNOWLEDGE_MARKERS = ("定义", "口径", "制度", "规则", "文档", "知识", "说明", "含义")
_DATA_MARKERS = ("多少", "趋势", "同比", "环比", "排名", "收入", "成本", "利润", "订单", "客户")
_COMPLEX_MARKERS = ("综合分析", "深度分析", "诊断原因", "归因分析", "制定分析步骤")


class QuestionRouter:
    def classify(self, question: str, requested: QuestionRoute | None = None) -> QuestionRoute:
        if requested is not None:
            return requested
        if any(marker in question for marker in _COMPLEX_MARKERS):
            return QuestionRoute.COMPLEX_ANALYSIS
        has_knowledge = any(marker in question for marker in _KNOWLEDGE_MARKERS)
        has_data = any(marker in question for marker in _DATA_MARKERS)
        if has_data and has_knowledge:
            return QuestionRoute.HYBRID_ANALYSIS
        if has_knowledge:
            return QuestionRoute.KNOWLEDGE_QUERY
        return QuestionRoute.DATA_QUERY
