from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def api(base_url: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=payload,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with OPENER.open(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {detail}") from exc


def local_secret(root: Path, key: str) -> str:
    if value := os.environ.get(key):
        return value
    env_path = root / ".env"
    if not env_path.exists():
        return ""
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        name, separator, value = raw_line.partition("=")
        if separator and name.strip() == key:
            return value.strip().strip("\"'")
    return ""


def prepare_catalog(base_url: str) -> None:
    sources = api(base_url, "GET", "/datasources")
    for dialect in ("postgresql", "mysql"):
        source = next((item for item in sources if item.get("type") == dialect), None)
        if source is None:
            raise RuntimeError(f"Missing {dialect} datasource")
        connection = api(base_url, "POST", f"/datasources/{source['id']}/test")
        if not connection.get("success"):
            raise RuntimeError(f"{dialect} readonly connection test failed")
        sync = api(base_url, "POST", f"/datasources/{source['id']}/sync")
        if not sync.get("success"):
            raise RuntimeError(f"{dialect} schema sync failed")


def main() -> int:
    parser = argparse.ArgumentParser(description="ChatBI V2.1 evaluation and feedback release gate")
    root = Path(__file__).resolve().parents[2]
    parser.add_argument("--api-base", default="http://127.0.0.1:18080/api/v1")
    parser.add_argument("--email", default="admin@chatbi.local")
    parser.add_argument("--run-id")
    parser.add_argument("--require-feedback", action="store_true")
    parser.add_argument("--output", type=Path, default=root / "docs" / "evidence" / "v2.1" / "eval-feedback-release-gate.json")
    args = parser.parse_args()

    password = local_secret(root, "CHATBI_BOOTSTRAP_ADMIN_PASSWORD")
    if not password:
        raise RuntimeError("Missing CHATBI_BOOTSTRAP_ADMIN_PASSWORD for authenticated release gate")
    api(args.api_base, "POST", "/auth/login", {"email": args.email, "password": password})
    prepare_catalog(args.api_base)
    run_id = args.run_id
    if not run_id:
        created = api(args.api_base, "POST", "/evaluation/definitions", {
            "name": "ChatBI V2.1 CI Golden 50",
            "profile": {
                "model": "deterministic",
                "prompt": "chatbi-eval-v2.1",
                "semantic_engine": "chatbi-semantic",
                "nl2sql_engine": "chatbi-nl2sql",
                "version": "v2.1",
            },
        })
        run_id = created["id"]
        executed = api(args.api_base, "POST", f"/evaluation/runs/{run_id}/execute")
    else:
        executed = api(args.api_base, "GET", f"/evaluation/runs/{run_id}")
    gate = api(args.api_base, "GET", f"/evaluation/runs/{run_id}/gate")
    dashboard = api(args.api_base, "GET", f"/evaluation/dashboard?run_id={run_id}")
    feedback = api(args.api_base, "GET", "/evaluation/feedback/dashboard")

    accuracy = executed["run"].get("accuracy") or {}
    accuracy_complete = set(accuracy) == {"metric", "dimension", "time", "filter", "join", "result_value", "chart", "narrative"}
    accuracy_pass = accuracy_complete and all(float(value) >= 0.95 for value in accuracy.values())
    feedback_pass = (
        feedback["total_replays"] >= 1 and feedback["feedback_replay_rate"] == 1.0
        if args.require_feedback else True
    )
    passed = bool(
        gate["status"] == "PASS"
        and executed["run"].get("multiple_ground_truth")
        and accuracy_pass
        and len(dashboard["accuracy_cards"]) == 8
        and feedback_pass
    )
    report = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "status": "PASS" if passed else "FAIL",
        "golden_count": int(gate["metrics"]["golden_count"]),
        "sql_execution_rate": gate["metrics"]["sql_execution_rate"],
        "result_value_accuracy": gate["metrics"]["result_value_accuracy"],
        "dangerous_sql_block_rate": gate["metrics"]["dangerous_sql_block_rate"],
        "multiple_ground_truth": executed["run"].get("multiple_ground_truth", False),
        "accuracy": accuracy,
        "feedback_total_replays": feedback["total_replays"],
        "feedback_replay_rate": feedback["feedback_replay_rate"],
        "checks": {
            "evaluation_gate": gate["status"] == "PASS",
            "multiple_ground_truth": bool(executed["run"].get("multiple_ground_truth")),
            "eight_accuracy_dimensions": accuracy_pass,
            "evaluation_dashboard": len(dashboard["accuracy_cards"]) == 8,
            "feedback_replay": feedback_pass,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
