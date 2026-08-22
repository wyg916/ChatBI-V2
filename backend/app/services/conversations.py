from __future__ import annotations

import re
from ipaddress import ip_address
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.access import Principal
from app.models import ChatMessage, Conversation, ConversationShare, Project


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


def list_conversations(
    db: Session,
    principal: Principal,
    *,
    query: str = "",
    state: str = "active",
    project_id: str | None = None,
) -> list[Conversation]:
    statement = select(Conversation).where(
        Conversation.workspace_id == principal.workspace_id,
        Conversation.user_id == principal.user_id,
    )
    if state == "active":
        statement = statement.where(Conversation.archived_at.is_(None))
    elif state == "archived":
        statement = statement.where(Conversation.archived_at.is_not(None))
    elif state != "all":
        raise HTTPException(status_code=422, detail="Invalid conversation state")
    if project_id:
        get_project(db, project_id, principal)
        statement = statement.where(Conversation.project_id == project_id)
    normalized_query = " ".join(query.split())[:255]
    if normalized_query:
        escaped = normalized_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        statement = statement.where(or_(
            Conversation.title.ilike(pattern, escape="\\"),
            Conversation.summary.ilike(pattern, escape="\\"),
        ))
    return list(db.scalars(statement.order_by(
        Conversation.pinned_at.is_(None),
        Conversation.pinned_at.desc(),
        Conversation.updated_at.desc(),
        Conversation.id,
    )))


