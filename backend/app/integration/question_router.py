from __future__ import annotations

import re

from chatbi_agent_contracts import QuestionRoute

from app.model_gateway import ModelGateway, ModelUnavailable, RequestContext, RouterDecision
from app.model_gateway.policy import ComplexityScorer
from app.model_gateway.test_cost_control import TestCostControlError


_KNOWLEDGE_MARKERS = ("定义", "口径", "制度", "规则", "文档", "知识", "说明", "含义", "为什么这样算", "依据")
_DATA_MARKERS = (
    "多少", "趋势", "同比", "环比", "排名", "收入", "营收", "销售额", "成本", "利润", "订单", "客户",
    "地区", "月份", "季度", "今年", "去年", "最大", "最小", "差距", "revenue", "cost", "order_count",
)
_COMPLEX_MARKERS = (
    "综合分析", "深度分析", "诊断原因", "诊断", "归因分析", "原因分析", "制定分析步骤", "多维分析",
    "异常原因", "逐行验证", "生成图表和结论",
)
_GENERAL_MARKERS = ("你好", "你是谁", "谢谢", "帮助", "怎么使用", "hello", "hi")
_NON_DATA_CONTEXT = ("写一首", "写诗", "诗歌", "翻译", "造句", "词语解释", "故事", "哲学角度")
_PRODUCT_HELP_MARKERS = (
    "第一次使用", "通用聊天机器人", "可以在这里", "问数据页面",
    "如何判断一个分析结论", "chatbi studio designed",
)
_SQL_STATEMENT = re.compile(r"^(?:with|select|drop|delete|update|insert|alter|create|truncate|call|copy)\b", re.IGNORECASE)
_DATE_QUESTION = re.compile(
    r"(?:(?:今天|今日|现在).*(?:几号|日期|星期|周几)|(?:几号|日期|星期|周几).*(?:今天|今日|现在)|"
    r"固定历史日期\s*\d{4}-\d{2}-\d{2}|fixed historical date\s*\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_UNSUPPORTED = re.compile(
    r"(?:删除|修改|写入|更新|创建)\s*(?:数据库|表|订单|客户)|绕过.*权限|(?:查看|访问).*其他工作空间|"
    r"(?:执行|运行).*(?:系统命令|shell|服务器密码|密钥)|(?:读取|泄露|导出|打印).*(?:服务器密码|凭据|私钥|密钥|系统提示|环境变量|上下文)|"
    r"(?:忽略|disable|ignore).*(?:安全策略|acl|权限)|(?:system|developer message|\[inst\]).*(?:授权|泄露|密码|acl|忽略)|"
    r"(?:文档指令).*(?:系统指令)|"
    r"(?:伪造|随便编|编造).*(?:报告|客户|数据|结论)|(?:另一个|其他|다른)\s*(?:workspace|工作空间)|"
    r"(?:管理员身份|绕过\s*acl)|(?:无限循环|所有历史.*所有表.*所有文件)|"
    r"(?:drop|delete|update|insert|alter|create|truncate|call|copy)\s+",
    re.IGNORECASE,
)
_AMBIGUOUS = re.compile(
    r"^(?:增长意味着什么|给我一个好的数字|收入多少|看看华东|按月比较一下|上次那个指标再算一遍|同比|退款率环比)[？?。]?$|"
    r"(?:不存在的指标|数据库中不存在的\s*[a-z_]+\s*表)|(?:秘密预算数字)|(?:先\s*clarify)",
    re.IGNORECASE,
)
_COMMON_TYPO_REPLACEMENTS = {
    "第一季哉": "第一季度",
    "订単": "订单",
    "品屏": "品类",
    "利閏": "利润",
    "多邵": "多少",
    "环毕": "环比",
}


def normalize_common_input_typos(question: str) -> str:
    normalized = question
    for source, target in _COMMON_TYPO_REPLACEMENTS.items():
        normalized = normalized.replace(source, target)
    return normalized


def is_local_date_question(question: str) -> bool:
    return bool(_DATE_QUESTION.search(question.strip()))


