from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import SandboxLimits


_ALLOWED_IMPORT_ROOTS = frozenset(
    {"datetime", "decimal", "json", "math", "numpy", "pandas", "statistics"}
)
_FORBIDDEN_CALLS = frozenset(
    {
        "__import__",
        "breakpoint",
        "compile",
        "delattr",
        "dir",
        "eval",
        "exec",
        "getattr",
        "globals",
        "help",
        "input",
        "locals",
        "memoryview",
        "open",
        "setattr",
        "vars",
    }
)
_FORBIDDEN_ATTRIBUTES = frozenset(
    {
        "connect",
        "environ",
        "exec",
        "exec_run",
        "fork",
        "get_archive",
        "getenv",
        "kill",
        "load",
        "load_library",
        "memmap",
        "open",
        "popen",
        "put_archive",
        "read_csv",
        "read_excel",
        "read_feather",
        "read_fwf",
        "read_hdf",
        "read_html",
        "read_json",
        "read_orc",
        "read_parquet",
        "read_pickle",
        "read_sas",
        "read_sql",
        "read_spss",
        "read_stata",
        "read_table",
        "read_xml",
        "remove",
        "rename",
        "replace",
        "request",
        "rmdir",
        "run",
        "send",
        "socket",
        "spawn",
        "system",
        "to_csv",
        "to_excel",
        "to_feather",
        "to_hdf",
        "to_json",
        "to_orc",
        "to_parquet",
        "to_pickle",
        "to_sql",
        "to_stata",
        "unlink",
        "urlopen",
    }
)
_FORBIDDEN_DATASET_KEY = re.compile(
    r"(?:api[_-]?key|authorization|bearer|credential|database[_-]?url|password|private[_-]?key|secret|token)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(?:-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|"
    r"\b(?:sk|ghp)_[A-Za-z0-9_-]{24,}|"
    r"\b(?:postgres(?:ql)?|mysql|mariadb)://[^\s]+|"
    r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*)",
    re.IGNORECASE,
)


class SandboxPolicyViolation(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GuardReport:
    code_sha256: str
    ast_nodes: int
    imports: tuple[str, ...]


class PythonCodeGuard:
    def __init__(self, limits: SandboxLimits | None = None) -> None:
        self.limits = limits or SandboxLimits()

    def validate(self, code: str, datasets: Mapping[str, Any]) -> GuardReport:
        import hashlib

        encoded = code.encode("utf-8")
        if not encoded or len(encoded) > self.limits.max_code_bytes:
            raise SandboxPolicyViolation("SANDBOX_CODE_SIZE", "code size exceeds policy")
        try:
            dataset_bytes = json.dumps(
                datasets,
                ensure_ascii=False,
                separators=(",", ":"),
                default=_reject_non_json,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise SandboxPolicyViolation(
                "SANDBOX_DATASET_TYPE", "dataset must be finite JSON data"
            ) from exc
        if len(dataset_bytes) > self.limits.max_dataset_bytes:
            raise SandboxPolicyViolation(
                "SANDBOX_DATASET_SIZE", "dataset payload exceeds policy"
            )
        _validate_dataset_secrets(datasets)
        try:
            tree = ast.parse(code, mode="exec")
        except SyntaxError as exc:
            raise SandboxPolicyViolation("SANDBOX_INVALID_SYNTAX", "invalid Python syntax") from exc
        nodes = list(ast.walk(tree))
        if len(nodes) > self.limits.max_ast_nodes:
            raise SandboxPolicyViolation("SANDBOX_AST_SIZE", "AST exceeds policy")

        imports: set[str] = set()
        for node in nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(_validate_import(alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    raise SandboxPolicyViolation(
                        "SANDBOX_IMPORT_DENIED", "relative imports are forbidden"
                    )
                imports.add(_validate_import(node.module or ""))
                for alias in node.names:
                    imported_name = alias.name.rsplit(".", 1)[-1].lower()
                    if (
                        imported_name in _FORBIDDEN_CALLS
                        or imported_name in _FORBIDDEN_ATTRIBUTES
                    ):
                        raise SandboxPolicyViolation(
                            "SANDBOX_API_DENIED",
                            f"imported API is forbidden: {imported_name}",
                        )
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                raise SandboxPolicyViolation(
                    "SANDBOX_SCOPE_MUTATION", "global/nonlocal mutation is forbidden"
                )
            elif isinstance(node, ast.Name) and node.id.startswith("__"):
                raise SandboxPolicyViolation(
                    "SANDBOX_DUNDER_DENIED", "dunder names are forbidden"
                )
            elif isinstance(node, ast.Attribute):
                if node.attr.startswith("__") or node.attr.lower() in _FORBIDDEN_ATTRIBUTES:
                    raise SandboxPolicyViolation(
                        "SANDBOX_API_DENIED", f"attribute is forbidden: {node.attr}"
                    )
            elif isinstance(node, ast.Call):
                name = _call_name(node.func)
                if name in _FORBIDDEN_CALLS or name.lower() in _FORBIDDEN_ATTRIBUTES:
                    raise SandboxPolicyViolation(
                        "SANDBOX_API_DENIED", f"call is forbidden: {name}"
                    )
        return GuardReport(
            code_sha256=hashlib.sha256(encoded).hexdigest(),
            ast_nodes=len(nodes),
            imports=tuple(sorted(imports)),
        )


def _validate_import(name: str) -> str:
    root = name.split(".", 1)[0]
    if root not in _ALLOWED_IMPORT_ROOTS:
        raise SandboxPolicyViolation(
            "SANDBOX_IMPORT_DENIED", f"import is not allowlisted: {root or '<empty>'}"
        )
    return root


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _reject_non_json(value: Any) -> None:
    raise TypeError(f"non-JSON dataset value: {type(value).__name__}")


def _validate_dataset_secrets(value: Any, *, key: str = "") -> None:
    if key and _FORBIDDEN_DATASET_KEY.search(key):
        raise SandboxPolicyViolation(
            "SANDBOX_SECRET_INPUT", "secret-shaped dataset field is forbidden"
        )
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            _validate_dataset_secrets(child_value, key=str(child_key))
    elif isinstance(value, (list, tuple)):
        for child in value:
            _validate_dataset_secrets(child)
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        raise SandboxPolicyViolation(
            "SANDBOX_SECRET_INPUT", "secret-shaped dataset value is forbidden"
        )
