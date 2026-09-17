from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.certification.runtime_binding import (  # noqa: E402
    RuntimeBindingError,
    run_exact_sha_runtime_preflight,
    seal_runtime_preflight_receipt,
)
from app.model_gateway.test_cost_control import control_config_hash  # noqa: E402


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail-closed ChatBI exact-SHA runtime binding preflight")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _write(path: Path, payload: dict[str, object]) -> None:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    arguments = _arguments()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    try:
        payload = run_exact_sha_runtime_preflight(
            repo_root=arguments.repo_root,
            expected_git_sha=arguments.expected_sha,
            include_pip_freeze=True,
        )
    except RuntimeBindingError as exc:
        payload = dict(exc.receipt or {"status": "FAIL", "failures": [str(exc)]})
    payload = seal_runtime_preflight_receipt(payload, config_hash=control_config_hash())
    _write(arguments.output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
