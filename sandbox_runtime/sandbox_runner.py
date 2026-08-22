from __future__ import annotations

import ast
import base64
import builtins as python_builtins
import hashlib
import io
import json
import os
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from typing import Any


ALLOWED_IMPORTS = {"datetime", "decimal", "json", "math", "numpy", "pandas", "statistics"}
ALLOWED_BUILTINS = {
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "len",
    "list", "max", "min", "print", "range", "round", "set", "sorted", "str",
    "sum", "tuple", "zip",
}
ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MAX_REQUEST_BYTES = 1024 * 1024


class LimitedText(io.StringIO):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit
        self.used = 0
        self.truncated = False

    def write(self, value: str) -> int:
        raw = value.encode("utf-8")
        remaining = max(0, self.limit - self.used)
        accepted = raw[:remaining].decode("utf-8", errors="ignore")
        self.used += len(accepted.encode("utf-8"))
        self.truncated = self.truncated or len(raw) > remaining
        return super().write(accepted)


def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".", 1)[0]
    if level or root not in ALLOWED_IMPORTS:
        raise ImportError(f"import denied: {root}")
    return python_builtins.__import__(name, globals, locals, fromlist, level)


def main() -> int:
    encoded_request = os.environ.pop("SANDBOX_REQUEST_B64", "")
    if not encoded_request or len(encoded_request) > MAX_REQUEST_BYTES * 2:
        raise ValueError("sandbox request environment is missing or oversized")
    raw_request = base64.b64decode(encoded_request, validate=True)
    if len(raw_request) > MAX_REQUEST_BYTES:
        raise ValueError("sandbox request is oversized")
    request = json.loads(raw_request.decode("utf-8"))
    code = str(request["code"])
    limits = request["limits"]
    max_output = int(limits["max_output_bytes"])
    max_file = int(limits["max_file_bytes"])
    max_files = int(limits["max_files"])
    ast.parse(code, mode="exec")

    stdout = LimitedText(max_output // 2)
    stderr = LimitedText(max_output // 2)
    artifacts: list[dict[str, Any]] = []

    def save_artifact(name: str, content: Any, media_type: str = "application/octet-stream") -> dict[str, Any]:
        if len(artifacts) >= max_files or not ARTIFACT_NAME.fullmatch(name) or ".." in name:
            raise ValueError("artifact policy violation")
        data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        if len(data) > max_file:
            raise ValueError("artifact exceeds file limit")
        item = {
            "name": name,
            "media_type": media_type,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "content_base64": base64.b64encode(data).decode("ascii"),
        }
        artifacts.append(item)
        return {key: value for key, value in item.items() if key != "content_base64"}

    builtins = {name: getattr(python_builtins, name) for name in ALLOWED_BUILTINS}
    builtins["__import__"] = safe_import
    namespace = {
        "__builtins__": builtins,
        "datasets": request["datasets"],
        "result": None,
        "save_artifact": save_artifact,
    }
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exec(compile(code, "<chatbi-sandbox>", "exec"), namespace, namespace)
        payload = {
            "status": "SUCCEEDED",
            "output": namespace.get("result"),
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
            "stdout_truncated": stdout.truncated,
            "stderr_truncated": stderr.truncated,
            "artifacts": artifacts,
        }
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > max_output:
            raise ValueError("response exceeds output limit")
    except BaseException as exc:
        payload = {
            "status": "FAILED",
            "error_code": "SANDBOX_CODE_FAILED",
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue() + type(exc).__name__,
            "stdout_truncated": stdout.truncated,
            "stderr_truncated": stderr.truncated,
            "artifacts": [],
        }
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sys.__stdout__.buffer.write(encoded[:max_output])
    return 0 if payload["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
