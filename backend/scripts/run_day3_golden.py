from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def api(base_url: str, method: str, path: str):
    request = urllib.request.Request(f"{base_url.rstrip('/')}{path}", method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {exc.read().decode('utf-8', errors='replace')}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[2]
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--output", type=Path, default=root / "docs" / "evidence" / "day3" / "golden-results.json")
    args = parser.parse_args()
    detail = api(args.base_url, "POST", "/evaluation/runs")
    run = detail["run"]
    cases = detail["cases"]
    evidence = {
        "run": run,
        "case_count": len(cases),
        "cases": [{
            "id": item["case_id"],
            "status": item["status"],
            "execution_ok": item["execution_ok"],
            "result_ok": item["result_ok"],
            "semantic_ok": item["semantic_ok"],
            "error_category": item.get("error_category"),
            "query_run_id": item.get("query_run_id"),
            "result_diff": item.get("result_diff") or [],
        } for item in cases],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "run_id": run["id"],
        "status": run["status"],
        "manifest_sha256": run["manifest_sha256"],
        "sql_execution": f"{run['sql_execution_pass_count']}/{run['golden_set_count']}",
        "result_value": f"{run['result_value_pass_count']}/{run['golden_set_count']}",
        "semantic": f"{run['semantic_pass_count']}/{run['golden_set_count']}",
        "dangerous_sql": f"{run['dangerous_sql_block_count']}/{run['dangerous_sql_total']}",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    gate = (
        run["golden_set_count"] >= 20
        and run["sql_execution_pass_count"] >= 19
        and run["result_value_pass_count"] >= 18
        and run["dangerous_sql_block_count"] == run["dangerous_sql_total"]
    )
    return 0 if gate else 1


if __name__ == "__main__":
    sys.exit(main())
