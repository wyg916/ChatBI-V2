"""Correct the selected DB-GPT AWEL distribution metadata after an audited aiohttp override."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path


EXPECTED_VERSION = "0.8.1"
EXPECTED_ARCHIVE = (
    "https://github.com/eosphoros-ai/DB-GPT/archive/"
    "db580e952e544acf9f6c6c153da29dc67e9e40d7.zip"
)
EXPECTED_ARCHIVE_SHA256 = "e225a2e222874adfb504e03f6a2d091729d8ecb2c874783fd4bcbc2c7c8ef31b"
EXPECTED_SUBDIRECTORY = "packages/dbgpt-core"
OLD_REQUIREMENT = "Requires-Dist: aiohttp==3.8.4"
NEW_REQUIREMENT = "Requires-Dist: aiohttp==3.14.3"


def _record_digest(data: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode("ascii").rstrip("=")
    return f"sha256={encoded}"


def patch_dist_info(dist_info: Path, *, aiohttp_version: str) -> dict[str, object]:
    dist_info = dist_info.resolve()
    metadata_path = dist_info / "METADATA"
    direct_url_path = dist_info / "direct_url.json"
    record_path = dist_info / "RECORD"
    if not all(path.is_file() for path in (metadata_path, direct_url_path, record_path)):
        raise RuntimeError("SELECTED_DBGPT_METADATA_FILES_MISSING")

    direct_url = json.loads(direct_url_path.read_text(encoding="utf-8"))
    hashes = (direct_url.get("archive_info") or {}).get("hashes") or {}
    if (
        direct_url.get("url") != EXPECTED_ARCHIVE
        or direct_url.get("subdirectory") != EXPECTED_SUBDIRECTORY
        or hashes.get("sha256") != EXPECTED_ARCHIVE_SHA256
    ):
        raise RuntimeError("SELECTED_DBGPT_DIRECT_URL_PROVENANCE_MISMATCH")
    if aiohttp_version != "3.14.3":
        raise RuntimeError("AUDITED_AIOHTTP_VERSION_MISMATCH")

    metadata = metadata_path.read_text(encoding="utf-8")
    version_lines = [line for line in metadata.splitlines() if line.startswith("Version: ")]
    if version_lines != [f"Version: {EXPECTED_VERSION}"]:
        raise RuntimeError("SELECTED_DBGPT_VERSION_MISMATCH")
    old_count = metadata.count(OLD_REQUIREMENT)
    new_count = metadata.count(NEW_REQUIREMENT)
    if (old_count, new_count) == (1, 0):
        metadata = metadata.replace(OLD_REQUIREMENT, NEW_REQUIREMENT, 1)
        metadata_path.write_text(metadata, encoding="utf-8", newline="\n")
        changed = True
    elif (old_count, new_count) == (0, 1):
        changed = False
    else:
        raise RuntimeError("SELECTED_DBGPT_AIOHTTP_REQUIREMENT_UNEXPECTED")

    metadata_bytes = metadata_path.read_bytes()
    relative_metadata = f"{dist_info.name}/METADATA"
    with record_path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    matches = [index for index, row in enumerate(rows) if row and row[0] == relative_metadata]
    if len(matches) != 1:
        raise RuntimeError("SELECTED_DBGPT_RECORD_METADATA_ENTRY_INVALID")
    rows[matches[0]] = [relative_metadata, _record_digest(metadata_bytes), str(len(metadata_bytes))]
    with record_path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, lineterminator="\n").writerows(rows)

    return {
        "status": "PASS",
        "distribution": "dbgpt",
        "version": EXPECTED_VERSION,
        "selected_archive_sha256": EXPECTED_ARCHIVE_SHA256,
        "aiohttp_requirement": "aiohttp==3.14.3",
        "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        "record_updated": True,
        "changed": changed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    distribution = importlib.metadata.distribution("dbgpt")
    if distribution.version != EXPECTED_VERSION:
        raise SystemExit("SELECTED_DBGPT_VERSION_MISMATCH")
    try:
        aiohttp_version = importlib.metadata.version("aiohttp")
        result = patch_dist_info(Path(distribution._path), aiohttp_version=aiohttp_version)
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
