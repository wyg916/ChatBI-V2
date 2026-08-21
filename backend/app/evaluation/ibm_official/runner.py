from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any


IBM_UPSTREAM_COMMIT = "60dd4515236adb335f2053b7c069397d7d88fe0a"

# Every Python file executed by runtime_bridge.py is locked to the reviewed IBM
# commit. The sole file without an SPDX header is evaluation/__init__.py; it is
# an unmodified package initializer governed by the repository Apache-2.0
# LICENSE. The package/wheel metadata path is deliberately not used.
CANONICAL_SELECTED_SOURCE_SHA256 = {
    "src/text2sql_eval_toolkit/evaluation/__init__.py": "591df0dd1e437c07a35164294ccd23fd508562bc2564e2efafb737aec600cae3",
    "src/text2sql_eval_toolkit/evaluation/evaluation_tools.py": "86afcae7775b450f7c913fdcce9386d6b52d3bcec27303da0fc3a69f12fa5684",
    "src/text2sql_eval_toolkit/evaluation/llm_as_judge.py": "88204d754aa2ea2fc310641697803aabb3b2743ff5f8a4ade670235b5e9d4cfc",
    "src/text2sql_eval_toolkit/metrics/__init__.py": "410996bda7c5a3ae16e31305c47d814af2ce3d9f9f2ffd7532bcf7ac6b3d9c78",
    "src/text2sql_eval_toolkit/metrics/text2sql_utils.py": "211727bd42b7d34d5685dc3671161fcfb50f4579ce88c8bf9c8f394ff93b66e9",
    "src/text2sql_eval_toolkit/utils.py": "baa5946fcdcc97a354ea851c9813f6fd2c4d5bd04118c24f44b37e8b55df51f8",
    "src/text2sql_eval_toolkit/logging.py": "a578b9be523b06bb938b34963769d22e83a56603a8e1baf6085f09eb3b6ecd22",
    "src/text2sql_eval_toolkit/inference/__init__.py": "6bdd279222aa0ea556f720557ab4548f4d1fcdafc59396b626161a54273ca9f1",
    "src/text2sql_eval_toolkit/inference/inference_tools.py": "7a69915d4b36e142d004daef87b9843bfea587f0592ecc5f971fe3488cadb8b6",
    "src/text2sql_eval_toolkit/analysis/__init__.py": "6bdd279222aa0ea556f720557ab4548f4d1fcdafc59396b626161a54273ca9f1",
    "src/text2sql_eval_toolkit/analysis/error_analysis.py": "07c4254b15b74bd72706bc5fe9159441b6ebc6937ad9fa26e47393399e506c0f",
}

# Backward-compatible export for evidence and integrations written before the
# canonical Git-blob contract was introduced.
SELECTED_SOURCE_SHA256 = CANONICAL_SELECTED_SOURCE_SHA256


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class PinnedIbmOfficialEvaluator:
    """Execute reviewed IBM source in its isolated, pinned checkout environment."""

    def __init__(
        self,
        checkout: Path,
        *,
        python_executable: Path | None = None,
        upstream_commit: str = IBM_UPSTREAM_COMMIT,
        selected_source_sha256: Mapping[str, str] | None = None,
    ) -> None:
        self.checkout = checkout.resolve()
        self.upstream_commit = upstream_commit
        self.selected_source_sha256 = dict(
            selected_source_sha256 or CANONICAL_SELECTED_SOURCE_SHA256
        )
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
        if head != self.upstream_commit:
            raise RuntimeError(f"IBM_UPSTREAM_COMMIT_MISMATCH:{head}")

        missing = [
            relative
            for relative in self.selected_source_sha256
            if not (self.checkout / relative).is_file()
        ]
        if missing:
            raise RuntimeError("IBM_SELECTED_SOURCE_MISSING:" + ",".join(missing))

        worktree = subprocess.run(
            [
                "git",
                "-C",
                str(self.checkout),
                "diff",
                "--quiet",
                "HEAD",
                "--",
                *self.selected_source_sha256,
            ],
            check=False,
            capture_output=True,
            timeout=30,
        )
        if worktree.returncode == 1:
            raise RuntimeError("IBM_SELECTED_SOURCE_WORKTREE_DIRTY")
        if worktree.returncode != 0:
            raise RuntimeError(
                f"IBM_SELECTED_SOURCE_WORKTREE_STATUS_FAILED:{worktree.returncode}"
            )

        mismatches: list[str] = []
        blob_oids: dict[str, str] = {}
        for relative, expected in self.selected_source_sha256.items():
            revision = f"{self.upstream_commit}:{relative}"
            oid = subprocess.run(
                ["git", "-C", str(self.checkout), "rev-parse", revision],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout.strip()
            canonical_bytes = subprocess.run(
                ["git", "-C", str(self.checkout), "show", revision],
                check=True,
                capture_output=True,
                timeout=30,
            ).stdout
            actual = _sha256(canonical_bytes)
            blob_oids[relative] = oid
            if actual != expected:
                mismatches.append(f"{relative}:{actual}")
        if mismatches:
            raise RuntimeError("IBM_SELECTED_SOURCE_HASH_MISMATCH:" + ",".join(mismatches))
        if not self.python_executable.is_file():
            raise RuntimeError("IBM_ISOLATED_PYTHON_NOT_FOUND")
        return {
            "upstream_commit": head,
            "canonical_hash_source": "git-blob",
            "selected_worktree_clean": True,
            "selected_source_count": len(self.selected_source_sha256),
            "selected_source_sha256": dict(self.selected_source_sha256),
            "selected_source_git_blob_oid": blob_oids,
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
