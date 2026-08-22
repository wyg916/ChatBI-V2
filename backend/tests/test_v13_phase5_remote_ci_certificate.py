from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "phase5-certify-remote-ci.py"
SPEC = importlib.util.spec_from_file_location("phase5_certify_remote_ci", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _checksum(directory: Path) -> None:
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  source/{path.name}"
        for path in sorted(directory.iterdir()) if path.name != "SHA256SUMS.txt"
    ]
    (directory / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _evidence(tmp_path: Path, sha: str) -> Path:
    root = tmp_path / "evidence"
    deterministic = root / "deterministic"
    migration = root / "migration"
    supply = root / "supply"
    for directory in (deterministic, migration, supply):
        directory.mkdir(parents=True)
    (deterministic / "tested-sha.txt").write_text(sha + "\n", encoding="utf-8")
    _write_json(deterministic / "fault-contract.json", {"status": "CONTRACT_PASS", "tested_sha": sha})
    _write_json(deterministic / "fault-production-boundaries.json", {"status": "FAULT_PASS", "tested_sha": sha})
    for name in ("phase5-junit.xml", "frontend-junit.xml"):
        (deterministic / name).write_text(
            '<testsuites tests="1" failures="0" errors="0"><testsuite tests="1" failures="0" errors="0"/></testsuites>',
            encoding="utf-8",
        )
    (deterministic / "frontend-build-success.txt").write_text(sha + "\n", encoding="utf-8")
    _write_json(migration / "migration.json", {
        "tested_sha": sha, "single_head": True,
        "upgrade_base_upgrade_pass": True, "temporary_schema_removed": True,
    })
    _write_json(supply / "security-supply.json", {
        "final_pass": True, "provenance": {"tested_sha": sha},
    })
    _write_json(supply / "sbom-receipt.json", {"unknown_or_denied_license_count": 0})
    for directory in (deterministic, migration, supply):
        _checksum(directory)
    return root


def test_remote_ci_certificate_requires_same_sha_and_all_three_scopes(tmp_path: Path) -> None:
    sha = "a" * 40
    root = _evidence(tmp_path, sha)

    job_results = {"deterministic": "success", "migration": "success", "supply": "success"}
    receipt = MODULE.certify(root, sha, job_results=job_results)

    assert receipt["remote_ci_certified"] is True
    assert receipt["phase5_release_gate_certified"] is False
    assert receipt["failures"] == []

    migration = json.loads((root / "migration" / "migration.json").read_text(encoding="utf-8"))
    migration["tested_sha"] = "b" * 40
    _write_json(root / "migration" / "migration.json", migration)
    _checksum(root / "migration")
    receipt = MODULE.certify(root, sha, job_results=job_results)
    assert receipt["remote_ci_certified"] is False
    assert "migration:tested_sha_mismatch" in receipt["failures"]

    receipt = MODULE.certify(root, sha, job_results={**job_results, "deterministic": "failure"})
    assert receipt["remote_ci_certified"] is False
    assert "remote_job_not_success:deterministic:failure" in receipt["failures"]
