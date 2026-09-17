from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx


TOPICS = (
    ("revenue", "收入口径与退款处理", "收入营收销售额退款口径"),
    ("profit", "利润与成本口径", "利润毛利成本口径"),
    ("orders", "订单量与有效订单口径", "订单量订单数有效订单取消口径"),
    ("region", "区域经营维度说明", "地区区域省份经营维度"),
    ("time", "同比环比与时间窗口", "同比环比月份季度年度增长率"),
    ("verification", "ChatBI 可验证结果发布规则", "验证 SQL Guard Result Oracle 引用审计只读"),
)
TEMPLATES = (
    "请说明{keywords}", "{keywords}是什么", "解释一下{keywords}", "给出{keywords}的定义",
    "业务上如何理解{keywords}", "查询前确认{keywords}", "帮我核对{keywords}", "我想了解{keywords}",
    "分析需要遵循哪些{keywords}", "请引用文档说明{keywords}", "{keywords}有哪些规则", "{keywords}采用什么标准",
    "请给出可验证的{keywords}", "数据分析中的{keywords}", "看板应如何使用{keywords}", "问数时怎么处理{keywords}",
    "审计要求下的{keywords}", "请概括{keywords}", "用一句话说明{keywords}", "详细列出{keywords}",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("CHATBI_TEST_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--output")
    args = parser.parse_args()
    results = []
    hits = 0
    citation_passes = 0
    with httpx.Client(base_url=args.base_url, timeout=35.0, trust_env=False) as client:
        capability_response = client.get("/api/v1/query-capabilities")
        capability_response.raise_for_status()
        capabilities = capability_response.json()
        if capabilities["controlled_rag"].get("live_bridge") is not True:
            raise SystemExit("RAG_GOLDEN_120=FAIL LIVE_BRIDGE=UNAVAILABLE")
        for topic, expected_title, keywords in TOPICS:
            for index, template in enumerate(TEMPLATES, 1):
                question = template.format(keywords=keywords)
                response = client.post(
                    "/api/v1/analysis",
                    json={"question": question, "route": "KNOWLEDGE_QUERY"},
                )
                body = response.json()
                citations = body.get("primary", {}).get("citations", [])
                titles = [item.get("title") for item in citations]
                hit = response.status_code == 201 and expected_title in titles[:10]
                citation_ok = bool(
                    body.get("primary", {}).get("answer_guard") == "PASSED"
                    and citations
                    and all(
                        item.get("document_id")
                        and item.get("document_version_id")
                        and item.get("chunk_id")
                        and item.get("source")
                        for item in citations
                    )
                )
                hits += int(hit)
                citation_passes += int(citation_ok)
                results.append(
                    {
                        "case_id": f"RAG-{topic}-{index:02d}",
                        "topic": topic,
                        "status": body.get("status"),
                        "trace_id": body.get("trace_id"),
                        "hit_at_10": hit,
                        "citation_verified": citation_ok,
                        "citation_ids": [item.get("citation_id") for item in citations],
                    }
                )
        unauthorized_leaks = 0
        for index in range(10):
            denied = client.post(
                "/api/v1/analysis",
                headers={"X-ChatBI-Actor": f"unauthorized-{index}@chatbi.invalid"},
                json={"question": "收入营收口径", "route": "KNOWLEDGE_QUERY"},
            )
            if denied.status_code != 401 or "citations" in denied.text:
                unauthorized_leaks += 1

    total = len(results)
    evidence = {
        "suite": "CHATBI_V1_RAG_GOLDEN_120",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": total,
        "recall_at_10": hits / total,
        "citation_accuracy": citation_passes / total,
        "unauthorized_access": unauthorized_leaks,
        "live_bridge": True,
        "workspace_identity_signed": capabilities["controlled_rag"].get("workspace_identity_signed"),
        "passed": hits == total and citation_passes == total and unauthorized_leaks == 0,
        "results": results,
    }
    if args.output:
        _atomic_json(Path(args.output), evidence)
    print(f"RAG_GOLDEN_120={'PASS' if evidence['passed'] else 'FAIL'}")
    print(f"CASES={total} RECALL_AT_10={evidence['recall_at_10']:.4f} CITATION_ACCURACY={evidence['citation_accuracy']:.4f}")
    print(f"UNAUTHORIZED_ACCESS={unauthorized_leaks} LIVE_BRIDGE=PASS WORKSPACE_IDENTITY=PASS")
    raise SystemExit(0 if evidence["passed"] else 1)


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


if __name__ == "__main__":
    main()
