from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


IBM_UPSTREAM_COMMIT = "60dd4515236adb335f2053b7c069397d7d88fe0a"

# Every Python file executed by runtime_bridge.py is locked to the reviewed IBM
# commit. The sole file without an SPDX header is evaluation/__init__.py; it is
# an unmodified package initializer governed by the repository Apache-2.0
# LICENSE. The package/wheel metadata path is deliberately not used.
SELECTED_SOURCE_SHA256 = {
    "src/text2sql_eval_toolkit/evaluation/__init__.py": "dc7f0dae49ba79434bb76256ddc0111bc3ed7a87de6f04a6bdf0504ea414f4b4",
    "src/text2sql_eval_toolkit/evaluation/evaluation_tools.py": "ecf732cf2b13eb093132baaf512658dea871e1d5a9a15098b10f6abce29c44c9",
    "src/text2sql_eval_toolkit/evaluation/llm_as_judge.py": "af04a5f3557f04f9e89b2833e8321ca252679cc13667362a1772e7458dbc9cb1",
    "src/text2sql_eval_toolkit/metrics/__init__.py": "119babb7b375f0053f3079227ed536bfc17622dfb49be6e3c29cd46de90f4f57",
    "src/text2sql_eval_toolkit/metrics/text2sql_utils.py": "f6caa4d84682ba67e435cc70837d684db03c7982d130f65ae5365f4a2363bbbe",
    "src/text2sql_eval_toolkit/utils.py": "8691f1e6a4fb44c9f66eb2455e476e57722fbf02f27abd7bbbecbf8b56681bb2",
    "src/text2sql_eval_toolkit/logging.py": "d1dacfc65224c4a83e1b6775ee288055ba0d719e8c12fe84c6c158f637d67201",
    "src/text2sql_eval_toolkit/inference/__init__.py": "175c9670991429b449f2edd09103833eddd4a65a9a13c3153ea6151da96d0367",
    "src/text2sql_eval_toolkit/inference/inference_tools.py": "e56a78755a85fd8f92583562f59f3c843e8c7a0e1edf1bf37b3ccdb2ddddb3f8",
    "src/text2sql_eval_toolkit/analysis/__init__.py": "175c9670991429b449f2edd09103833eddd4a65a9a13c3153ea6151da96d0367",
    "src/text2sql_eval_toolkit/analysis/error_analysis.py": "c2c60f5cfd64923f1e3f83929b11d6c25ab4b23d768189dc39a0b7bff9aa3727",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PinnedIbmOfficialEvaluator:
    """Execute reviewed IBM source in its isolated, pinned checkout environment."""

    def __init__(self, checkout: Path, *, python_executable: Path | None = None) -> None:
        self.checkout = checkout.resolve()
        self.python_executable = (
            python_executable.resolve()
            if python_executable
            else (self.checkout / ".venv" / "Scripts" / "python.exe").resolve()
        )

    def verify_checkout(self) -> dict[str, Any]:
        if not self.checkout.is_dir():
            raise RuntimeError("IBM_OFFICIAL_CHECKOUT_NOT_FOUND")
        head = subprocess.run(
            ["git", "-C", str(self.checkout), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        if head != IBM_UPSTREAM_COMMIT:
            raise RuntimeError(f"IBM_UPSTREAM_COMMIT_MISMATCH:{head}")
        mismatches: list[str] = []
        for relative, expected in SELECTED_SOURCE_SHA256.items():
            path = self.checkout / relative
            actual = _sha256(path) if path.is_file() else "MISSING"
            if actual != expected:
                mismatches.append(f"{relative}:{actual}")
        if mismatches:
            raise RuntimeError("IBM_SELECTED_SOURCE_HASH_MISMATCH:" + ",".join(mismatches))
        if not self.python_executable.is_file():
            raise RuntimeError("IBM_ISOLATED_PYTHON_NOT_FOUND")
        return {
            "upstream_commit": head,
            "selected_source_count": len(SELECTED_SOURCE_SHA256),
            "selected_source_sha256": dict(SELECTED_SOURCE_SHA256),
        }

    def evaluate(self, cases: list[dict[str, Any]]) -> dict[str, Any]:
        verification = self.verify_checkout()
        if len(cases) < 50:
            raise RuntimeError(f"IBM_CASE_COUNT_BELOW_GATE:{len(cases)}")
        bridge = Path(__file__).with_name("runtime_bridge.py").resolve()
        with tempfile.TemporaryDirectory(prefix="chatbi-ibm-official-") as directory:
            root = Path(directory)
            input_path = root / "input.json"
            output_path = root / "output.json"
            input_path.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    str(self.python_executable),
                    str(bridge),
                    "--checkout",
                    str(self.checkout),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=600,
            )
            if completed.returncode != 0:
                stderr = completed.stderr[-4000:].replace(str(self.checkout), "<IBM_CHECKOUT>")
                raise RuntimeError(f"IBM_OFFICIAL_RUNTIME_FAILED:{completed.returncode}:{stderr}")
            result = json.loads(output_path.read_text(encoding="utf-8"))
        result["checkout_verification"] = verification
        result["integration_mode"] = "PINNED_OFFICIAL_SOURCE_TOOL"
        return result
