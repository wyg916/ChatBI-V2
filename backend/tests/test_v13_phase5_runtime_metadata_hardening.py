from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release" / "patch_selected_dbgpt_metadata.py"
SPEC = importlib.util.spec_from_file_location("patch_selected_dbgpt_metadata", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _fake_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dbgpt-0.8.1.dist-info"
    dist.mkdir(parents=True)
    metadata = (
        "Metadata-Version: 2.4\nName: dbgpt\nVersion: 0.8.1\n"
        "Requires-Dist: aiohttp==3.8.4\nRequires-Dist: pydantic>=2.6.0\n"
    ).encode()
    (dist / "METADATA").write_bytes(metadata)
    (dist / "direct_url.json").write_text(json.dumps({
        "archive_info": {"hashes": {"sha256": MODULE.EXPECTED_ARCHIVE_SHA256}},
        "subdirectory": MODULE.EXPECTED_SUBDIRECTORY,
        "url": MODULE.EXPECTED_ARCHIVE,
    }), encoding="utf-8")
    digest = base64.urlsafe_b64encode(hashlib.sha256(metadata).digest()).decode().rstrip("=")
    (dist / "RECORD").write_text(
        f"{dist.name}/METADATA,sha256={digest},{len(metadata)}\n"
        f"{dist.name}/RECORD,,\n",
        encoding="utf-8",
    )
    return dist


def test_patch_corrects_exact_selected_metadata_and_record_idempotently(tmp_path: Path) -> None:
    dist = _fake_dist(tmp_path)

    first = MODULE.patch_dist_info(dist, aiohttp_version="3.14.3")
    second = MODULE.patch_dist_info(dist, aiohttp_version="3.14.3")

    assert first["status"] == "PASS" and first["changed"] is True
    assert second["status"] == "PASS" and second["changed"] is False
    metadata = (dist / "METADATA").read_bytes()
    assert b"aiohttp==3.14.3" in metadata and b"aiohttp==3.8.4" not in metadata
    with (dist / "RECORD").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream))
    row = next(item for item in rows if item[0].endswith("/METADATA"))
    expected = base64.urlsafe_b64encode(hashlib.sha256(metadata).digest()).decode().rstrip("=")
    assert row[1] == f"sha256={expected}"
    assert row[2] == str(len(metadata))


def test_patch_fails_closed_on_provenance_or_runtime_version_drift(tmp_path: Path) -> None:
    dist = _fake_dist(tmp_path)
    direct = json.loads((dist / "direct_url.json").read_text(encoding="utf-8"))
    direct["archive_info"]["hashes"]["sha256"] = "0" * 64
    (dist / "direct_url.json").write_text(json.dumps(direct), encoding="utf-8")

    with pytest.raises(RuntimeError, match="PROVENANCE_MISMATCH"):
        MODULE.patch_dist_info(dist, aiohttp_version="3.14.3")

    dist = _fake_dist(tmp_path / "other")
    with pytest.raises(RuntimeError, match="AIOHTTP_VERSION_MISMATCH"):
        MODULE.patch_dist_info(dist, aiohttp_version="3.14.2")
