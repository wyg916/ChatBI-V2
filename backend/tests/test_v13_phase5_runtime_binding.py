from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.certification.runtime_binding import (
    INTERNAL_PACKAGES,
    RuntimeBindingError,
    evaluate_runtime_binding,
)
from scripts import run_v13_model_gateway_smoke as smoke_runner


SHA = "a" * 40


def _candidate_layout(root: Path) -> tuple[dict[str, str], dict[str, tuple[str, ...]], list[str]]:
    package_files: dict[str, str] = {}
    package_exports: dict[str, tuple[str, ...]] = {}
    sys_path: list[str] = []
    for package in INTERNAL_PACKAGES:
        source_root = root / package.source_relative
        module_root = source_root.joinpath(*package.module.split("."))
        module_root.mkdir(parents=True, exist_ok=True)
        module_file = module_root / "__init__.py"
        module_file.write_text("# synthetic package binding fixture\n", encoding="utf-8")
        package_files[package.module] = str(module_file)
        package_exports[package.module] = package.required_exports
        sys_path.append(str(source_root))
    return package_files, package_exports, sys_path


def test_exact_sha_runtime_binding_accepts_only_candidate_sources_in_fresh_venv(tmp_path: Path) -> None:
    repo = tmp_path / "candidate"
    package_files, package_exports, sys_path = _candidate_layout(repo)
    executable = tmp_path / "certification-venv" / "Scripts" / "python.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()

    receipt = evaluate_runtime_binding(
        repo_root=repo,
        expected_git_sha=SHA,
        actual_git_sha=SHA,
        package_files=package_files,
        package_exports=package_exports,
        sys_path=sys_path,
        environ={"VIRTUAL_ENV": str(executable.parents[1])},
        python_executable=str(executable),
        prefix=str(executable.parents[1]),
        base_prefix=str(tmp_path / "base-python"),
    )

    assert receipt["status"] == "PASS"
    assert receipt["runtime_binding_gate"] == "PASS"
    assert receipt["import_preflight"] == "PASS"
    assert receipt["dbgpt_selected_runtime_import"] == "PASS"
    assert receipt["stale_editable_bindings"] == []


def test_stale_editable_binding_is_detected_before_provider_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "candidate"
    package_files, package_exports, sys_path = _candidate_layout(repo)
    stale_source = tmp_path / "old-worktree" / "packages" / "agent-orchestrator" / "src"
    stale_module = stale_source / "chatbi_agent_orchestrator" / "__init__.py"
    stale_module.parent.mkdir(parents=True)
    stale_module.write_text("# missing selected runtime export\n", encoding="utf-8")
    package_files["chatbi_agent_orchestrator"] = str(stale_module)
    package_exports["chatbi_agent_orchestrator"] = ()
    executable = tmp_path / "certification-venv" / "Scripts" / "python.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()

    receipt = evaluate_runtime_binding(
        repo_root=repo,
        expected_git_sha=SHA,
        actual_git_sha=SHA,
        package_files=package_files,
        package_exports=package_exports,
        sys_path=[*sys_path, str(stale_source)],
        environ={},
        python_executable=str(executable),
        prefix=str(executable.parents[1]),
        base_prefix=str(tmp_path / "base-python"),
        detected_stale_bindings=(f"PTH_OUTSIDE_CANDIDATE:stale.pth:{stale_source}",),
    )
    assert receipt["status"] == "FAIL"
    assert any("INTERNAL_PACKAGE_SOURCE_MISMATCH" in item for item in receipt["failures"])
    assert any("PTH_OUTSIDE_CANDIDATE" in item for item in receipt["failures"])

    provider_constructions = 0

    def blocked_preflight(**_kwargs):
        raise RuntimeBindingError("EXACT_SHA_RUNTIME_PREFLIGHT_FAILED", receipt=receipt)

    def forbidden_gateway(*_args, **_kwargs):
        nonlocal provider_constructions
        provider_constructions += 1
        raise AssertionError("provider gateway must not be constructed")

    monkeypatch.setattr(smoke_runner, "_arguments", lambda: SimpleNamespace(provider=["mimo"], output=tmp_path / "out.json"))
    monkeypatch.setattr(smoke_runner, "run_exact_sha_runtime_preflight", blocked_preflight)
    monkeypatch.setattr(smoke_runner, "ModelGateway", forbidden_gateway)
    monkeypatch.setenv("CHATBI_TEST_SHA", SHA)
    with pytest.raises(SystemExit, match="EXACT_SHA_RUNTIME_PREFLIGHT_FAILED"):
        smoke_runner.main()
    assert provider_constructions == 0


def test_selected_dbgpt_runtime_import_contract_is_explicit() -> None:
    from chatbi_agent_orchestrator import DbgptSelectedRuntimeOrchestrator
    from chatbi_dbgpt_runtime import DbgptAwelRuntime

    assert DbgptSelectedRuntimeOrchestrator.__name__ == "DbgptSelectedRuntimeOrchestrator"
    assert DbgptAwelRuntime.__name__ == "DbgptAwelRuntime"
