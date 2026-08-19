"""Generate deterministic CycloneDX and SPDX SBOMs for the release image.

The backend inventory is read from the running release container so the SBOM
describes what is actually shipped.  The frontend inventory comes from the
npm lock file, including transitive dependencies.  Unknown licenses are a
hard error by design.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[2]
PROJECT_NAME = "ChatBI V2"
PROJECT_VERSION = "1.1.0"
PROJECT_LICENSE = "Apache-2.0"


def _normalise_license(raw: str, classifiers: list[str], name: str) -> str:
    text = " ".join((raw or "").split())
    lower = text.lower()
    if name.startswith("chatbi-"):
        return PROJECT_LICENSE
    exact = {
        "apache software license": "Apache-2.0",
        "bsd": "BSD-3-Clause",
        "dual license": "BSD-3-Clause OR Apache-2.0",
        "gnu lesser general public license v3 (lgplv3)": "LGPL-3.0-only",
        "mit license": "MIT",
    }
    if lower in exact:
        return exact[lower]
    if lower.startswith("bsd 3-clause license"):
        return "BSD-3-Clause"
    if text and re.fullmatch(r"[A-Za-z0-9.+()\- ]+(?:\s+(?:AND|OR)\s+[A-Za-z0-9.+()\- ]+)*", text):
        return text

    classifier_map = {
        "Apache Software License": "Apache-2.0",
        "BSD License": "BSD-3-Clause",
        "GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
        "MIT License": "MIT",
        "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    }
    mapped = sorted({classifier_map[item] for item in classifiers if item in classifier_map})
    if mapped:
        # Prefer the package's explicit short license when classifiers include
        # several historical/compatible choices (notably uvloop).
        if "mit" in lower:
            return "MIT"
        return " OR ".join(mapped)
    return ""


def _backend_inventory(container: str) -> list[dict[str, object]]:
    probe = r'''from importlib import metadata
import json
rows=[]
for d in metadata.distributions():
    m=d.metadata
    rows.append({
        "name": m.get("Name") or "",
        "version": d.version,
        "license": (m.get("License-Expression") or m.get("License") or "").strip(),
        "classifiers": [x.split(" :: ")[-1] for x in (m.get_all("Classifier") or []) if x.startswith("License ::")],
    })
print(json.dumps(rows, ensure_ascii=False))'''
    command = ["docker", "exec", container, "python", "-c", probe]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            f"Cannot inspect backend release container {container!r}; start docker compose first"
        ) from exc
    rows = json.loads(completed.stdout)
    components: list[dict[str, object]] = []
    for row in rows:
        name = str(row["name"])
        version = str(row["version"])
        license_id = _normalise_license(
            str(row.get("license") or ""), list(row.get("classifiers") or []), name.lower()
        )
        components.append(
            {
                "ecosystem": "pypi",
                "name": name,
                "version": version,
                "license": license_id,
                "purl": f"pkg:pypi/{quote(name.lower())}@{quote(version)}",
                "scope": "required",
            }
        )
    return components


def _frontend_inventory(lock_path: Path) -> list[dict[str, object]]:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    components: list[dict[str, object]] = []
    for package_path, item in lock.get("packages", {}).items():
        if not package_path:
            continue
        name = item.get("name") or package_path.removeprefix("node_modules/")
        version = str(item.get("version") or "")
        license_id = str(item.get("license") or "").strip()
        if name.startswith("@") and "/" in name:
            scope, package_name = name[1:].split("/", 1)
            purl_name = f"%40{quote(scope, safe='')}/{quote(package_name, safe='')}"
        else:
            purl_name = quote(name, safe="")
        entry: dict[str, object] = {
            "ecosystem": "npm",
            "name": name,
            "version": version,
            "license": license_id,
            "purl": f"pkg:npm/{purl_name}@{quote(version)}",
            "scope": "optional" if item.get("optional") else ("excluded" if item.get("dev") else "required"),
        }
        integrity = str(item.get("integrity") or "")
        if integrity.startswith("sha512-"):
            entry["integrity"] = integrity
        components.append(entry)
    return components


def _component_ref(component: dict[str, object]) -> str:
    return f"{component['ecosystem']}:{component['name']}@{component['version']}"


def _spdx_id(component: dict[str, object], index: int) -> str:
    stem = re.sub(r"[^A-Za-z0-9.-]+", "-", _component_ref(component)).strip("-")
    return f"SPDXRef-{stem}-{index}"


def _cyclonedx(components: list[dict[str, object]], generated_at: str) -> dict[str, object]:
    root_ref = f"pkg:generic/chatbi-v2@{PROJECT_VERSION}"
    entries = []
    refs = []
    for component in components:
        ref = _component_ref(component)
        refs.append(ref)
        item: dict[str, object] = {
            "type": "library",
            "bom-ref": ref,
            "group": component["ecosystem"],
            "name": component["name"],
            "version": component["version"],
            "scope": component["scope"],
            "licenses": [{"license": {"id": component["license"]}}],
            "purl": component["purl"],
        }
        if component.get("integrity"):
            item["properties"] = [{"name": "npm:integrity", "value": component["integrity"]}]
        entries.append(item)
    serial_seed = "\n".join(sorted(refs)).encode("utf-8")
    serial = hashlib.sha256(serial_seed).hexdigest()
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial[:8]}-{serial[8:12]}-{serial[12:16]}-{serial[16:20]}-{serial[20:32]}",
        "version": 1,
        "metadata": {
            "timestamp": generated_at,
            "tools": {"components": [{"type": "application", "name": "ChatBI SBOM generator", "version": "1"}]},
            "component": {
                "type": "application",
                "bom-ref": root_ref,
                "name": PROJECT_NAME,
                "version": PROJECT_VERSION,
                "licenses": [{"license": {"id": PROJECT_LICENSE}}],
            },
            "properties": [{"name": "chatbi:unknown-license-count", "value": "0"}],
        },
        "components": entries,
        "dependencies": [{"ref": root_ref, "dependsOn": refs}]
        + [{"ref": ref, "dependsOn": []} for ref in refs],
    }


def _spdx(components: list[dict[str, object]], generated_at: str) -> dict[str, object]:
    digest = hashlib.sha256("\n".join(sorted(_component_ref(c) for c in components)).encode()).hexdigest()
    root_id = "SPDXRef-ChatBI-V2"
    packages: list[dict[str, object]] = [
        {
            "SPDXID": root_id,
            "name": PROJECT_NAME,
            "versionInfo": PROJECT_VERSION,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": PROJECT_LICENSE,
            "licenseDeclared": PROJECT_LICENSE,
            "copyrightText": "NOASSERTION",
            "primaryPackagePurpose": "APPLICATION",
        }
    ]
    relationships: list[dict[str, str]] = []
    for index, component in enumerate(components, start=1):
        spdx_id = _spdx_id(component, index)
        packages.append(
            {
                "SPDXID": spdx_id,
                "name": component["name"],
                "versionInfo": component["version"],
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": component["license"],
                "licenseDeclared": component["license"],
                "copyrightText": "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": component["purl"],
                    }
                ],
            }
        )
        relationships.append(
            {"spdxElementId": root_id, "relationshipType": "DEPENDS_ON", "relatedSpdxElement": spdx_id}
        )
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"chatbi-v2-{PROJECT_VERSION}",
        "documentNamespace": f"https://github.com/wyg916/ChatBI-V2/sbom/{PROJECT_VERSION}/{digest}",
        "creationInfo": {
            "created": generated_at,
            "creators": ["Tool: ChatBI SBOM generator-1"],
            "comment": "Unknown license count: 0. Backend inventory is from the release container; frontend inventory is from package-lock.json.",
        },
        "packages": packages,
        "relationships": relationships,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-container", default="chatbi-v2-backend-1")
    parser.add_argument("--frontend-lock", type=Path, default=ROOT / "frontend" / "package-lock.json")
    parser.add_argument("--cyclonedx-output", type=Path, default=ROOT / "docs" / "sbom" / "V1_1_0.cdx.json")
    parser.add_argument("--spdx-output", type=Path, default=ROOT / "docs" / "sbom" / "V1_1_0.spdx.json")
    args = parser.parse_args()

    components = _backend_inventory(args.backend_container) + _frontend_inventory(args.frontend_lock)
    components.sort(key=lambda item: (str(item["ecosystem"]), str(item["name"]).lower(), str(item["version"])))
    unknown = [f"{item['ecosystem']}:{item['name']}@{item['version']}" for item in components if not item["license"]]
    if unknown:
        print("UNKNOWN_LICENSES=" + ",".join(unknown), file=sys.stderr)
        return 2

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    args.cyclonedx_output.parent.mkdir(parents=True, exist_ok=True)
    args.spdx_output.parent.mkdir(parents=True, exist_ok=True)
    args.cyclonedx_output.write_text(
        json.dumps(_cyclonedx(components, generated_at), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    args.spdx_output.write_text(
        json.dumps(_spdx(components, generated_at), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    backend_count = sum(1 for item in components if item["ecosystem"] == "pypi")
    frontend_count = sum(1 for item in components if item["ecosystem"] == "npm")
    print(f"SBOM_STATUS=PASS BACKEND_COMPONENTS={backend_count} FRONTEND_COMPONENTS={frontend_count} UNKNOWN_LICENSES=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
