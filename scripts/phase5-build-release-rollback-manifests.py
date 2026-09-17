#!/usr/bin/env python3
"""Build exact-SHA Phase 5 release and rollback manifests outside Git.

The manifests intentionally contain no credentials. They bind the immutable
source, configuration, images, migration topology and exact dry-run commands.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
ROLLBACK_SHA = "89bdc12936be0555bdad8a85f06932fb7dc476ee"
CONFIG_PATHS = (
    ".env.example",
    "backend/config/test_cost_control.yaml",
    "backend/config/model_policy.yaml",
    "backend/config/model_capabilities.yaml",
    "backend/config/model_pricing.yaml",
    "backend/config/provider_health.yaml",
    "docker-compose.yml",
)
IMAGE_NAMES = (
    "chatbi-v2-backend:latest",
    "chatbi-v2-frontend:latest",
    "chatbi-sandbox-runtime:phase3",
)


def run(*args: str, check: bool = True) -> str:
    completed = subprocess.run(
        list(args), cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    if check and completed.returncode != 0:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(args)}")
    return completed.stdout.strip()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def configuration_hash() -> tuple[str, dict[str, str]]:
    files = {path: sha256_file(REPO_ROOT / path) for path in CONFIG_PATHS}
    canonical = json.dumps(files, ensure_ascii=True, sort_keys=True).encode("utf-8")
    return sha256_bytes(canonical), files


def git_file(sha: str, path: str) -> str | None:
    completed = subprocess.run(
        ["git", "show", f"{sha}:{path}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout if completed.returncode == 0 else None


def migration_head(sha: str) -> str:
    paths = run("git", "ls-tree", "-r", "--name-only", sha, "--", "backend/alembic/versions")
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in paths.splitlines():
        source = git_file(sha, path)
        if not source:
            continue
        tree = ast.parse(source, filename=path)
        values: dict[str, Any] = {}
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                    try:
                        values[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        pass
        revision = values.get("revision")
        down_revision = values.get("down_revision")
        if isinstance(revision, str):
            revisions.add(revision)
        if isinstance(down_revision, str):
            parents.add(down_revision)
        elif isinstance(down_revision, (tuple, list)):
            parents.update(value for value in down_revision if isinstance(value, str))
    heads = sorted(revisions - parents)
    if len(heads) != 1:
        raise RuntimeError(f"expected one migration head at {sha}, got {heads}")
    return heads[0]


def image_identity(name: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["docker", "image", "inspect", name],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return {"image": name, "status": "NOT_BUILT"}
    document = json.loads(completed.stdout)[0]
    repo_digests = sorted(document.get("RepoDigests") or [])
    image_id = str(document.get("Id") or "")
    return {
        "image": name,
        "status": "AVAILABLE",
        "image_id": image_id,
        "immutable_digest": repo_digests[0] if repo_digests else image_id,
        "repo_digests": repo_digests,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--final-sha", default="")
    parser.add_argument("--rollback-sha", default=ROLLBACK_SHA)
    args = parser.parse_args()

    final_sha = args.final_sha or run("git", "rev-parse", "HEAD")
    if len(final_sha) != 40 or run("git", "rev-parse", final_sha) != final_sha:
        raise RuntimeError("final SHA must be a full existing commit")
    rollback_sha = run("git", "rev-parse", args.rollback_sha)
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", rollback_sha, final_sha],
        cwd=REPO_ROOT,
        check=False,
    )
    if ancestry.returncode != 0:
        raise RuntimeError("rollback SHA is not an ancestor of final SHA")
    if run("git", "status", "--porcelain"):
        raise RuntimeError("manifest generation requires a clean worktree")

    config_hash, config_files = configuration_hash()
    compose_hash = sha256_file(REPO_ROOT / "docker-compose.yml")
    final_head = migration_head(final_sha)
    rollback_head = migration_head(rollback_sha)
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    images = [image_identity(name) for name in IMAGE_NAMES]
    exact_commands = {
        "precheck": [
            "git status --short --branch",
            f"git rev-parse HEAD  # must equal {final_sha}",
            "docker image inspect chatbi-v2-backend:latest chatbi-v2-frontend:latest chatbi-sandbox-runtime:phase3",
        ],
        "stop": ["docker compose -p <isolated-project> down --remove-orphans"],
        "rollback": [
            f"git -c core.autocrlf=false archive --format=tar --output=<temp>/rollback.tar {rollback_sha} -- <runtime-paths>",
            "python scripts/extract_git_archive.py <temp>/rollback.tar <temp>/rollback",
        ],
        "migration": [
            f"alembic current  # must equal {final_head}",
            (
                f"alembic downgrade {rollback_head}"
                if final_head != rollback_head
                else f"# NOT_APPLICABLE: candidate and rollback both use {final_head}"
            ),
        ],
        "start": ["docker compose -p <isolated-project> up -d --build"],
        "health": [
            "Invoke-RestMethod http://127.0.0.1:<backend-port>/health",
            "Invoke-WebRequest http://127.0.0.1:<frontend-port>/healthz",
        ],
        "verify": [
            "frontend Playwright rollback browser smoke",
            "authenticated dashboard API readback fingerprint before/after rollback",
            f"alembic current  # must equal {rollback_head}",
        ],
        "cleanup": [
            "docker compose -p <isolated-project> down --remove-orphans",
            "drop only the run-specific temporary PostgreSQL schema",
            "remove only the validated run-specific temporary archive directory",
        ],
    }

    common = {
        "schema_version": "chatbi.v13.phase5.release-identity.v1",
        "generated_at": timestamp,
        "final_sha": final_sha,
        "rollback_sha": rollback_sha,
        "branch": run("git", "branch", "--show-current"),
        "configuration_hash": config_hash,
        "configuration_files": config_files,
        "compose_hash": compose_hash,
        "image_digests": images,
        "migration_head": final_head,
        "rollback_migration_target": rollback_head,
        "migration_downgrade_applicable": final_head != rollback_head,
        "secrets_recorded": False,
        "main_changed": False,
        "tag_created": False,
        "release_created": False,
        "phase6_started": False,
    }
    release = {
        **common,
        "manifest_type": "RELEASE_CANDIDATE",
        "status": "IDENTITY_FROZEN_PENDING_SAME_SHA_CERTIFICATION",
        "exact_commands": exact_commands,
    }
    rollback = {
        **common,
        "manifest_type": "ROLLBACK",
        "status": "EXECUTABLE_DRY_RUN_REQUIRED",
        "production_target": False,
        "preserve_local_business_databases": True,
        "exact_commands": exact_commands,
    }

    root = args.evidence_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    release_path = root / "release-manifest.json"
    rollback_path = root / "rollback-manifest.json"
    write_json(release_path, release)
    write_json(rollback_path, rollback)
    checksums = {
        release_path.name: sha256_file(release_path),
        rollback_path.name: sha256_file(rollback_path),
    }
    (root / "SHA256SUMS.txt").write_text(
        "".join(f"{value}  {name}\n" for name, value in sorted(checksums.items())),
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "evidence_root": str(root), **checksums}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
