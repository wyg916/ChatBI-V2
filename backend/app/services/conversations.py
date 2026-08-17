from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access import Principal
from app.models import ChatMessage, Conversation


def get_conversation(db: Session, conversation_id: str, principal: Principal) -> Conversation:
    item = db.get(Conversation, conversation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if item.workspace_id != principal.workspace_id or item.user_id != principal.user_id:
        raise HTTPException(status_code=403, detail="Conversation access denied")
    return item


def list_messages(db: Session, conversation_id: str) -> list[ChatMessage]:
    return list(db.scalars(select(ChatMessage).where(
        ChatMessage.conversation_id == conversation_id,
    ).order_by(ChatMessage.created_at, ChatMessage.id)))


def extract_slots(question: str, previous: dict | None = None) -> tuple[dict, str]:
    state = dict(previous or {})
    regions = re.findall(r"华北|华东|华南|华中|西部", question)
    previous_regions = list(state.get("regions", []))
    if regions:
        if re.search(r"那.+呢|换成|改成", question):
            comparison = list(dict.fromkeys([*previous_regions, *regions]))
            state["regions"] = regions
            state["comparison_regions"] = comparison
        else:
            state["regions"] = list(dict.fromkeys(regions))
            state["comparison_regions"] = list(dict.fromkeys([*state.get("comparison_regions", []), *regions]))
    metric_map = {
        "revenue": ("收入", "营收", "销售额"),
        "profit": ("利润", "毛利"),
        "cost": ("成本",),
        "order_count": ("订单数", "订单量", "多少单"),
    }
    for metric, markers in metric_map.items():
        if any(marker in question for marker in markers):
            state["metric"] = metric
            break
    year = re.search(r"(20\d{2})\s*年", question)
    if year:
        state["time"] = f"{year.group(1)}年"
    elif "今年" in question:
        state["time"] = "今年"
    elif "去年" in question:
        state["time"] = "去年"
    if any(marker in question for marker in ("按月", "每月", "月份", "月度", "趋势图")):
        state["granularity"] = "按月"
    if "结合知识库" in question or "知识库规则" in question:
        state["include_knowledge"] = True

    inherited: list[str] = []
    metric_labels = {"revenue": "销售额", "profit": "利润", "cost": "成本", "order_count": "订单量"}
    if state.get("time") and state["time"] not in question:
        inherited.append(str(state["time"]))
    if state.get("metric") and not any(marker in question for values in metric_map.values() for marker in values):
        inherited.append(metric_labels.get(str(state["metric"]), str(state["metric"])))
    effective_regions = state.get("regions", [])
    if re.search(r"两者|差距|相差|对比", question) and len(state.get("comparison_regions", [])) >= 2:
        effective_regions = state["comparison_regions"]
        inherited.append("按地区")
    elif len(state.get("comparison_regions", [])) >= 2 and (
        state.get("granularity") or state.get("include_knowledge")
    ):
        effective_regions = state["comparison_regions"]
    for region in effective_regions:
        if region not in question:
            inherited.append(region)
    if state.get("granularity") and not any(marker in question for marker in ("按月", "每月", "月份", "月度")):
        if re.search(r"哪个月|趋势|差距最大", question):
            inherited.append(str(state["granularity"]))
    resolved = " ".join([*inherited, question]).strip()
    return state, resolved


def refresh_conversation_summary(conversation: Conversation, question: str, slots: dict) -> None:
    if conversation.title == "新会话":
        conversation.title = question.strip().replace("\n", " ")[:40] or "附件问答"
    parts = [f"最近问题：{question.strip()[:120]}"]
    if slots.get("metric"):
        parts.append(f"指标={slots['metric']}")
    if slots.get("time"):
        parts.append(f"时间={slots['time']}")
    if slots.get("comparison_regions") or slots.get("regions"):
        parts.append("区域=" + ",".join(slots.get("comparison_regions") or slots.get("regions")))
    if slots.get("granularity"):
        parts.append(f"粒度={slots['granularity']}")
    conversation.summary = "；".join(parts)
    conversation.slot_state = slots
    conversation.updated_at = datetime.now(timezone.utc)
