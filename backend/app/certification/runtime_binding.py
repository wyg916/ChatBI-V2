from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
import re
import site
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import unquote, urlparse


_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


class RuntimeBindingError(RuntimeError):
    """Fail-closed exact-SHA certification environment error."""

    def __init__(self, message: str, *, receipt: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.receipt = dict(receipt or {})


@dataclass(frozen=True)
class InternalPackage:
    distribution: str
    module: str
    source_relative: str
    required_exports: tuple[str, ...] = ()


INTERNAL_PACKAGES: tuple[InternalPackage, ...] = (
    InternalPackage("chatbi-backend", "app", "backend/app"),
    InternalPackage("chatbi-agent-contracts", "chatbi_agent_contracts", "packages/agent-contracts/src"),
    InternalPackage(
        "chatbi-agent-orchestrator",
        "chatbi_agent_orchestrator",
        "packages/agent-orchestrator/src",
        ("DbgptSelectedRuntimeOrchestrator",),
    ),
    InternalPackage(
        "chatbi-dbgpt-runtime-adapter",
        "chatbi_dbgpt_runtime",
        "packages/dbgpt-runtime-adapter/src",
        ("DbgptAwelRuntime",),
    ),
    InternalPackage(
        "chatbi-pandasai-selected-runtime",
        "pandasai_selected_runtime",
        "packages/pandasai-selected-runtime/src",
    ),
    InternalPackage("chatbi-prompt-registry", "chatbi_prompt_registry", "packages/prompt-registry/src"),
    InternalPackage("chatbi-rag-adapter", "chatbi_rag_adapter", "packages/rag-adapter/src"),
    InternalPackage("chatbi-rag-contracts", "chatbi_rag_contracts", "packages/rag-contracts/src"),
)


def _resolved(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().resolve()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _git(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeBindingError(
            f"EXACT_SHA_GIT_COMMAND_FAILED:{' '.join(arguments)}:{completed.stderr.strip()[:300]}"
        )
    return completed.stdout.strip()


def _path_hosts_internal_source(path: Path, packages: Sequence[InternalPackage]) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    for package in packages:
        module_path = Path(*package.module.split("."))
        if (path / module_path / "__init__.py").is_file() or (path / f"{package.module}.py").is_file():
            return True
        expected = path / package.source_relative
        if (expected / module_path / "__init__.py").is_file():
            return True
    return False


def _file_url_path(value: str) -> Path | None:
    parsed = urlparse(value)
    if parsed.scheme != "file":
        return None
    raw = unquote(parsed.path)
    if os.name == "nt" and re.match(r"^/[A-Za-z]:", raw):
        raw = raw[1:]
    return _resolved(raw)


def _active_site_roots(prefix: Path, sys_path: Sequence[str]) -> tuple[Path, ...]:
    candidates: list[Path] = []
    for raw in sys_path:
        if not raw:
            continue
        path = _resolved(raw)
        if path.name.casefold() in {"site-packages", "dist-packages"} and _inside(path, prefix):
            candidates.append(path)
    try:
        candidates.extend(_resolved(value) for value in site.getsitepackages())
    except AttributeError:
        pass
    unique: dict[str, Path] = {}
    for path in candidates:
        if path.exists() and _inside(path, prefix):
            unique[str(path).casefold()] = path
    return tuple(unique.values())


def _scan_pth_bindings(
    *, site_roots: Sequence[Path], repo_root: Path, packages: Sequence[InternalPackage]
) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    stale: list[str] = []
    for site_root in site_roots:
        for path in sorted(site_root.glob("*.pth")):
            references: list[str] = []
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                lines = path.read_text(encoding=sys.getfilesystemencoding(), errors="replace").splitlines()
            for line in lines:
                value = line.strip()
                if not value or value.startswith("#") or value.startswith("import "):
                    continue
                reference = _resolved(value if Path(value).is_absolute() else site_root / value)
                references.append(str(reference))
                if _path_hosts_internal_source(reference, packages) and not _inside(reference, repo_root):
                    stale.append(f"PTH_OUTSIDE_CANDIDATE:{path.name}:{reference}")
            if references or path.name.casefold().startswith("__editable__."):
                records.append({"path": str(path), "references": references})
    return records, stale


def _scan_direct_urls(
    *, site_roots: Sequence[Path], repo_root: Path, packages: Sequence[InternalPackage]
) -> tuple[list[dict[str, Any]], list[str]]:
    expected = {package.distribution.casefold().replace("_", "-") for package in packages}
    records: list[dict[str, Any]] = []
    stale: list[str] = []
    for distribution in importlib.metadata.distributions(path=[str(path) for path in site_roots]):
        name = str(distribution.metadata.get("Name") or "").casefold().replace("_", "-")
        if name not in expected:
            continue
        raw = distribution.read_text("direct_url.json")
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            stale.append(f"DIRECT_URL_INVALID:{name}")
            continue
        source = _file_url_path(str(payload.get("url") or ""))
        record = {
            "distribution": name,
            "editable": bool((payload.get("dir_info") or {}).get("editable")),
            "source": str(source) if source is not None else None,
        }
        records.append(record)
        if source is None or not _inside(source, repo_root):
            stale.append(f"DIRECT_URL_OUTSIDE_CANDIDATE:{name}:{source or 'NON_FILE_URL'}")
    return records, stale


def _sanitize_freeze_line(line: str) -> str:
    if " @ " not in line:
        return line
    name, source = line.split(" @ ", 1)
    parsed = urlparse(source)
    if not parsed.netloc:
        return line
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    sanitized = parsed._replace(netloc=host, query="", fragment="").geturl()
    return f"{name} @ {sanitized}"


def _pip_freeze() -> list[str]:
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--all"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return [f"PIP_FREEZE_FAILED:{completed.returncode}"]
    return [_sanitize_freeze_line(line) for line in completed.stdout.splitlines() if line.strip()]


def seal_runtime_preflight_receipt(
    receipt: Mapping[str, Any], **metadata: Any
) -> dict[str, Any]:
    payload = {**receipt, **metadata}
    payload.pop("receipt_sha256", None)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["receipt_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def evaluate_runtime_binding(
    *,
    repo_root: Path,
    expected_git_sha: str,
    actual_git_sha: str,
    package_files: Mapping[str, str],
    package_exports: Mapping[str, Sequence[str]],
    sys_path: Sequence[str],
    environ: Mapping[str, str],
    python_executable: str,
    prefix: str,
    base_prefix: str,
    pth_records: Sequence[Mapping[str, Any]] = (),
    direct_url_records: Sequence[Mapping[str, Any]] = (),
    detected_stale_bindings: Iterable[str] = (),
    packages: Sequence[InternalPackage] = INTERNAL_PACKAGES,
    worktree_clean: bool = True,
) -> dict[str, Any]:
    root = repo_root.resolve()
    failures = list(detected_stale_bindings)
    expected = expected_git_sha.strip().lower()
    actual = actual_git_sha.strip().lower()
    if not _FULL_SHA.fullmatch(expected):
        failures.append("EXPECTED_GIT_SHA_INVALID")
    if actual != expected:
        failures.append(f"ACTUAL_GIT_SHA_MISMATCH:{actual}")
    if not worktree_clean:
        failures.append("CERTIFICATION_WORKTREE_NOT_CLEAN")

    executable = _resolved(python_executable)
    runtime_prefix = _resolved(prefix)
    runtime_base_prefix = _resolved(base_prefix)
    if runtime_prefix == runtime_base_prefix:
        failures.append("FRESH_VIRTUAL_ENV_REQUIRED")
    if not _inside(executable, runtime_prefix):
        failures.append(f"PYTHON_EXECUTABLE_OUTSIDE_VENV:{executable}")
    declared_venv = str(environ.get("VIRTUAL_ENV") or "").strip()
    if declared_venv and _resolved(declared_venv) != runtime_prefix:
        failures.append(f"VIRTUAL_ENV_MISMATCH:{_resolved(declared_venv)}")

    python_path_entries = [entry for entry in str(environ.get("PYTHONPATH") or "").split(os.pathsep) if entry]
    for entry in python_path_entries:
        resolved = _resolved(entry)
        if not _inside(resolved, root):
            failures.append(f"PYTHONPATH_OUTSIDE_CANDIDATE:{resolved}")

    for raw in sys_path:
        if not raw:
            continue
        resolved = _resolved(raw)
        if _inside(resolved, runtime_prefix):
            # Installed wheels are verified package-by-package below against
            # direct_url provenance from the candidate repository.
            continue
        if _path_hosts_internal_source(resolved, packages) and not _inside(resolved, root):
            failures.append(f"SYS_PATH_INTERNAL_SOURCE_OUTSIDE_CANDIDATE:{resolved}")

    package_receipts: list[dict[str, Any]] = []
    direct_sources = {
        str(record.get("distribution") or "").casefold().replace("_", "-"): _resolved(str(record["source"]))
        for record in direct_url_records
        if record.get("source")
    }
    for package in packages:
        raw_module_file = package_files.get(package.module)
        expected_root = (root / package.source_relative).resolve()
        if not raw_module_file:
            failures.append(f"INTERNAL_PACKAGE_NOT_IMPORTED:{package.module}")
            module_file = None
            binding_kind = "MISSING"
        else:
            module_file = _resolved(raw_module_file)
            proven_source = direct_sources.get(package.distribution.casefold().replace("_", "-"))
            installed_artifact = (
                package.distribution != "chatbi-backend"
                and _inside(module_file, runtime_prefix)
                and proven_source is not None
                and _inside(proven_source, root)
            )
            if _inside(module_file, expected_root):
                binding_kind = "EXACT_WORKTREE_SOURCE"
            elif installed_artifact:
                binding_kind = "EXACT_WORKTREE_INSTALLED_ARTIFACT"
            else:
                binding_kind = "MISMATCH"
                failures.append(
                    f"INTERNAL_PACKAGE_SOURCE_MISMATCH:{package.module}:{module_file}:{expected_root}"
                )
        actual_exports = set(package_exports.get(package.module) or ())
        missing_exports = sorted(set(package.required_exports) - actual_exports)
        if missing_exports:
            failures.append(f"IMPORT_PREFLIGHT_MISSING_EXPORT:{package.module}:{','.join(missing_exports)}")
        package_receipts.append(
            {
                "distribution": package.distribution,
                "module": package.module,
                "module_file": str(module_file) if module_file is not None else None,
                "resolved_source_root": str(expected_root),
                "binding_kind": binding_kind,
                "required_exports": list(package.required_exports),
                "missing_exports": missing_exports,
            }
        )

    unique_failures = list(dict.fromkeys(failures))
    payload: dict[str, Any] = {
        "schema_version": "chatbi-exact-sha-runtime-preflight-v1",
        "status": "PASS" if not unique_failures else "FAIL",
        "runtime_binding_gate": "PASS" if not unique_failures else "FAIL",
        "import_preflight": "PASS" if not any("IMPORT_PREFLIGHT" in value or "NOT_IMPORTED" in value for value in unique_failures) else "FAIL",
        "dbgpt_selected_runtime_import": (
            "PASS"
            if "DbgptSelectedRuntimeOrchestrator" in set(package_exports.get("chatbi_agent_orchestrator") or ())
            and "DbgptAwelRuntime" in set(package_exports.get("chatbi_dbgpt_runtime") or ())
            else "FAIL"
        ),
        "expected_git_sha": expected,
        "actual_git_sha": actual,
        "candidate_repository_root": str(root),
        "worktree_clean": worktree_clean,
        "python_executable": str(executable),
        "python_version": sys.version,
        "virtual_env": str(runtime_prefix),
        "virtual_env_environment": declared_venv or None,
        "sys_path": [str(_resolved(value)) if value else str(Path.cwd().resolve()) for value in sys_path],
        "pythonpath": [str(_resolved(value)) for value in python_path_entries],
        "internal_packages": package_receipts,
        "pth_bindings": list(pth_records),
        "direct_url_bindings": list(direct_url_records),
        "stale_editable_bindings": unique_failures,
        "failures": unique_failures,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["receipt_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def run_exact_sha_runtime_preflight(
    *,
    repo_root: Path,
    expected_git_sha: str,
    include_pip_freeze: bool = False,
) -> dict[str, Any]:
    root = repo_root.expanduser().resolve()
    actual_sha = _git(root, "rev-parse", "HEAD").lower()
    worktree_clean = not bool(_git(root, "status", "--porcelain=v1", "--untracked-files=all"))
    package_files: dict[str, str] = {}
    package_exports: dict[str, Sequence[str]] = {}
    import_failures: list[str] = []
    importlib.invalidate_caches()
    for package in INTERNAL_PACKAGES:
        try:
            module = importlib.import_module(package.module)
            module_file = getattr(module, "__file__", None)
            if module_file:
                package_files[package.module] = str(module_file)
            package_exports[package.module] = tuple(
                name for name in package.required_exports if hasattr(module, name)
            )
        except Exception as exc:  # Fail closed while preserving only class, never provider/secret payloads.
            import_failures.append(f"INTERNAL_PACKAGE_IMPORT_FAILED:{package.module}:{type(exc).__name__}")

    prefix = _resolved(sys.prefix)
    site_roots = _active_site_roots(prefix, tuple(sys.path))
    pth_records, pth_stale = _scan_pth_bindings(
        site_roots=site_roots, repo_root=root, packages=INTERNAL_PACKAGES
    )
    direct_records, direct_stale = _scan_direct_urls(
        site_roots=site_roots, repo_root=root, packages=INTERNAL_PACKAGES
    )
    receipt = evaluate_runtime_binding(
        repo_root=root,
        expected_git_sha=expected_git_sha,
        actual_git_sha=actual_sha,
        package_files=package_files,
        package_exports=package_exports,
        sys_path=tuple(sys.path),
        environ=os.environ,
        python_executable=sys.executable,
        prefix=sys.prefix,
        base_prefix=sys.base_prefix,
        pth_records=pth_records,
        direct_url_records=direct_records,
        detected_stale_bindings=(*import_failures, *pth_stale, *direct_stale),
        worktree_clean=worktree_clean,
    )
    if include_pip_freeze:
        receipt = seal_runtime_preflight_receipt(receipt, pip_freeze=_pip_freeze())
    if receipt["status"] != "PASS":
        raise RuntimeBindingError("EXACT_SHA_RUNTIME_PREFLIGHT_FAILED", receipt=receipt)
    return receipt