def get_project(db: Session, project_id: str, principal: Principal) -> Project:
    item = db.get(Project, project_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if item.workspace_id != principal.workspace_id or item.user_id != principal.user_id:
        raise HTTPException(status_code=403, detail="Project access denied")
    return item


def list_projects(
    db: Session,
    principal: Principal,
    *,
    query: str = "",
    state: str = "active",
) -> list[Project]:
    statement = select(Project).where(
        Project.workspace_id == principal.workspace_id,
        Project.user_id == principal.user_id,
    )
    if state == "active":
        statement = statement.where(Project.archived_at.is_(None))
    elif state == "archived":
        statement = statement.where(Project.archived_at.is_not(None))
    elif state != "all":
        raise HTTPException(status_code=422, detail="Invalid project state")
    normalized_query = " ".join(query.split())[:255]
    if normalized_query:
        escaped = normalized_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        statement = statement.where(or_(
            Project.name.ilike(pattern, escape="\\"),
            Project.description.ilike(pattern, escape="\\"),
        ))
    return list(db.scalars(statement.order_by(Project.updated_at.desc(), Project.id)))


def require_owned_conversations(
    db: Session,
    conversation_ids: list[str],
    principal: Principal,
) -> list[Conversation]:
    items = list(db.scalars(select(Conversation).where(
        Conversation.id.in_(conversation_ids),
        Conversation.workspace_id == principal.workspace_id,
        Conversation.user_id == principal.user_id,
    )))
    by_id = {item.id: item for item in items}
    if len(by_id) != len(conversation_ids):
        raise HTTPException(status_code=403, detail="Batch conversation access denied")
    return [by_id[item_id] for item_id in conversation_ids]


def get_conversation_share(
    db: Session,
    share_id: str,
    principal: Principal,
) -> ConversationShare:
    item = db.get(ConversationShare, share_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Conversation share not found")
    get_conversation(db, item.conversation_id, principal)
    if item.workspace_id != principal.workspace_id or item.created_by_user_id != principal.user_id:
        raise HTTPException(status_code=403, detail="Conversation share access denied")
    return item


_SECRET_VALUE = re.compile(
    r"(?i)\b(api[_ -]?key|password|passwd|secret|authorization|bearer|database[_ -]?credential)\b\s*[:=]\s*[^\s,;]+"
)
_PRIVATE_URL = re.compile(r"https?://[^\s)\]}]+", re.IGNORECASE)
_SQL_FENCE = re.compile(r"```\s*sql\b.*?```", re.IGNORECASE | re.DOTALL)
_SQL_LINE = re.compile(
    r"(?im)^\s*(?:WITH|SELECT|FROM|WHERE|JOIN|LEFT\s+JOIN|RIGHT\s+JOIN|INNER\s+JOIN|"
    r"GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT)\b[^\r\n]*(?:\r?\n|$)"
)
_TRACE_VALUE = re.compile(r"(?i)\b(?:trace(?:[_ -]?id)?\s*[:=]\s*|TRACE-)[A-Za-z0-9._:-]+")
_PRIVATE_KEYS = {
    "api_key", "authorization", "credential", "credentials", "database_url", "hidden_prompt",
    "internal_trace", "password", "prompt", "reasoning", "reasoning_content", "secret", "sql",
    "storage_key", "token", "trace", "trace_payload", "url",
}


def _is_private_key(value: str) -> bool:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in _PRIVATE_KEYS or any(marker in normalized for marker in (
        "api_key", "credential", "password", "private_url", "reasoning", "secret", "storage_key",
    ))


def _safe_public_url(value: str) -> str:
    if "/attachments/" in value.lower() or "/artifact" in value.lower():
        return "[已隐藏私有链接]"
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https" or parsed.username or parsed.password or not parsed.hostname:
        return "[已隐藏不安全链接]"
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal", ".corp", ".lan")):
        return "[已隐藏私有链接]"
    try:
        if not ip_address(hostname).is_global:
            return "[已隐藏私有链接]"
    except ValueError:
        pass
    if any(marker in parsed.query.lower() for marker in ("token=", "signature=", "x-amz-", "credential=")):
        return "[已隐藏私有链接]"
    return value


def redact_public_text(value: str, *, limit: int = 8_000) -> str:
    redacted = _SQL_FENCE.sub("[SQL 已隐藏]", value)
    redacted = _SQL_LINE.sub("[SQL 已隐藏]\n", redacted)
    redacted = _TRACE_VALUE.sub("[Trace 已隐藏]", redacted)
    redacted = _SECRET_VALUE.sub(lambda match: f"{match.group(1)}=[已隐藏]", redacted)
    redacted = _PRIVATE_URL.sub(lambda match: _safe_public_url(match.group(0)), redacted)
    return redacted[:limit]


def safe_public_locator(value: str) -> str:
    stripped = value.strip()
    if re.match(r"^[a-z][a-z0-9+.-]*:", stripped, re.IGNORECASE):
        return _safe_public_url(stripped) if stripped.lower().startswith("https://") else "[已隐藏不安全链接]"
    if stripped.startswith("//"):
        return "[已隐藏不安全链接]"
    return redact_public_text(stripped, limit=1_000)


def _public_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return None
    if isinstance(value, str):
        return redact_public_text(value, limit=4_000)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, list):
        return [_public_value(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, dict):
        return {
            str(key)[:128]: _public_value(item, depth=depth + 1)
            for key, item in list(value.items())[:100]
            if not _is_private_key(str(key))
        }
    return redact_public_text(str(value), limit=1_000)


def public_message_parts(message: ChatMessage) -> list[dict[str, Any]]:
    raw_parts = message.response_payload.get("message_parts", []) if isinstance(message.response_payload, dict) else []
    if not isinstance(raw_parts, list):
        return []
    safe_parts: list[dict[str, Any]] = []
    for raw_part in raw_parts[:30]:
        if not isinstance(raw_part, dict):
            continue
        part_type = str(raw_part.get("type") or "")
        if part_type == "text":
            safe_parts.append({
                "type": "text",
                "text": redact_public_text(str(raw_part.get("text") or "")),
                "role": redact_public_text(str(raw_part.get("role") or ""), limit=64),
            })
        elif part_type == "kpi":
            safe_parts.append({"type": "kpi", "items": _public_value(raw_part.get("items") or [])})
        elif part_type == "chart":
            safe_parts.append({
                "type": "chart",
                "chart_spec": _public_value(raw_part.get("chart_spec") or {}),
                "result_signature": redact_public_text(str(raw_part.get("result_signature") or ""), limit=128),
            })
        elif part_type == "table":
            columns = [
                str(column)[:255] for column in (raw_part.get("columns") or [])[:30]
                if not _is_private_key(str(column))
            ]
            rows = []
            for row in (raw_part.get("rows") or [])[:100]:
                if isinstance(row, dict):
                    rows.append({column: _public_value(row.get(column)) for column in columns})
            safe_parts.append({
                "type": "table", "columns": columns, "rows": rows,
                "row_count": len(rows),
                "result_signature": redact_public_text(str(raw_part.get("result_signature") or ""), limit=128),
            })
        elif part_type == "citations":
            items = []
            for item in (raw_part.get("items") or [])[:30]:
                if not isinstance(item, dict):
                    continue
                locator = safe_public_locator(str(item.get("locator") or ""))
                items.append({
                    "title": redact_public_text(str(item.get("title") or ""), limit=255),
                    "version": redact_public_text(str(item.get("version") or ""), limit=64),
                    "locator": locator,
                })
            safe_parts.append({"type": "citations", "items": items})
        elif part_type == "error":
            safe_parts.append({
                "type": "error",
                "code": redact_public_text(str(raw_part.get("code") or "SHARED_ERROR"), limit=64),
                "message": redact_public_text(str(raw_part.get("message") or "")),
                "retryable": False,
            })
    return safe_parts


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
    dimension_markers = {
        "region": ("按地区", "按区域", "地区维度", "区域维度"),
        "customer": ("按客户", "客户维度", "客户排名", "客户分组", "客户"),
        "product": ("按产品", "按品类", "产品维度", "品类维度", "产品", "商品", "品类"),
        "status": ("按状态", "状态维度"),
        "month": ("按月", "每月", "月份", "月度"),
    }
    dimensions = list(state.get("dimensions", []))
    for dimension, markers in dimension_markers.items():
        if any(marker in question for marker in markers) and dimension not in dimensions:
            dimensions.append(dimension)
    if dimensions:
        state["dimensions"] = dimensions

    customer_match = re.search(r"(?:客户|客户名称)[：:\s]*(?!维度|排名|分组)([A-Za-z0-9\u4e00-\u9fff_-]{2,32})", question)
    if customer_match:
        state["customer"] = customer_match.group(1)
    product_match = re.search(r"(?:产品|商品)[：:\s]*(?!维度|类别|品类)([A-Za-z0-9\u4e00-\u9fff_-]{2,32})", question)
    if product_match:
        state["product"] = product_match.group(1)

    filter_markers = {
        "status=PAID": ("已支付", "支付完成"),
        "status=VALID": ("有效订单", "仅有效"),
        "status=REFUNDED": ("退款订单", "已退款"),
        "status!=CANCELLED": ("排除取消", "不含取消", "剔除取消"),
    }
    filters = list(state.get("filters", []))
    for value, markers in filter_markers.items():
        if any(marker in question for marker in markers) and value not in filters:
            filters.append(value)
    if filters:
        state["filters"] = filters
    if "结合知识库" in question or "知识库规则" in question:
        state["include_knowledge"] = True
    references = dict(state.get("references", {}))
    reference_markers = {
        "previous_sql": ("刚才的SQL", "上一条SQL", "前面的SQL"),
        "previous_result": ("刚才的结果", "上一轮结果", "前面的结果", "基于这个结果"),
        "citation": ("刚才的引用", "上一轮引用", "这个依据"),
        "attachment": ("这个附件", "刚才的附件", "上一份附件"),
        "file_context": ("这个文件", "刚才的文件", "上一份文件"),
    }
    for key, markers in reference_markers.items():
        if any(marker.lower() in question.lower() for marker in markers):
            references[key] = True
    if references:
        state["references"] = references

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
    dimension_labels = {"region": "按地区", "customer": "按客户", "product": "按产品", "status": "按状态", "month": "按月"}
    if re.search(r"继续|再看|再按|换成|那.+呢|基于|上一轮|刚才|前面", question):
        for dimension in state.get("dimensions", []):
            label = dimension_labels.get(str(dimension), str(dimension))
            if label not in question and label not in inherited:
                inherited.append(label)
        if state.get("customer") and str(state["customer"]) not in question:
            inherited.append(f"客户 {state['customer']}")
        if state.get("product") and str(state["product"]) not in question:
            inherited.append(f"产品 {state['product']}")
        for item in state.get("filters", []):
            if str(item) not in inherited:
                inherited.append(str(item))
    if references:
        inherited.append("基于上一轮已验证上下文")
    resolved = " ".join([*inherited, question]).strip()
    return state, resolved


def merge_runtime_context(
    slots: dict,
    *,
    datasource_id: str | None,
    semantic_model_id: str | None,
    response_payload: dict[str, Any],
    retrieved_sources: list[dict],
    attachments: list[Any],
) -> dict:
    state = dict(slots)
    if datasource_id:
        state["datasource"] = datasource_id
    if semantic_model_id:
        state["semantic_model"] = semantic_model_id
    analysis = response_payload.get("analysis") if isinstance(response_payload, dict) else None
    primary = (analysis or {}).get("primary", {}) if isinstance(analysis, dict) else {}
    data = primary.get("data", primary) if isinstance(primary, dict) else {}
    if isinstance(data, dict):
        plan = data.get("plan") or {}
        guard = data.get("guard") or {}
        execution = data.get("execution") or {}
        sql = guard.get("normalized_sql") or plan.get("generated_sql")
        if sql:
            state["previous_sql"] = str(sql)[:4_000]
        if execution:
            state["previous_result"] = {
                "status": execution.get("status"),
                "row_count": execution.get("row_count"),
                "result_signature": execution.get("result_signature"),
                "columns": list(execution.get("columns") or [])[:30],
            }
        if plan.get("filters"):
            state["filters"] = list(plan["filters"])[:20]
        resolved_datasource = data.get("datasource_id") or state.get("datasource")
        resolved_model = data.get("semantic_model_id") or state.get("semantic_model")
        if resolved_datasource:
            state["datasource"] = resolved_datasource
        if resolved_model:
            state["semantic_model"] = resolved_model
    governed_citations = [
        {
            key: item.get(key)
            for key in ("source", "document_id", "document_version_id", "chunk_id", "locator")
            if item.get(key) is not None
        }
        for item in retrieved_sources
        if any(item.get(key) for key in ("document_id", "document_version_id", "chunk_id"))
    ]
    if governed_citations:
        state["citation"] = governed_citations[:8]
    if attachments:
        state["attachment"] = [
            {"id": item.id, "filename": item.filename, "kind": item.kind}
            for item in attachments[:8]
        ]
    file_analysis = response_payload.get("file_analysis") if isinstance(response_payload, dict) else None
    if isinstance(file_analysis, dict):
        state["file_context"] = {
            key: file_analysis.get(key)
            for key in ("operation", "row_count", "columns", "result_signature", "artifacts")
            if file_analysis.get(key) is not None
        }
    return state


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
    if slots.get("dimensions"):
        parts.append("维度=" + ",".join(map(str, slots["dimensions"])))
    if slots.get("filters"):
        parts.append(f"过滤={len(slots['filters'])}")
    for key, label in (("datasource", "数据源"), ("semantic_model", "语义模型")):
        if slots.get(key):
            parts.append(f"{label}={str(slots[key])[:36]}")
    evidence = [key for key in ("previous_sql", "previous_result", "citation", "attachment", "file_context") if slots.get(key)]
    if evidence:
        parts.append("继承=" + ",".join(evidence))
    conversation.summary = "；".join(parts)
    conversation.slot_state = slots
    conversation.updated_at = datetime.now(timezone.utc)