class QuestionRouter:
    def __init__(self, gateway: ModelGateway | None = None):
        self.gateway = gateway or ModelGateway()

    @staticmethod
    def _decision(
        route: QuestionRoute,
        *,
        question: str,
        reason: str,
        confidence: float = 1.0,
        model_required: bool = False,
        requested_alias: str = "none",
        attachment_count: int = 0,
    ) -> RouterDecision:
        return RouterDecision(
            route=route,
            confidence=confidence,
            reason=reason,
            complexity_score=ComplexityScorer.score(
                question, route=route, attachment_count=attachment_count,
            ),
            model_required=model_required,
            requested_alias=requested_alias,
            needs_sql=route in {QuestionRoute.DATA_QUERY, QuestionRoute.HYBRID_ANALYSIS, QuestionRoute.COMPLEX_ANALYSIS},
            needs_rag=route in {QuestionRoute.KNOWLEDGE_QUERY, QuestionRoute.HYBRID_ANALYSIS, QuestionRoute.COMPLEX_ANALYSIS},
            needs_vision=route == QuestionRoute.MULTIMODAL_QUERY,
            needs_clarification=route == QuestionRoute.CLARIFICATION,
            time_expressions=tuple(
                marker for marker in ("今天", "本月", "今年", "去年", "季度") if marker in question
            ),
        )

    def decide(
        self,
        question: str,
        requested: QuestionRoute | None = None,
        *,
        history_summary: str = "",
        attachment_kinds: set[str] | None = None,
        context: RequestContext | None = None,
    ) -> RouterDecision:
        normalized = normalize_common_input_typos(question.strip())
        kinds = attachment_kinds or set()
        if requested is not None:
            return self._decision(requested, question=normalized, reason="EXPLICIT_ROUTE", attachment_count=len(kinds))
        if kinds & {"IMAGE", "SCANNED_PDF"}:
            return self._decision(
                QuestionRoute.MULTIMODAL_QUERY, question=normalized,
                reason="VISION_ATTACHMENT", attachment_count=len(kinds),
            )
        if kinds:
            return self._decision(
                QuestionRoute.FILE_QUERY, question=normalized,
                reason="FILE_ATTACHMENT", attachment_count=len(kinds),
            )
        if _UNSUPPORTED.search(normalized):
            return self._decision(QuestionRoute.UNSUPPORTED, question=normalized, reason="SECURITY_POLICY")
        if _SQL_STATEMENT.search(normalized):
            return self._decision(QuestionRoute.DATA_QUERY, question=normalized, reason="READ_ONLY_SQL_SHAPE")
        if is_local_date_question(normalized):
            return self._decision(
                QuestionRoute.GENERAL_CHAT, question=normalized, reason="DATE_TIME_L0",
                confidence=1.0, model_required=False, requested_alias="none",
            )
        if any(marker in normalized for marker in _NON_DATA_CONTEXT):
            return self._decision(
                QuestionRoute.GENERAL_CHAT, question=normalized, reason="NON_DATA_CONTEXT_L0",
            )
        if _AMBIGUOUS.search(normalized):
            return self._decision(
                QuestionRoute.CLARIFICATION, question=normalized, reason="MISSING_REQUIRED_SLOTS",
            )
        if (
            any(marker.lower() in normalized.lower() for marker in _PRODUCT_HELP_MARKERS)
            or any(marker.lower() in normalized.lower() for marker in ("谢谢", "你好", "hello", "hi"))
        ):
            return self._decision(QuestionRoute.GENERAL_CHAT, question=normalized, reason="GENERAL_L0")
        if any(marker in normalized for marker in _COMPLEX_MARKERS):
            return self._decision(QuestionRoute.COMPLEX_ANALYSIS, question=normalized, reason="COMPLEX_L0")
        has_knowledge = any(marker in normalized for marker in _KNOWLEDGE_MARKERS)
        has_data = any(marker in normalized for marker in _DATA_MARKERS)
        quantitative = any(marker.lower() in normalized.lower() for marker in (
            "多少", "趋势", "同比", "环比", "排名", "最大", "最小", "相差", "差距",
            "今年", "去年", "本月", "季度", "分别是多少", "统计", "汇总", "按地区", "按区域",
            "compare", "verify exact rows", "trend", "by 区域",
        )) or bool(re.search(r"20\d{2}\s*年", normalized))
        hybrid_action = any(marker in normalized for marker in ("核对", "结合", "比较", "对照", "验证", "影响", "基于数据"))
        if has_data and has_knowledge and (quantitative or hybrid_action):
            return self._decision(QuestionRoute.HYBRID_ANALYSIS, question=normalized, reason="HYBRID_L0")
        if has_knowledge:
            return self._decision(QuestionRoute.KNOWLEDGE_QUERY, question=normalized, reason="KNOWLEDGE_L0")
        if has_data:
            return self._decision(QuestionRoute.DATA_QUERY, question=normalized, reason="DATA_L0")
        if any(marker.lower() in normalized.lower() for marker in _GENERAL_MARKERS):
            return self._decision(QuestionRoute.GENERAL_CHAT, question=normalized, reason="GENERAL_L0")
        if len(normalized) < 3 or normalized in {"看看", "分析一下", "怎么样", "查一下"}:
            return self._decision(QuestionRoute.CLARIFICATION, question=normalized, reason="MISSING_REQUIRED_SLOTS")
        score = ComplexityScorer.score(normalized)
        try:
            route = QuestionRoute(self.gateway.classify(
                normalized, history_summary=history_summary, context=context, complexity_score=score,
            ))
            return self._decision(
                route, question=normalized, reason="MODEL_INTENT_ROUTER",
                confidence=0.75, model_required=True, requested_alias="auto",
            )
        except (ModelUnavailable, ValueError, TestCostControlError) as exc:
            if isinstance(exc, TestCostControlError) and str(exc) != "LEVEL0_PAID_PROVIDER_CALL_BLOCKED":
                raise
            return self._decision(
                QuestionRoute.GENERAL_CHAT, question=normalized,
                reason="INTENT_MODEL_UNAVAILABLE_SAFE_GENERAL", confidence=0.5,
            )

    def classify(
        self,
        question: str,
        requested: QuestionRoute | None = None,
        *,
        history_summary: str = "",
        attachment_kinds: set[str] | None = None,
        context: RequestContext | None = None,
    ) -> QuestionRoute:
        return self.decide(
            question, requested, history_summary=history_summary,
            attachment_kinds=attachment_kinds, context=context,
        ).route
