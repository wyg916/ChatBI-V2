from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import load_dotenv


async def collect_case(client: httpx.AsyncClient, case: dict, datasource_id: str, semantic_model_id: str) -> list[dict]:
    conversation = await client.post("/conversations", json={"title": f"Day1 {case['case_id']}"})
    conversation.raise_for_status()
    conversation_id = conversation.json()["id"]
    events: list[dict] = []
    try:
        async with client.stream(
            "POST",
            "/chat/stream",
            json={
                "conversation_id": conversation_id,
                "client_message_id": f"day1-{case['case_id']}-{uuid4()}",
                "content": case["question"],
                "route": "DATA_QUERY",
                "attachment_ids": [],
                "datasource_id": datasource_id,
                "semantic_model_id": semantic_model_id,
            },
            timeout=90.0,
        ) as response:
            response.raise_for_status()
            event_name = ""
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and event_name not in {"progress", "result"}:
                    payload = json.loads(line.split(":", 1)[1].strip())
                    if isinstance(payload, dict) and "trace_id" in payload:
                        events.append(payload)
    finally:
        await client.delete(f"/conversations/{conversation_id}")
    return events


async def run(args: argparse.Namespace) -> dict:
    report = json.loads(args.input.read_text(encoding="utf-8"))
    password = os.environ.get("CHATBI_BOOTSTRAP_ADMIN_PASSWORD", "")
    if not password:
        raise SystemExit("CHATBI_BOOTSTRAP_ADMIN_PASSWORD is required")
    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), timeout=90.0, trust_env=False) as client:
        login = await client.post(
            "/auth/login",
            json={"email": "admin@chatbi.local", "password": password, "remember": False},
        )
        login.raise_for_status()
        for case in report["cases"]:
            case["sse_events"] = await collect_case(
                client, case, report["datasource_id"], report["semantic_model_id"],
            )
    incomplete = [
        case["case_id"]
        for case in report["cases"]
        if not case["sse_events"]
        or case["sse_events"][0].get("event") != "accepted"
        or case["sse_events"][-1].get("event") not in {"completed", "error", "cancelled"}
    ]
    report["sse_evidence"] = {
        "case_count": len(report["cases"]),
        "complete_case_count": len(report["cases"]) - len(incomplete),
        "incomplete_cases": incomplete,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    args = parser.parse_args()
    load_dotenv(args.env_file, override=True)
    report = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["sse_evidence"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
