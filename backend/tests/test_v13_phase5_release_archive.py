from __future__ import annotations

import importlib.util
import io
import tarfile
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "extract_git_archive.py"
DRY_RUN_PATH = PROJECT_ROOT / "scripts" / "test-v13-phase5-rollback-dry-run.ps1"
SPEC = importlib.util.spec_from_file_location("phase5_extract_git_archive", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write_tar(path: Path, name: str, payload: bytes) -> None:
    with tarfile.open(path, mode="w") as archive:
        member = tarfile.TarInfo(name)
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))


def test_extract_archive_preserves_tracked_bytes(tmp_path: Path) -> None:
    archive = tmp_path / "candidate.tar"
    output = tmp_path / "candidate"
    payload = b"first\nsecond\n"
    _write_tar(archive, "backend/vendor/source.py", payload)

    MODULE.extract_archive(archive, output)

    assert (output / "backend/vendor/source.py").read_bytes() == payload


def test_extract_archive_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "candidate.tar"
    _write_tar(archive, "../escape.txt", b"blocked")

    with pytest.raises(ValueError, match="unsafe archive member"):
        MODULE.extract_archive(archive, tmp_path / "candidate")

    assert not (tmp_path / "escape.txt").exists()


def test_rollback_dry_run_exports_raw_git_blob_bytes() -> None:
    script = DRY_RUN_PATH.read_text(encoding="utf-8")

    assert script.count("-c core.autocrlf=false archive") == 2
    assert "tar -xf" not in script
