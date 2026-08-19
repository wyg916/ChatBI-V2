"""Run one release-gate command and append an auditable command record."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    # The recorder already decodes child output as UTF-8.  Windows otherwise
    # inherits a GBK console writer, which crashes on Vitest/Playwright glyphs
    # such as the check mark before the exit code can be recorded.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="set a non-secret child-process environment variable (repeatable)",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")

    child_env = os.environ.copy()
    recorded_env: dict[str, str] = {}
    for assignment in args.env:
        name, separator, value = assignment.partition("=")
        if not separator or not name or not name.replace("_", "").isalnum():
            parser.error(f"invalid --env assignment: {assignment!r}")
        child_env[name] = value
        recorded_env[name] = value

    started = _now()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("w", encoding="utf-8", newline="") as log:
        process = subprocess.Popen(
            command,
            cwd=args.cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env,
        )
        assert process.stdout is not None
        for line in process.stdout:
            log.write(line)
            log.flush()
            sys.stdout.write(line)
            sys.stdout.flush()
        exit_code = process.wait()
    finished = _now()

    records: list[dict] = []
    if args.record.exists():
        records = json.loads(args.record.read_text(encoding="utf-8-sig"))
    records.append(
        {
            "name": args.name,
            "command": command,
            "environment": recorded_env,
            "cwd": str(args.cwd.resolve()),
            "started_at": started,
            "finished_at": finished,
            "exit_code": exit_code,
            "log": str(args.log.resolve()),
        }
    )
    _atomic_json(args.record, records)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
