"""Bind Phase 5 evidence to one clean SHA; this never certifies the release gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


REQUIRED_DIRECTORIES = (
    "Data100",
    "10M",
    "Concurrency",
    "Weird50",
    "Complex5",
    "Multimodal10",
    "Provider_Fault",
    "DB_Fault",
    "RAG_Fault",
    "Sandbox_Fault",
    "Security",
    "Cost",
    "Migration",
    "Cold_Start",
    "SBOM",
    "License",
    "Secret_Scan",
    "Dependency_Audit",
    "Browser",
    "Phase1",
    "Phase2",
    "Phase3",
    "Phase4",
    "Git",
    "Remote_CI",
    "Final_Summary",
    "SHA256SUMS",
)
FORBIDDEN_NAME_PARTS = (".env", "auth-state", "cookie", "credentials", "private-key")
SECRET_PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |ENCRYPTED )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "gitlab-token": re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    "slack-token": re.compile(r"\bxox(?:a|b|p|r|s)-[A-Za-z0-9-]{20,}\b"),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "provider-token": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{40,}\b"),
    "credential-url": re.compile(
        r"\b(?:postgres(?:ql)?|mysql|mariadb)://[^\s:@/]+:[^\s@/]+@", re.I
    ),
}


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files(root: Path, checksum_path: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if path.is_file() and path != checksum_path and not path.name.endswith(".tmp"):
            yield path


def _secret_hits(root: Path, paths: Iterable[Path]) -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        lowered = relative.lower()
        if any(part in lowered for part in FORBIDDEN_NAME_PARTS):
            hits.append({"path": relative, "pattern": "forbidden-evidence-filename"})
            continue
        try:
            content = path.read_bytes().decode("utf-8", errors="replace")
        except OSError as exc:
            hits.append({"path": relative, "pattern": f"unscannable:{type(exc).__name__}"})
            continue
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(content):
                hits.append({"path": relative, "pattern": name})
    return hits


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize ChatBI V1.3 Phase 5 external evidence")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--expected-sha")
    parser.add_argument(
        "--reported-gate-status",
        choices=("PASS", "FAIL", "PARTIAL"),
        required=True,
        help="Informational status from the separately validated final gate; never trusted here.",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    repo = args.repo.resolve()
    if not root.is_dir():
        raise SystemExit("EVIDENCE_ROOT_MISSING")
    if root == repo or repo in root.parents or root in repo.parents:
        raise SystemExit("EVIDENCE_ROOT_MUST_BE_INDEPENDENT_FROM_REPOSITORY")
    missing = [name for name in REQUIRED_DIRECTORIES if not (root / name).is_dir()]
    if missing:
        raise SystemExit("EVIDENCE_DIRECTORIES_MISSING:" + ",".join(missing))

    sha = _git(repo, "rev-parse", "HEAD")
    expected_sha = args.expected_sha or sha
    if sha != expected_sha:
        raise SystemExit("TESTED_SHA_MISMATCH")
    dirty = _git(repo, "status", "--porcelain")
    if dirty:
        raise SystemExit("WORKTREE_NOT_CLEAN")

    checksum_path = root / "SHA256SUMS" / "SHA256SUMS.txt"
    before = list(_files(root, checksum_path))
    hits = _secret_hits(root, before)
    if hits:
        safe = [{"path": item["path"], "pattern": item["pattern"]} for item in hits]
        _atomic_json(root / "Secret_Scan" / "evidence-secret-scan-failed.json", {
            "tested_sha": sha,
            "status": "FAIL",
            "hits": safe,
        })
        raise SystemExit("EVIDENCE_SECRET_SCAN_FAILED")

    counts = {
        name: sum(path.is_file() for path in (root / name).rglob("*"))
        for name in REQUIRED_DIRECTORIES
    }
    empty = [name for name, count in counts.items() if count == 0 and name != "SHA256SUMS"]
    if args.reported_gate_status == "PASS" and empty:
        raise SystemExit("PASS_EVIDENCE_DIRECTORIES_EMPTY:" + ",".join(empty))
    summary = {
        "schema_version": "chatbi-v1.3-phase5-evidence-integrity-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "integrity_status": "PASS",
        "release_gate_certified": False,
        "reported_gate_status_untrusted": args.reported_gate_status,
        "tested_sha": sha,
        "worktree_clean": True,
        "required_directory_count": len(REQUIRED_DIRECTORIES),
        "directory_file_counts": counts,
        "empty_required_directories": empty,
        "secret_hit_count": 0,
    }
    _atomic_json(root / "Final_Summary" / "evidence-integrity.json", summary)

    paths = list(_files(root, checksum_path))
    lines = [f"{_sha256(path)}  {path.relative_to(root).as_posix()}" for path in paths]
    checksum_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = checksum_path.with_suffix(".txt.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(checksum_path)
    print(json.dumps({
        "integrity_status": "PASS",
        "release_gate_certified": False,
        "tested_sha": sha,
        "evidence_file_count": len(paths),
        "empty_required_directories": empty,
        "sha256_manifest": str(checksum_path),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
