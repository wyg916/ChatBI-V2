import re

from chatbi_agent_contracts import QuestionRoute

from app.integration.model_gateway import ModelGateway, ModelUnavailable


_KNOWLEDGE_MARKERS = ("定义", "口径", "制度", "规则", "文档", "知识", "说明", "含义", "为什么这样算", "依据")
_DATA_MARKERS = ("多少", "趋势", "同比", "环比", "排名", "收入", "营收", "销售额", "成本", "利润", "订单", "客户", "地区", "月份", "季度", "今年", "去年", "最大", "最小", "差距")
_COMPLEX_MARKERS = ("综合分析", "深度分析", "诊断原因", "诊断", "归因分析", "原因分析", "制定分析步骤", "多维分析", "异常原因")
_GENERAL_MARKERS = ("你好", "你是谁", "谢谢", "帮助", "怎么使用", "hello", "hi")
_PRODUCT_HELP_MARKERS = (
    "第一次使用", "通用聊天机器人", "可以在这里", "问数据页面",
    "如何判断一个分析结论", "chatbi studio designed",
)
_SQL_STATEMENT = re.compile(r"^(?:with|select|drop|delete|update|insert|alter|create|truncate|call|copy)\b", re.IGNORECASE)
_UNSUPPORTED = re.compile(
    r"(?:删除|修改|写入|更新|创建)\s*(?:数据库|表|订单|客户)|绕过.*权限|(?:查看|访问).*其他工作空间|"
    r"(?:执行|运行).*(?:系统命令|shell|服务器密码|密钥)|(?:读取|泄露|导出).*(?:服务器密码|凭据|私钥)|"
    r"(?:drop|delete|update|insert|alter|create|truncate|call|copy)\s+",
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
        if _UNSUPPORTED.search(normalized):
            return QuestionRoute.UNSUPPORTED
        # Read-only SQL-looking input may use the deterministic data path;
        # mutation/administration statements were refused above. The /ask and
        # SQL Workspace APIs independently exercise SQLGlot Guard directly.
        if _SQL_STATEMENT.search(normalized):
            return QuestionRoute.DATA_QUERY
        if (
            any(marker.lower() in normalized.lower() for marker in _PRODUCT_HELP_MARKERS)
            or any(marker.lower() in normalized.lower() for marker in ("谢谢", "你好", "hello", "hi"))
        ):
            return QuestionRoute.GENERAL_CHAT
        if any(marker in question for marker in _COMPLEX_MARKERS):
            return QuestionRoute.COMPLEX_ANALYSIS
        has_knowledge = any(marker in question for marker in _KNOWLEDGE_MARKERS)
        has_data = any(marker in question for marker in _DATA_MARKERS)
        quantitative = any(marker in question for marker in (
            "多少", "趋势", "同比", "环比", "排名", "最大", "最小", "相差", "差距",
            "今年", "去年", "本月", "季度", "分别是多少", "统计", "汇总", "按地区", "按区域",
        )) or bool(re.search(r"20\d{2}\s*年", question))
        hybrid_action = any(marker in question for marker in (
            "核对", "结合", "比较", "对照", "验证", "影响", "基于数据",
        ))
        if has_data and has_knowledge and (quantitative or hybrid_action):
            return QuestionRoute.HYBRID_ANALYSIS
        if has_knowledge and not quantitative:
            return QuestionRoute.KNOWLEDGE_QUERY
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
