"""Generate byte-deterministic V1.3 CycloneDX/SPDX SBOMs from exact inventories."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "supply-chain" / "v1.3-phase5-policy.json"
LEGACY_GENERATOR = ROOT / "scripts" / "release" / "generate_sbom.py"
INVENTORY_PROBE = r'''from importlib import metadata
import json, sysconfig
rows=[]
for d in metadata.distributions(path=[sysconfig.get_paths()["purelib"]]):
    m=d.metadata
    rows.append({
        "name": m.get("Name") or "",
        "version": d.version,
        "license": (m.get("License-Expression") or m.get("License") or "").strip(),
        "classifiers": [x.split(" :: ")[-1] for x in (m.get_all("Classifier") or []) if x.startswith("License ::")],
    })
rows.sort(key=lambda item: ((item.get("name") or "").lower().replace("_", "-"), item.get("version") or ""))
print(json.dumps(rows, ensure_ascii=False))'''
CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _legacy_module():
    spec = importlib.util.spec_from_file_location("chatbi_release_sbom", LEGACY_GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the release SBOM generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_inventory(
    path: Path | None,
    python: Path | None,
    container: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if path is not None:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        source = {
            "type": "inventory-file",
            "path": path.as_posix(),
            "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    elif python is not None:
        completed = subprocess.run(
            [str(python), "-c", INVENTORY_PROBE],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        source = {
            "type": "python-environment",
            "python": str(python),
            "python_sha256": hashlib.sha256(python.read_bytes()).hexdigest(),
        }
    elif container is not None:
        if not CONTAINER_NAME.fullmatch(container):
            raise ValueError("backend container name is not valid")
        completed = subprocess.run(
            ["docker", "exec", container, "python", "-c", INVENTORY_PROBE],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        image_id = subprocess.run(
            ["docker", "inspect", "--format", "{{.Image}}", container],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        repo_digests_raw = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image_id],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        repo_digests = json.loads(repo_digests_raw) if repo_digests_raw else []
        source = {
            "type": "release-container",
            "container_name": container,
            "image_id": image_id,
            "image_repo_digests": sorted(repo_digests or []),
        }
    else:
        raise ValueError("a backend inventory source is required")
    if not isinstance(payload, list):
        raise ValueError("backend inventory must be a JSON list")
    rows = [item for item in payload if isinstance(item, dict)]
    rows.sort(
        key=lambda item: (
            str(item.get("name") or "").lower().replace("_", "-"),
            str(item.get("version") or ""),
        )
    )
    return rows, source


def _backend_components(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    legacy = _legacy_module()
    components: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        name = str(row.get("name") or "").strip()
        version = str(row.get("version") or "").strip()
        if not name or not version:
            raise ValueError("backend inventory contains an unnamed or unversioned distribution")
        key = (name.lower().replace("_", "-"), version)
        if key in seen:
            continue
        seen.add(key)
        license_id = legacy._normalise_license(
            str(row.get("license") or ""),
            list(row.get("classifiers") or []),
            key[0],
        )
        components.append(
            {
                "ecosystem": "pypi",
                "name": name,
                "version": version,
                "license": license_id,
                "purl": f"pkg:pypi/{quote(key[0])}@{quote(version)}",
                "scope": "required",
            }
        )
    return components


def _frontend_components(lock_path: Path) -> list[dict[str, Any]]:
    return list(_legacy_module()._frontend_inventory(lock_path))


def _license_allowed(expression: str, policy: dict[str, Any]) -> bool:
    if not expression:
        return False
    if any(expression.startswith(prefix) for prefix in policy["denied_license_prefixes"]):
        return False
    allowed = set(policy["allowed_license_ids"])
    tokens = (
        expression.replace("(", " ")
        .replace(")", " ")
        .replace(" AND ", " ")
        .replace(" OR ", " ")
        .replace(" WITH ", " ")
        .split()
    )
    return bool(tokens) and all(token in allowed for token in tokens)


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build_documents(
    rows: list[dict[str, Any]],
    frontend_lock: Path,
    *,
    generated_at: str,
    policy: dict[str, Any],
) -> tuple[bytes, bytes, dict[str, Any]]:
    legacy = _legacy_module()
    components = _backend_components(rows) + _frontend_components(frontend_lock)
    components.sort(key=lambda item: (str(item["ecosystem"]), str(item["name"]).lower(), str(item["version"])))
    invalid = [
        f"{item['ecosystem']}:{item['name']}@{item['version']}"
        for item in components
        if not _license_allowed(str(item.get("license") or ""), policy)
    ]
    if invalid:
        raise ValueError("unknown or denied licenses: " + ",".join(invalid))

    version = str(policy["project_version"])
    root_ref = f"pkg:generic/chatbi-v2@{version}"
    cyclonedx = legacy._cyclonedx(components, generated_at)
    old_root_ref = str(cyclonedx["metadata"]["component"]["bom-ref"])
    cyclonedx["metadata"]["component"]["version"] = version
    cyclonedx["metadata"]["component"]["bom-ref"] = root_ref
    cyclonedx["metadata"]["tools"]["components"][0].update(
        {"name": "ChatBI deterministic Phase5 SBOM generator", "version": "1"}
    )
    for dependency in cyclonedx["dependencies"]:
        if dependency["ref"] == old_root_ref:
            dependency["ref"] = root_ref

    spdx = legacy._spdx(components, generated_at)
    refs_digest = hashlib.sha256(
        "\n".join(
            sorted(f"{item['ecosystem']}:{item['name']}@{item['version']}" for item in components)
        ).encode("utf-8")
    ).hexdigest()
    spdx["name"] = f"chatbi-v2-{version}"
    spdx["documentNamespace"] = (
        f"https://github.com/wyg916/ChatBI-V2/sbom/{version}/{refs_digest}"
    )
    spdx["creationInfo"]["creators"] = [
        "Tool: ChatBI deterministic Phase5 SBOM generator-1"
    ]
    spdx["creationInfo"]["comment"] = (
        "Unknown or denied license count: 0. Inventories are exact inputs; "
        "SOURCE_DATE_EPOCH fixes creation time."
    )
    spdx["packages"][0]["versionInfo"] = version
    receipt = {
        "schema_version": "chatbi-v1.3-phase5-sbom-receipt-v1",
        "component_count": len(components),
        "backend_component_count": sum(item["ecosystem"] == "pypi" for item in components),
        "frontend_component_count": sum(item["ecosystem"] == "npm" for item in components),
        "unknown_or_denied_license_count": 0,
        "generated_at": generated_at,
        "backend_inventory_sha256": hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "frontend_lock_sha256": hashlib.sha256(frontend_lock.read_bytes()).hexdigest(),
        "policy_sha256": hashlib.sha256(
            json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    return _canonical_json(cyclonedx), _canonical_json(spdx), receipt


def _timestamp(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--backend-inventory", type=Path)
    inputs.add_argument("--backend-python", type=Path)
    inputs.add_argument("--backend-container")
    parser.add_argument("--frontend-lock", type=Path, default=ROOT / "frontend" / "package-lock.json")
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    parser.add_argument("--cyclonedx-output", type=Path, required=True)
    parser.add_argument("--spdx-output", type=Path, required=True)
    parser.add_argument("--receipt-output", type=Path)
    parser.add_argument("--source-date-epoch", type=int)
    args = parser.parse_args()

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    epoch = args.source_date_epoch
    if epoch is None:
        epoch = int(os.getenv("SOURCE_DATE_EPOCH") or policy["source_date_epoch"])
    rows, inventory_source = _load_inventory(
        args.backend_inventory,
        args.backend_python,
        args.backend_container,
    )
    first = build_documents(rows, args.frontend_lock, generated_at=_timestamp(epoch), policy=policy)
    second = build_documents(rows, args.frontend_lock, generated_at=_timestamp(epoch), policy=policy)
    if first[:2] != second[:2]:
        print("SBOM_DETERMINISTIC=0", file=sys.stderr)
        return 3
    for path, content in ((args.cyclonedx_output, first[0]), (args.spdx_output, first[1])):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    receipt = {
        **first[2],
        "backend_inventory_source": inventory_source,
        "deterministic": True,
        "cyclonedx_sha256": hashlib.sha256(first[0]).hexdigest(),
        "spdx_sha256": hashlib.sha256(first[1]).hexdigest(),
    }
    if args.receipt_output:
        args.receipt_output.parent.mkdir(parents=True, exist_ok=True)
        args.receipt_output.write_bytes(_canonical_json(receipt))
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
