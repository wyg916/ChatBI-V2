from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import httpx


REPO_ROOT = Path(__file__).resolve().parents[2]
PERFORMANCE_ROOT = Path(__file__).resolve().parent
if str(PERFORMANCE_ROOT) not in sys.path:
    sys.path.insert(0, str(PERFORMANCE_ROOT))

from run_v13_phase5_api_load import (  # noqa: E402
    DEFAULT_CORE_DATA_MANIFEST,
    load_core_data_manifest,
    run_core_data100,
)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _git_sha() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    value = completed.stdout.strip().lower()
    return value if completed.returncode == 0 and len(value) == 40 else None


def _require(response: httpx.Response, expected: int = 200) -> Any:
    if response.status_code != expected:
        raise RuntimeError(f"HTTP_{response.status_code}:{response.request.method}:{response.request.url.path}")
    return response.json()


def _resolve_runtime(client: httpx.Client) -> tuple[str, str, dict[str, Any]]:
    sources = _require(client.get("/api/v1/datasources"))
    models = _require(client.get("/api/v1/semantic-models"))
    published_model_by_source = {
        str(item.get("datasource_id")): item
        for item in models
        if item.get("status") == "PUBLISHED" and item.get("datasource_id")
    }
    source = next((
        item for item in sources
        if item.get("type") == "postgresql" and str(item.get("id")) in published_model_by_source
    ), None)
    if source is None:
        raise RuntimeError("LEVEL0_POSTGRESQL_DATASOURCE_MISSING")
    sync_receipt: dict[str, Any] = {
        "performed": False,
        "reason": "catalog_already_present",
        "table_count_before": int(source.get("table_count") or 0),
    }
    if sync_receipt["table_count_before"] == 0:
        sync_result = _require(
            client.post(f"/api/v1/datasources/{source['id']}/sync"),
            expected=200,
        )
        sources = _require(client.get("/api/v1/datasources"))
        source = next((item for item in sources if item.get("id") == source.get("id")), None)
        if source is None:
            raise RuntimeError("LEVEL0_POSTGRESQL_DATASOURCE_DISAPPEARED_AFTER_SYNC")
        sync_receipt.update({
            "performed": True,
            "reason": "empty_catalog",
            "sync_status": sync_result.get("status"),
        })
    table_count_after = int(source.get("table_count") or 0)
    if table_count_after <= 0:
        raise RuntimeError("LEVEL0_POSTGRESQL_SCHEMA_SYNC_EMPTY")
    sync_receipt["table_count_after"] = table_count_after
    sync_receipt["column_count_after"] = int(source.get("column_count") or 0)
    model = published_model_by_source.get(str(source.get("id")))
    if model is None:
        raise RuntimeError("LEVEL0_PUBLISHED_SEMANTIC_MODEL_MISSING")
    return str(source["id"]), str(model["id"]), sync_receipt


def run_level0(
    *,
    base_url: str,
    email: str,
    password: str,
    manifest_path: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    manifest, cases = load_core_data_manifest(manifest_path)
    with httpx.Client(
        base_url=base_url.rstrip("/"),
        timeout=timeout_seconds,
        trust_env=False,
        headers={"User-Agent": "ChatBI-V13-Phase5-Data100-Level0/1.0"},
    ) as client:
        _require(client.post("/api/v1/auth/login", json={
            "email": email,
            "password": password,
            "remember": False,
        }))
        provider_catalog = _require(client.get("/api/v1/model-providers"))
        active_provider = str(provider_catalog.get("active_provider") or "")
        if active_provider != "deterministic":
            raise RuntimeError(f"LEVEL0_REQUIRES_DETERMINISTIC_PROVIDER:{active_provider or 'unknown'}")
        datasource_id, semantic_model_id, schema_sync = _resolve_runtime(client)
        result = run_core_data100(
            client,
            cases,
            datasource_id=datasource_id,
            semantic_model_id=semantic_model_id,
        )
        logout = client.post("/api/v1/auth/logout")
        if logout.status_code != 204:
            raise RuntimeError(f"LEVEL0_LOGOUT_HTTP_{logout.status_code}")
    return {
        "schema_version": "chatbi-v1.3-phase5-data100-level0-v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "tested_sha": _git_sha(),
        "test_level": "LEVEL0",
        "provider_mode": "deterministic",
        "paid_provider_calls": 0,
        "paid_test_cost_cny": 0.0,
        "manifest": {
            "path": str(manifest_path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/"),
            "sha256": manifest["manifest_sha256"],
            "case_count": len(cases),
        },
        "schema_sync": schema_sync,
        "core_data100": result,
        "status": "PASS" if result.get("status") == "PASS" else "FAIL",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the zero-paid ChatBI Phase5 Data100 gate")
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_CORE_DATA_MANIFEST)
    parser.add_argument("--email", default="admin@chatbi.local")
    parser.add_argument("--password-env", default="CHATBI_BOOTSTRAP_ADMIN_PASSWORD")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    password = os.getenv(args.password_env, "")
    if not password:
        raise SystemExit(f"MISSING_PASSWORD_ENV:{args.password_env}")
    payload = run_level0(
        base_url=args.base_url,
        email=args.email,
        password=password,
        manifest_path=args.manifest,
        timeout_seconds=args.timeout_seconds,
    )
    _atomic_json(args.output, payload)
    result = payload["core_data100"]
    print(json.dumps({
        "status": payload["status"],
        "tested_sha": payload["tested_sha"],
        "data100": f"{result['passed']}/{result['total']}",
        "result_value_accuracy": result["result_value_accuracy"],
        "paid_provider_calls": 0,
        "output": str(args.output.resolve()),
    }, ensure_ascii=False, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
