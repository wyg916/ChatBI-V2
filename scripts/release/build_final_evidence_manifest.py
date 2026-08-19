"""Seal raw release evidence after every gate ran on one frozen SHA."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BRANCH_REF = "refs/heads/codex/v2.1-final-integration"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _test_count(path: Path, pattern: str) -> int:
    if not path.exists():
        return 0
    matches = re.findall(pattern, path.read_text(encoding="utf-8", errors="replace"), flags=re.IGNORECASE)
    return int(matches[-1]) if matches else 0


def _command_ok(commands: list[dict], name: str) -> bool:
    return any(item.get("name") == name and item.get("exit_code") == 0 for item in commands)


def _vulnerability_count(payload: dict) -> int:
    """Accept the native JSON shapes emitted by npm audit and pip-audit."""
    metadata = payload.get("metadata") or {}
    vulnerabilities = metadata.get("vulnerabilities") or {}
    if isinstance(vulnerabilities, dict) and "total" in vulnerabilities:
        return int(vulnerabilities.get("total") or 0)
    dependencies = payload.get("dependencies") or []
    if isinstance(dependencies, list):
        return sum(len(item.get("vulns") or []) for item in dependencies if isinstance(item, dict))
    return -1


def _stage_pass(load: dict, name: str, threshold_ms: float | None = None) -> bool:
    stage = (load.get("stage_latency") or {}).get(name) or {}
    if int(stage.get("samples") or 0) <= 0:
        return False
    return threshold_ms is None or float(stage.get("p95_ms", 999999)) <= threshold_ms


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    evidence_root = args.evidence_root.resolve()
    output = (args.output or evidence_root / "FINAL_EVIDENCE_MANIFEST.json").resolve()

    tested_sha = _git("rev-parse", "HEAD")
    remote_tracking_sha = _git("rev-parse", "origin/codex/v2.1-final-integration")
    ls_remote = _git("ls-remote", "origin", BRANCH_REF).split()
    remote_sha = ls_remote[0] if ls_remote else ""
    tracked_dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    commands_path = evidence_root / "commands.json"
    commands = json.loads(commands_path.read_text(encoding="utf-8-sig")) if commands_path.exists() else []

    performance = _json(evidence_root / "performance.json")
    security = _json(evidence_root / "security.json")
    open_questions = _json(evidence_root / "open-questions.json")
    memory = _json(evidence_root / "memory-30x5.json")
    migration = _json(evidence_root / "migration.json")
    cold1 = _json(evidence_root / "cold-start-run1.json")
    cold2 = _json(evidence_root / "cold-start-run2.json")
    consecutive = _json(evidence_root / "consecutive-starts.json")
    golden = _json(evidence_root / "golden50.json")
    npm_audit = _json(evidence_root / "npm-audit.json")
    pip_audit = _json(evidence_root / "pip-audit.json")
    capability_matrix = _json(ROOT / "docs/v2_1/day3/V2_1_FINAL_CAPABILITY_MATRIX.json")
    capability_evidence = _json(ROOT / "docs/CAPABILITY_EVIDENCE_MANIFEST.json")
    upstream_lock = _json(ROOT / "docs/UPSTREAM_LOCK.json")
    cyclonedx = _json(ROOT / "docs/sbom/V1_1_0.cdx.json")
    spdx = _json(ROOT / "docs/sbom/V1_1_0.spdx.json")
    agent_manifest = _json(ROOT / "evaluation/golden/v2.1-agent-15.json")
    knowledge_manifest = _json(ROOT / "evaluation/golden/v2.1-knowledge-20.json")
    file_manifest = _json(ROOT / "evaluation/golden/v2.1-file-10.json")
    load = performance["load"]
    database = performance["database"]
    open_metrics = open_questions["open_questions"]
    memory_metrics = memory["memory"]

    backend_tests = _test_count(evidence_root / "backend-tests.log", r"(\d+)\s+passed")
    frontend_tests = _test_count(evidence_root / "frontend-tests.log", r"Tests\s+(\d+)\s+passed")
    e2e_tests = _test_count(evidence_root / "e2e.log", r"(\d+)\s+passed")
    target_tests = _test_count(evidence_root / "product-targeted-tests.log", r"(\d+)\s+passed")
    required_files = {
        "commands.json", "backend-tests.log", "product-targeted-tests.log",
        "frontend-typecheck.log", "frontend-tests.log", "frontend-build.log", "e2e.log",
        "open-questions.json", "memory-30x5.json", "golden50.json", "security.json",
        "performance.json", "performance.csv", "migration.json", "cold-start-run1.json",
        "cold-start-run2.json", "consecutive-starts.json", "npm-audit.json", "pip-audit.json",
    }
    required_routes = {
        "DATA_QUERY", "KNOWLEDGE_QUERY", "HYBRID_ANALYSIS", "COMPLEX_ANALYSIS",
        "FILE_QUERY", "SQL_WORKSPACE", "FEEDBACK", "EVALUATION",
    }
    route_counts = load.get("routes") or {}
    capabilities = capability_matrix.get("capabilities") or []
    upstream_projects = upstream_lock.get("projects") or []
    required_upstreams = {
        "WrenAI", "OpenChatBI", "SuperSonic", "IBM Text-to-SQL Evaluation Toolkit",
        "SQLBot", "Chat2DB", "DB-GPT", "PandasAI",
    }
    third_party_notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8-sig")
    supply_chain = security.get("supply_chain") or {}
    spdx_packages = spdx.get("packages") or []

    checks = {
        "sha_local_remote_equal": tested_sha == remote_tracking_sha == remote_sha,
        "tracked_worktree_clean": not tracked_dirty,
        "commands_all_zero": bool(commands) and all(item.get("exit_code") == 0 for item in commands),
        "required_evidence_files": all((evidence_root / name).is_file() for name in required_files),
        "backend_tests": backend_tests > 0 and _command_ok(commands, "backend-tests"),
        "frontend_typecheck": _command_ok(commands, "frontend-typecheck"),
        "frontend_tests": frontend_tests > 0 and _command_ok(commands, "frontend-tests"),
        "frontend_build": _command_ok(commands, "frontend-build"),
        "e2e": e2e_tests >= 30 and _command_ok(commands, "e2e"),
        "product_targeted_tests": target_tests > 0 and _command_ok(commands, "product-targeted-tests"),
        "capability_matrix": len(capabilities) == 18
        and all(item.get("PRODUCT_PASS") == "YES" and item.get("RUNTIME_CALL_RATE") == 1.0 for item in capabilities),
        "capability_evidence_manifest": capability_evidence.get("schema_version") is not None
        and len(capability_evidence.get("capabilities") or []) == 18
        and len({item.get("id") for item in capability_evidence.get("capabilities") or []}) == 18
        and all(
            all((ROOT / path).is_file() for path in item.get("tracked_evidence") or [])
            and all(path in required_files for path in item.get("final_evidence") or [])
            for item in capability_evidence.get("capabilities") or []
        ),
        "agent_product": len(agent_manifest.get("cases") or []) >= 15,
        "knowledge_product": len(knowledge_manifest.get("cases") or []) >= 20,
        "file_product": len(file_manifest.get("cases") or []) >= 10,
        "open_questions": open_metrics.get("total", 0) >= 100
        and open_metrics.get("hardcoded_answer_paths") == 0
        and open_metrics.get("open_ended_request_runtime_rate") == 1.0
        and open_metrics.get("question_route_coverage_rate") == 1.0
        and open_metrics.get("trace_complete_rate") == 1.0
        and open_metrics.get("unsupported_request_hallucination") == 0
        and not open_metrics.get("cleanup_failures"),
        "memory": memory_metrics.get("conversation_count", 0) >= 30
        and memory_metrics.get("turn_count", 0) >= 150
        and memory_metrics.get("follow_up_context_accuracy", 0) >= 0.95
        and memory_metrics.get("conversation_persistence") is True
        and memory_metrics.get("history_recovery") is True
        and memory_metrics.get("new_conversation_reset") is True
        and memory_metrics.get("cross_conversation_memory_leak") == 0
        and not memory_metrics.get("cleanup_failures"),
        "golden": golden.get("golden_count") >= 50
        and golden.get("sql_execution_rate") >= 0.98
        and golden.get("result_value_accuracy") >= 0.95
        and golden.get("dangerous_sql_block_rate") == 1.0
        and golden.get("feedback_replay_rate") == 1.0,
        "security": bool(security.get("final_pass"))
        and security.get("sql", {}).get("block_rate") == 1.0
        and security.get("business_database", {}).get("write_count") == 0
        and security.get("business_database", {}).get("before") == security.get("business_database", {}).get("after"),
        "security_authentication": security.get("authentication", {}).get("unauthorized_success") == 0
        and security.get("authentication", {}).get("passed") == security.get("authentication", {}).get("total"),
        "security_attachments": security.get("attachments", {}).get("malicious_attachment_execution") == 0
        and security.get("attachments", {}).get("passed") == security.get("attachments", {}).get("total"),
        "security_rag": security.get("rag", {}).get("all_attacks_passed") is True
        and security.get("rag", {}).get("unauthorized_recall") == 0
        and security.get("rag", {}).get("cross_scenario_recall") == 0
        and security.get("rag", {}).get("prompt_injection_evidence_used") == 0
        and security.get("rag", {}).get("citation_accuracy") == 1.0,
        "security_agent": security.get("agent", {}).get("all_attacks_passed") is True
        and all(
            security.get("agent", {}).get(key) == 0
            for key in (
                "agent_direct_db_access", "sql_guard_bypass", "result_oracle_bypass",
                "unauthorized_tool_call", "infinite_agent_loop", "cross_workspace_leak",
            )
        ),
        "security_sandbox": security.get("sandbox", {}).get("sandbox_escape") == 0
        and all(
            security.get("sandbox", {}).get("policy", {}).get(key) == 0
            for key in (
                "generated_code_execution", "host_filesystem_access", "database_credential_access",
                "provider_secret_access", "network_access", "shell_access",
            )
        ),
        "dependency_audits": _command_ok(commands, "npm-audit")
        and _command_ok(commands, "pip-audit")
        and _vulnerability_count(npm_audit) == 0
        and _vulnerability_count(pip_audit) == 0,
        "secret_scan": supply_chain.get("secret_scan") == "PASS"
        and supply_chain.get("secret_hit_count") == 0,
        "upstream_lock": {item.get("name") for item in upstream_projects} == required_upstreams
        and all(
            re.fullmatch(r"[0-9a-f]{40}", str(item.get("commit") or ""))
            and str(item.get("repository") or "").startswith("https://github.com/")
            and str(item.get("checksum") or "").startswith("sha256:")
            and item.get("license_files")
            and item.get("runtime_entry")
            and item.get("rollback")
            for item in upstream_projects
        ),
        "license_audit": supply_chain.get("license_audit_present") is True
        and supply_chain.get("unknown_license_count") == 0
        and supply_chain.get("spdx_noassertion_license_count") == 0
        and (ROOT / "docs/OPEN_SOURCE_LICENSE_AUDIT.md").stat().st_size > 1000,
        "third_party_notices": all(name.lower() in third_party_notices.lower() for name in required_upstreams)
        and (ROOT / "LICENSE").is_file(),
        "sbom": supply_chain.get("sbom_present") is True
        and cyclonedx.get("bomFormat") == "CycloneDX"
        and cyclonedx.get("specVersion") == "1.6"
        and len(cyclonedx.get("components") or []) >= 300
        and spdx.get("spdxVersion") == "SPDX-2.3"
        # SPDX contains the ChatBI application package in addition to the
        # dependency packages represented by CycloneDX `components`.
        and len(spdx_packages) == len(cyclonedx.get("components") or []) + 1
        and all(item.get("licenseConcluded") != "NOASSERTION" for item in spdx_packages),
        "performance": performance.get("release_gate", {}).get("enforced") is True
        and performance.get("release_gate", {}).get("pass") is True
        and load.get("concurrency") == 20
        and load.get("actual_duration_seconds", 0) >= 900
        and load.get("error_rate", 1) < 0.01
        and load.get("ttfe_p95_ms", 999999) <= 1000
        and load.get("heartbeat_max_gap_ms", 999999) <= 3000
        and load.get("over_10s_streaming_rate") == 1.0
        and load.get("cancellation", {}).get("cleanup_ms", 999999) <= 5000
        and load.get("db_connection_leak") == 0
        and load.get("memory_leak") == 0
        and load.get("sse_connection_leak") == 0
        and load.get("background_task_leak") == 0
        and load.get("cross_workspace_cache_leak") == 0
        and database.get("simple", {}).get("p95_ms", 999999) <= 5000
        and database.get("standard", {}).get("p95_ms", 999999) <= 10000
        and database.get("complex", {}).get("p95_ms", 999999) <= 30000
        and database.get("advanced", {}).get("p95_ms", 999999) <= 60000
        and required_routes.issubset({name for name, count in route_counts.items() if int(count or 0) > 0})
        and load.get("workspace_count", 0) >= 2
        and load.get("authenticated_user_count", 0) >= 2
        and load.get("cache_hits", 0) > 0
        and load.get("cache_misses", 0) > 0
        and load.get("planned_disconnects", 0) > 0
        and load.get("planned_disconnect_failures", 1) == 0
        and load.get("unauthenticated_sse_401") is True
        and _stage_pass(load, "catalog", 1000)
        and _stage_pass(load, "semantic_parse", 1500)
        and _stage_pass(load, "wren_compile", 2000)
        and _stage_pass(load, "oracle"),
        "migration": migration.get("single_head") is True
        and migration.get("upgrade_base_upgrade_pass") is True
        and migration.get("temporary_schema_removed") is True
        and not migration.get("failures")
        and not migration.get("blockers"),
        "cold_start_run1": cold1.get("cold_start") == "PASS",
        "cold_start_run2": cold2.get("cold_start") == "PASS",
        "consecutive_starts": consecutive.get("consecutive_start") == "PASS"
        and consecutive.get("one_click_start") == "PASS"
        and consecutive.get("run_count") == 2,
    }
    failures = sorted(name for name, passed in checks.items() if not passed)
    blockers = list(failures)
    evidence = []
    for path in sorted(evidence_root.rglob("*")):
        if path.is_file() and path.resolve() != output:
            evidence.append(
                {
                    "path": path.relative_to(evidence_root).as_posix(),
                    "sha256": _hash(path),
                    "bytes": path.stat().st_size,
                }
            )
    manifest = {
        "schema_version": "v2.1-final-evidence-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tested_sha": tested_sha,
        "remote_tracking_sha": remote_tracking_sha,
        "remote_sha": remote_sha,
        "branch": "codex/v2.1-final-integration",
        "commands": commands,
        "test_counts": {
            "backend": backend_tests,
            "frontend": frontend_tests,
            "e2e": e2e_tests,
            "product_targeted": target_tests,
            "open_questions": open_metrics.get("total"),
            "memory_conversations": memory_metrics.get("conversation_count"),
            "memory_turns": memory_metrics.get("turn_count"),
            "golden": golden.get("golden_count"),
            "security_attacks": security.get("attack_case_count"),
            "agent_cases": len(agent_manifest.get("cases") or []),
            "knowledge_cases": len(knowledge_manifest.get("cases") or []),
            "file_cases": len(file_manifest.get("cases") or []),
        },
        "actual_metrics": {
            "open_questions": open_metrics,
            "memory": memory_metrics,
            "golden": golden,
            "security_summary": {
                "attack_case_count": security.get("attack_case_count"),
                "dangerous_sql_block_rate": security.get("sql", {}).get("block_rate"),
                "business_database_write_count": security.get("business_database", {}).get("write_count"),
                "sandbox_escape": security.get("sandbox", {}).get("sandbox_escape"),
                "unauthorized_tool_call": security.get("agent", {}).get("unauthorized_tool_call"),
                "unknown_license_dependencies": security.get("supply_chain", {}).get("unknown_license_count"),
            },
            "performance": {"database": database, "load": {key: value for key, value in load.items() if key != "resource_samples"}},
            "migration": migration,
            "cold_starts": [cold1, cold2],
            "consecutive_starts": consecutive,
            "dependency_audits": {
                "npm_vulnerabilities": _vulnerability_count(npm_audit),
                "python_vulnerabilities": _vulnerability_count(pip_audit),
            },
        },
        "checks": checks,
        "evidence": evidence,
        "evidence_hash": hashlib.sha256(
            "\n".join(f"{item['path']}:{item['sha256']}" for item in evidence).encode("utf-8")
        ).hexdigest(),
        "failures": failures,
        "blockers": blockers,
        "final_status": "PASS" if not blockers else "PARTIAL",
        "release_ready": not blockers,
        "main_pushed": False,
        "tag_created": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({key: manifest[key] for key in ("tested_sha", "remote_sha", "test_counts", "checks", "failures", "blockers", "final_status", "release_ready")}, ensure_ascii=False, indent=2))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
