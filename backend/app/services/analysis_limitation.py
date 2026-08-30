from __future__ import annotations

from chatbi_agent_contracts import QuestionRoute


def humanized_analysis_limitation(route: QuestionRoute, error_code: str) -> str:
    """Map an internal fail-closed code to safe, actionable user copy.

    The stable code remains in the response envelope for diagnostics.  Only
    the visible answer changes, and no failed result is promoted to a business
    conclusion.
    """

    code = error_code.strip().upper()
    if code == "DBGPT_RUNTIME_TIMEOUT":
        return (
            "这次复杂分析没有在受控时限内完成，因此我没有发布不完整的结论。"
            "你可以直接重试，或缩小时间范围、指标和维度后再问。"
        )
    if code.startswith("PROJECTION_"):
        return (
            "这次生成的查询存在字段或别名歧义，未通过安全校验，因此我没有执行或发布它。"
            "你可以重试，或明确指定指标、分组维度和排序方式。"
        )
    if code.startswith(("SQL_", "QUERY_", "EXPLAIN_")):
        return (
            "这次查询没有通过只读执行与安全校验，因此我没有返回可能不可靠的数据。"
            "请确认指标、时间范围和数据源后重试。"
        )
    if code.startswith(("RESULT_", "ORACLE_")):
        return (
            "查询已经完成，但结果校验没有通过，因此我暂不下结论。"
            "你可以缩小范围或换一种更明确的统计口径后重试。"
        )
    if code.startswith(("PROVIDER_", "MODEL_")):
        return (
            "这次模型没有生成满足安全与可验证要求的结果。你的问题没有丢失，"
            "请稍后重试，或先到“系统设置 → 模型服务”检查连接状态。"
        )
    if code.startswith("RAG_"):
        return (
            "当前授权知识证据不足，暂时无法形成可靠结论。"
            "请补充相关口径资料或缩小问题范围后重试。"
        )
    subject = "复杂分析" if route == QuestionRoute.COMPLEX_ANALYSIS else "分析"
    return (
        f"这次{subject}没有形成可验证的结果，因此我没有发布可能误导你的结论。"
        "请稍后重试，或补充更明确的指标、时间范围、区域和数据源。"
    )
