from __future__ import annotations

import argparse
import shutil
import tarfile
from pathlib import Path, PurePosixPath


def _safe_target(root: Path, member_name: str) -> Path:
    member = PurePosixPath(member_name)
    if member.is_absolute() or ".." in member.parts:
        raise ValueError(f"unsafe archive member: {member_name}")
    target = (root / Path(*member.parts)).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"archive member escapes destination: {member_name}")
    return target


def extract_archive(archive_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, mode="r:") as archive:
        for member in archive.getmembers():
            target = _safe_target(destination, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ValueError(f"unsupported archive member type: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"archive member is unreadable: {member.name}")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract a trusted git archive without Windows newline conversion."
    )
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    extract_archive(args.archive, args.destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
