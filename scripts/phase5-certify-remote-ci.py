"""Fail-closed certificate for the remote Phase5 CI scope (not the full GA gate)."""

from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


def _json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_checksums(directory: Path) -> list[str]:
    failures: list[str] = []
    checksum = directory / "SHA256SUMS.txt"
    if not checksum.is_file():
        return [f"{directory.name}:checksum_manifest_missing"]
    for line in checksum.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, recorded = line.partition("  ")
        target = directory / Path(recorded).name
        if len(digest) != 64 or not target.is_file() or _sha256(target) != digest:
            failures.append(f"{directory.name}:checksum_mismatch:{Path(recorded).name}")
    return failures


def _junit_failures(path: Path) -> int:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    return sum(int(item.get("failures", "0")) + int(item.get("errors", "0")) for item in suites)


def certify(root: Path, expected_sha: str, *, job_results: dict[str, str]) -> dict[str, object]:
    failures: list[str] = []
    expected_jobs = {"deterministic", "migration", "supply"}
    if set(job_results) != expected_jobs:
        failures.append("remote_job_results_incomplete")
    for name in sorted(expected_jobs):
        if job_results.get(name) != "success":
            failures.append(f"remote_job_not_success:{name}:{job_results.get(name, 'missing')}")
    deterministic = root / "deterministic"
    migration = root / "migration"
    supply = root / "supply"
    for directory in (deterministic, migration, supply):
        if not directory.is_dir():
            failures.append(f"{directory.name}:artifact_missing")
        else:
            failures.extend(_verify_checksums(directory))

    if deterministic.is_dir():
        tested = (deterministic / "tested-sha.txt").read_text(encoding="utf-8").strip()
        if tested != expected_sha:
            failures.append("deterministic:tested_sha_mismatch")
        contract = _json(deterministic / "fault-contract.json")
        fault = _json(deterministic / "fault-production-boundaries.json")
        if contract.get("status") != "CONTRACT_PASS" or contract.get("tested_sha") != expected_sha:
            failures.append("deterministic:contract_gate_invalid")
        if fault.get("status") != "FAULT_PASS" or fault.get("tested_sha") != expected_sha:
            failures.append("deterministic:fault_gate_invalid")
        for junit in ("phase5-junit.xml", "frontend-junit.xml"):
            if not (deterministic / junit).is_file() or not (deterministic / junit).stat().st_size:
                failures.append(f"deterministic:{junit}_missing")
            elif _junit_failures(deterministic / junit) != 0:
                failures.append(f"deterministic:{junit}_failed")
        build_receipt = deterministic / "frontend-build-success.txt"
        if not build_receipt.is_file() or build_receipt.read_text(encoding="utf-8").strip() != expected_sha:
            failures.append("deterministic:frontend_build_success_not_proven")

    if migration.is_dir():
        payload = _json(migration / "migration.json")
        if payload.get("tested_sha") != expected_sha:
            failures.append("migration:tested_sha_mismatch")
        if not all(payload.get(key) is True for key in (
            "single_head", "upgrade_base_upgrade_pass", "temporary_schema_removed",
        )):
            failures.append("migration:gate_invalid")

    if supply.is_dir():
        payload = _json(supply / "security-supply.json")
        if (payload.get("provenance") or {}).get("tested_sha") != expected_sha:
            failures.append("supply:tested_sha_mismatch")
        if payload.get("final_pass") is not True:
            failures.append("supply:gate_invalid")
        receipt = _json(supply / "sbom-receipt.json")
        if int(receipt.get("unknown_or_denied_license_count", -1)) != 0:
            failures.append("supply:sbom_license_invalid")

    return {
        "schema_version": "chatbi-v1.3-phase5-remote-ci-certificate-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tested_sha": expected_sha,
        "scope": "REMOTE_DETERMINISTIC_MIGRATION_SUPPLY_ONLY",
        "job_results": job_results,
        "remote_ci_certified": not failures,
        "phase5_release_gate_certified": False,
        "release_gate_note": "Full live/local and Git synchronization evidence is certified separately.",
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deterministic-result", required=True)
    parser.add_argument("--migration-result", required=True)
    parser.add_argument("--supply-result", required=True)
    args = parser.parse_args()
    job_results = {
        "deterministic": args.deterministic_result,
        "migration": args.migration_result,
        "supply": args.supply_result,
    }
    try:
        receipt = certify(args.root, args.expected_sha, job_results=job_results)
    except (OSError, ValueError, json.JSONDecodeError, ET.ParseError) as exc:
        receipt = {
            "schema_version": "chatbi-v1.3-phase5-remote-ci-certificate-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tested_sha": args.expected_sha,
            "scope": "REMOTE_DETERMINISTIC_MIGRATION_SUPPLY_ONLY",
            "job_results": job_results,
            "remote_ci_certified": False,
            "phase5_release_gate_certified": False,
            "failures": [f"certificate_runtime:{type(exc).__name__}"],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["remote_ci_certified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
