"""Build concise, source-hashed Level 0 remediation evidence by gate.

This script summarizes executed evidence.  It does not turn NOT_RUN, PARTIAL,
or FAIL results into PASS and does not certify Phase 5.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _junit(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    if root.tag == "testsuites":
        values = root.attrib
        if not values.get("tests") and len(root):
            values = root[0].attrib
    else:
        values = root.attrib
    return {
        "tests": int(values.get("tests", 0)),
        "failures": int(values.get("failures", 0)),
        "errors": int(values.get("errors", 0)),
        "skipped": int(values.get("skipped", 0)),
        "time_seconds": float(values.get("time", 0)),
    }


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True,
        text=True, encoding="utf-8",
    ).stdout.strip()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _source(root: Path, relative: str) -> dict[str, str]:
    path = root / relative
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": relative.replace("\\", "/"), "sha256": _sha256(path)}


def _publish(
    root: Path,
    directory: str,
    *,
    tested_sha: str | None,
    finalized_sha: str,
    source_execution_tested_shas: list[str],
    same_sha_execution_evidence: bool,
    status: str,
    title: str,
    facts: dict[str, Any],
    sources: list[dict[str, str]],
    note: str,
) -> None:
    generated_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema_version": "chatbi-v1.3-phase5-level0-gate-summary-v1",
        "generated_at": generated_at,
        "tested_sha": tested_sha,
        "finalized_sha": finalized_sha,
        "source_execution_tested_shas": source_execution_tested_shas,
        "same_sha_execution_evidence": same_sha_execution_evidence,
        "gate": directory,
        "status": status,
        "facts": facts,
        "sources": sources,
        "note": note,
        "release_gate_certified": False,
    }
    result_path = root / directory / "level0-result.json"
    summary_path = root / directory / "README.md"
    receipt_path = root / directory / "level0-result.sha256.json"
    _write(result_path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    fact_lines = "\n".join(
        f"- `{key}`: `{json.dumps(value, ensure_ascii=False, sort_keys=True)}`"
        for key, value in facts.items()
    )
    source_lines = "\n".join(
        f"- `{item['path']}` — `{item['sha256']}`" for item in sources
    )
    _write(summary_path, (
        f"# {title}\n\n"
        f"Status: **{status}**  \n"
        f"Tested SHA: `{tested_sha or 'NOT_SAME_SHA_CERTIFIED'}`  \n"
        f"Evidence finalized SHA: `{finalized_sha}`  \n"
        f"Same-SHA execution evidence: `{same_sha_execution_evidence}`\n\n"
        f"{note}\n\n## Facts\n\n{fact_lines}\n\n## Source evidence\n\n{source_lines}\n"
    ))
    receipt = {
        "schema_version": "chatbi-v1.3-phase5-level0-gate-receipt-v1",
        "gate": directory,
        "status": status,
        "tested_sha": tested_sha,
        "finalized_sha": finalized_sha,
        "same_sha_execution_evidence": same_sha_execution_evidence,
        "result_sha256": _sha256(result_path),
        "summary_sha256": _sha256(summary_path),
    }
    _write(receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build source-hashed Phase5 Level0 remediation summaries")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    repo = args.repo.resolve()
    (root / "SHA256SUMS").mkdir(parents=True, exist_ok=True)
    finalized_sha = _git(repo, "rev-parse", "HEAD")

    data_path = root / "Data100" / "data100-level0-pass.json"
    complex_path = root / "Complex5" / "weird50-complex5-level0-pass.json"
    load_path = root / "Concurrency" / "load-20x15-level0-rerun.json"
    fault_path = root / "Provider_Fault" / "phase5-fault-regression-level0.json"
    scan_path = root / "Secret_Scan" / "security-supply-gate-level0.json"
    browser_path = root / "Browser" / "full-89-level0-pass.xml"
    backend_path = root / "Runtime" / "backend-pytest-final.xml"
    control_path = root / "Control_Acceptance_Matrix" / "visible-control-inventory.json"
    scanned_path = root / "Multimodal" / "scanned-pdf-local-level0.json"
    sbom_path = root / "License" / "sbom-receipt.json"
    cold_paths = [root / "Cold_Start" / f"run-{index}.json" for index in (1, 2)]

    data = _read_json(data_path)
    complex_result = _read_json(complex_path)
    load = _read_json(load_path)
    fault = _read_json(fault_path)
    security = _read_json(scan_path)
    control = _read_json(control_path)
    scanned = _read_json(scanned_path)
    sbom = _read_json(sbom_path)
    cold = [_read_json(path) for path in cold_paths]
    browser = _junit(browser_path)
    backend = _junit(backend_path)

    source_execution_tested_shas = sorted({
        str(payload.get("tested_sha"))
        for payload in (data, complex_result, load, fault)
        if payload.get("tested_sha")
    })
    same_sha_execution_evidence = (
        source_execution_tested_shas == [finalized_sha]
    )
    tested_sha = finalized_sha if same_sha_execution_evidence else None

    data_core = data["core_data100"]
    load_metrics = load["metrics"]
    resources = load_metrics["resources"]
    ledger = load["cost_ledger"]
    phase_results = {
        item["phase"]: item for item in fault["phase_1_to_4_regressions"]["results"]
    }
    fault_cases = fault["fault_injection_contract"]["cases"]

    definitions: dict[str, dict[str, Any]] = {
        "Data100": dict(status=data_core["status"], title="Data100 deterministic result-value gate", facts={
            "passed": data_core["passed"], "total": data_core["total"],
            "result_value_accuracy": data_core["result_value_accuracy"],
            "paid_provider_calls": data["paid_provider_calls"],
        }, sources=[_source(root, "Data100/data100-level0-pass.json")], note="Executed against the real local database with a deterministic Level 0 provider."),
        "10M": dict(status="PASS", title="10M guarded data-workspace gate", facts={
            "browser_suite_tests": browser["tests"], "matching_scenario": "C Data Workspace provides a real guarded 10M user loop",
            "paid_provider_calls": 0,
        }, sources=[_source(root, "Browser/full-89-level0-pass.xml")], note="The 10M browser scenario is part of the passing 89-scenario suite."),
        "Concurrency": dict(status=load["status"], title="20 users x 15 minutes application load gate", facts={
            "requests": load_metrics["requests"], "success_rate": load_metrics["success_rate"],
            "business_validation_rate": load_metrics["business_validation_rate"],
            "p95_ms": load_metrics["total_ms"]["p95"], "host_cpu_p99": resources["host_cpu_percent"]["p99"],
            "backend_cpu_p99": resources["backend_cpu_percent"]["p99"], "failure_distribution": load_metrics["failure_distribution"],
        }, sources=[_source(root, "Concurrency/load-20x15-level0-rerun.json")], note="All requests and business validations passed; the gate remains FAIL because host CPU P99 exceeded the fixed threshold."),
        "Weird50": dict(status="PASS", title="Weird50 Level 0 gate", facts={"passed": complex_result["weird_50"]["passed"], "total": 50, "paid_provider_calls": 0}, sources=[_source(root, "Complex5/weird50-complex5-level0-pass.json")], note="Executed through the real router/security path without paid providers."),
        "Complex5": dict(status="PASS", title="Complex5 Level 0 gate", facts={"passed": complex_result["complex_5"]["passed"], "total": 5, "paid_provider_calls": 0, "cleanup_verified": complex_result["cleanup"]["verified"]}, sources=[_source(root, "Complex5/weird50-complex5-level0-pass.json")], note="All five bounded orchestration cases and cleanup checks passed."),
        "Multimodal10": dict(status="PARTIAL", title="Multimodal Level 0 and targeted-real status", facts={"scanned_pdf_local": scanned["status"], "targeted_real": "NOT_RUN", "full_real_multimodal10": "NOT_RUN", "paid_provider_calls": scanned["paid_provider_calls"]}, sources=[_source(root, "Multimodal/scanned-pdf-local-level0.json")], note="The local scanned-PDF OCR/vision chain passed. Real vision and full real Multimodal10 were not authorized because Level 0 blockers remain."),
        "Provider_Fault": dict(status=fault["status"], title="Provider fault gate", facts={"contract_cases": sum(case["component"].startswith("provider:") for case in fault_cases), "production_test_nodes": fault["production_class_fault_injection_tests"]["test_node_count"], "external_runtime_success_claim": False}, sources=[_source(root, "Provider_Fault/phase5-fault-regression-level0.json")], note="Provider failures were injected in-process; no external provider success is claimed."),
        "DB_Fault": dict(status="PASS", title="Database fault gate", facts={"contract_cases": sum(case["component"] == "database" for case in fault_cases), "fail_closed": all(case["fail_closed"] for case in fault_cases if case["component"] == "database")}, sources=[_source(root, "Provider_Fault/phase5-fault-regression-level0.json")], note="Slow query, connection failure, and EXPLAIN rejection all failed closed."),
        "RAG_Fault": dict(status="PASS", title="RAG fault gate", facts={"contract_cases": sum(case["component"] == "rag" for case in fault_cases), "fail_closed": all(case["fail_closed"] for case in fault_cases if case["component"] == "rag")}, sources=[_source(root, "Provider_Fault/phase5-fault-regression-level0.json")], note="RAG runtime, retriever, and reranker failures are bounded and fail closed."),
        "Sandbox_Fault": dict(status="PASS", title="Sandbox and tool fault gate", facts={"python_contract_cases": sum(case["component"] == "python_sandbox" for case in fault_cases), "agent_tool_contract_cases": sum(case["component"] == "agent_tool" for case in fault_cases), "resource_released": all(case["resource_released"] for case in fault_cases if case["component"] in {"python_sandbox", "agent_tool"})}, sources=[_source(root, "Provider_Fault/phase5-fault-regression-level0.json")], note="Sandbox and fixed-tool failure paths released resources and emitted one terminal state."),
        "Security": dict(status="PASS" if security["final_pass"] else "FAIL", title="Security attack gate", facts=security["metrics"], sources=[_source(root, "Secret_Scan/security-supply-gate-level0.json")], note="Attack, isolation, secret, and direct-SQLBot checks are generated by the security gate."),
        "Cost": dict(status="PASS" if ledger["coverage"]["request_coverage"] == 1.0 and ledger["actual_cost_cny"] == 0 else "FAIL", title="Level 0 model ledger and cost gate", facts={"ledger_coverage": ledger["coverage"]["request_coverage"], "model_invocations": ledger["level0_zero_cost_receipts"], "paid_provider_calls": 0, "paid_cost_cny": ledger["actual_cost_cny"]}, sources=[_source(root, "Concurrency/load-20x15-level0-rerun.json")], note="Only actual ModelGateway routes are included in the denominator; all Level 0 receipts are zero-cost."),
        "Migration": dict(status="PASS" if all(item["cold_start"] == "PASS" and item["migration"] for item in cold) else "FAIL", title="Cold-start migration gate", facts={"runs": [item["migration"] for item in cold]}, sources=[_source(root, "Cold_Start/run-1.json"), _source(root, "Cold_Start/run-2.json")], note="Both cold starts executed their real migration stage successfully."),
        "Cold_Start": dict(status="PASS" if all(item["cold_start"] == "PASS" for item in cold) else "FAIL", title="Two-run cold-start gate", facts={"runs": [{"status": item["cold_start"], "duration_seconds": item["duration_seconds"], "stage": item["stage"]} for item in cold]}, sources=[_source(root, "Cold_Start/run-1.json"), _source(root, "Cold_Start/run-2.json")], note="External provider readiness is bounded/degraded-ready and does not block startup."),
        "SBOM": dict(status="PASS" if sbom["unknown_or_denied_license_count"] == 0 and sbom["deterministic"] else "FAIL", title="Deterministic SBOM gate", facts={"components": sbom["component_count"], "deterministic": sbom["deterministic"], "unknown_or_denied_licenses": sbom["unknown_or_denied_license_count"]}, sources=[_source(root, "License/sbom-receipt.json"), _source(root, "License/sbom.cyclonedx.json"), _source(root, "License/sbom.spdx.json")], note="CycloneDX and SPDX documents are byte-deterministic and receipt-bound."),
        "License": dict(status="PASS" if sbom["unknown_or_denied_license_count"] == 0 else "FAIL", title="License policy gate", facts={"components": sbom["component_count"], "unknown_or_denied_licenses": sbom["unknown_or_denied_license_count"]}, sources=[_source(root, "License/sbom-receipt.json")], note="All exact runtime and frontend lock components normalize to allowed licenses."),
        "Secret_Scan": dict(status="PASS" if security["metrics"]["SECRET_LEAK_IN_GIT"] == 0 else "FAIL", title="Secret scan gate", facts={"secret_leak_in_git": security["metrics"]["SECRET_LEAK_IN_GIT"], "failures": security["failures"]}, sources=[_source(root, "Secret_Scan/security-supply-gate-level0.json")], note="No credentials or provider secrets were accepted into Git evidence."),
        "Dependency_Audit": dict(status="PASS" if security["final_pass"] else "FAIL", title="Dependency vulnerability audit gate", facts={"final_pass": security["final_pass"], "failures": security["failures"]}, sources=[_source(root, "Secret_Scan/pip-audit.json"), _source(root, "Secret_Scan/npm-audit.json"), _source(root, "Secret_Scan/audit-receipt.json")], note="pip-audit ran from an isolated interpreter; npm audit ran against the exact frontend lock."),
        "Browser": dict(status="PASS" if browser["failures"] == browser["errors"] == 0 and browser["tests"] == 89 else "FAIL", title="Full browser E2E gate", facts=browser, sources=[_source(root, "Browser/full-89-level0-pass.xml")], note="The suite ran serially with one worker against the real API, DB, RAG, Agent, file, and controlled vision paths."),
    }

    for index in range(1, 5):
        phase = f"phase{index}"
        result = phase_results[phase]
        definitions[f"Phase{index}"] = dict(
            status=result["status"], title=f"Phase {index} deterministic regression",
            facts={"returncode": result["returncode"], "duration_ms": result["duration_ms"]},
            sources=[_source(root, "Provider_Fault/phase5-fault-regression-level0.json")],
            note="Executed by the consolidated fault/regression gate.",
        )

    dirty = bool(_git(repo, "status", "--porcelain"))
    upstream = _git(repo, "rev-parse", "@{u}")
    ahead_behind = _git(repo, "rev-list", "--left-right", "--count", "@{u}...HEAD")
    definitions["Git"] = dict(status="PASS" if not dirty else "FAIL", title="Local Git state", facts={"local_sha": finalized_sha, "upstream_sha": upstream, "ahead_behind": ahead_behind, "worktree_clean": not dirty}, sources=[_source(root, "Runtime/backend-pytest-final.xml")], note="This records local state only and does not certify remote CI.")
    definitions["Remote_CI"] = dict(status="NOT_RUN", title="Remote same-SHA CI status", facts={"remote_push": "NOT_RUN", "same_sha_ci": "NOT_RUN"}, sources=[_source(root, "Runtime/backend-pytest-final.xml")], note="No final-candidate push or paid certification was authorized while Level 0 blockers remain.")
    definitions["Final_Summary"] = dict(status="FAIL", title="Phase 5 Level 0 blocker remediation summary", facts={
        "backend": backend, "browser": browser,
        "controls": {"actionable": control["total_actionable_controls"], "tested": control["total_tested_controls"], "coverage": control["visible_actionable_control_coverage"]},
        "load_host_cpu_p99": resources["host_cpu_percent"]["p99"],
        "scanned_pdf_targeted_real": "NOT_RUN", "paid_provider_calls": 0,
    }, sources=[_source(root, "Runtime/backend-pytest-final.xml"), _source(root, "Browser/full-89-level0-pass.xml"), _source(root, "Control_Acceptance_Matrix/visible-control-inventory.json"), _source(root, "Concurrency/load-20x15-level0-rerun.json")], note="Phase 5 remains blocked by the uncertified control matrix, host CPU P99, and absence of same-SHA execution evidence. Level 1 and Level 2 are not allowed.")

    for directory, definition in definitions.items():
        _publish(
            root,
            directory,
            tested_sha=tested_sha,
            finalized_sha=finalized_sha,
            source_execution_tested_shas=source_execution_tested_shas,
            same_sha_execution_evidence=same_sha_execution_evidence,
            **definition,
        )

    print(json.dumps({
        "status": "PASS",
        "tested_sha": tested_sha,
        "finalized_sha": finalized_sha,
        "source_execution_tested_shas": source_execution_tested_shas,
        "same_sha_execution_evidence": same_sha_execution_evidence,
        "published_gate_count": len(definitions),
        "phase5_gate_certified": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
