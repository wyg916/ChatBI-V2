from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from app.evaluation.ibm_adapter import IbmText2SqlEvaluationAdapter
from app.evaluation.ibm_official.runner import (
    CANONICAL_SELECTED_SOURCE_SHA256,
    IBM_UPSTREAM_COMMIT,
    PinnedIbmOfficialEvaluator,
    SELECTED_SOURCE_SHA256,
)
from app.evaluation.ibm_official.runtime_bridge import diagnostic_category
from scripts import run_v13_ibm_official_eval as official_gate


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


def _git_bytes(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout


def _canonical_repo(
    tmp_path: Path,
) -> tuple[Path, Path, str, str, str, PinnedIbmOfficialEvaluator]:
    repo = tmp_path / "canonical-upstream"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.email", "canonical-integrity@chatbi.invalid")
    _git(repo, "config", "user.name", "ChatBI Canonical Integrity Test")
    _git(repo, "config", "core.autocrlf", "false")

    relative = "src/selected.py"
    source = repo / relative
    source.parent.mkdir(parents=True)
    source.write_bytes(b"alpha\nbeta\n")
    _git(repo, "add", "--", relative)
    _git(repo, "commit", "--quiet", "-m", "fixture")

    head = _git(repo, "rev-parse", "HEAD")
    canonical_bytes = _git_bytes(repo, "show", f"{head}:{relative}")
    canonical_hash = hashlib.sha256(canonical_bytes).hexdigest()
    blob_oid = _git(repo, "rev-parse", f"{head}:{relative}")
    python_executable = repo / "python-test-boundary"
    python_executable.write_text("test boundary only\n", encoding="utf-8")
    evaluator = PinnedIbmOfficialEvaluator(
        repo,
        python_executable=python_executable,
        upstream_commit=head,
        selected_source_sha256={relative: canonical_hash},
    )
    return repo, source, relative, canonical_hash, blob_oid, evaluator


def test_official_runner_is_pinned_and_separate_from_clean_room_adapter() -> None:
    adapter = IbmText2SqlEvaluationAdapter()
    assert IBM_UPSTREAM_COMMIT == adapter.upstream_commit
    assert adapter.implementation_origin == "chatbi-clean-room"
    assert adapter.upstream_runtime_calls == 0
    assert len(SELECTED_SOURCE_SHA256) == 11
    assert all(len(value) == 64 for value in SELECTED_SOURCE_SHA256.values())
    assert SELECTED_SOURCE_SHA256 is CANONICAL_SELECTED_SOURCE_SHA256


def test_canonical_git_blob_hash_is_independent_from_checkout_eol(tmp_path: Path) -> None:
    repo, source, relative, canonical_hash, blob_oid, evaluator = _canonical_repo(tmp_path)

    lf_verification = evaluator.verify_checkout()
    _git(repo, "config", "core.autocrlf", "true")
    _git(repo, "config", "core.eol", "crlf")
    source.unlink()
    _git(repo, "checkout", "--", relative)
    assert b"\r\n" in source.read_bytes()

    crlf_verification = evaluator.verify_checkout()

    assert lf_verification["selected_source_sha256"] == {relative: canonical_hash}
    assert crlf_verification["selected_source_sha256"] == {relative: canonical_hash}
    assert crlf_verification["selected_source_git_blob_oid"] == {relative: blob_oid}


def test_lf_checkout_passes_canonical_integrity_gate(tmp_path: Path) -> None:
    _, source, relative, canonical_hash, blob_oid, evaluator = _canonical_repo(tmp_path)
    assert b"\r\n" not in source.read_bytes()

    verification = evaluator.verify_checkout()

    assert verification["canonical_hash_source"] == "git-blob"
    assert verification["selected_worktree_clean"] is True
    assert verification["selected_source_sha256"] == {relative: canonical_hash}
    assert verification["selected_source_git_blob_oid"] == {relative: blob_oid}


def test_crlf_clean_worktree_passes_canonical_integrity_gate(tmp_path: Path) -> None:
    repo, source, relative, _, _, evaluator = _canonical_repo(tmp_path)
    _git(repo, "config", "core.autocrlf", "true")
    _git(repo, "config", "core.eol", "crlf")
    source.unlink()
    _git(repo, "checkout", "--", relative)
    assert b"\r\n" in source.read_bytes()
    subprocess.run(
        ["git", "-C", str(repo), "diff", "--quiet", "HEAD", "--", relative],
        check=True,
        timeout=30,
    )

    verification = evaluator.verify_checkout()

    assert verification["selected_worktree_clean"] is True


def test_committed_source_content_change_fails_canonical_hash_gate(tmp_path: Path) -> None:
    repo, source, relative, canonical_hash, _, evaluator = _canonical_repo(tmp_path)
    source.write_bytes(b"changed semantic source\n")
    _git(repo, "add", "--", relative)
    _git(repo, "commit", "--quiet", "-m", "changed source")
    evaluator.upstream_commit = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(RuntimeError, match="IBM_SELECTED_SOURCE_HASH_MISMATCH"):
        evaluator.verify_checkout()
    assert evaluator.selected_source_sha256 == {relative: canonical_hash}


def test_wrong_ibm_commit_fails_before_source_verification(tmp_path: Path) -> None:
    _, _, _, _, _, evaluator = _canonical_repo(tmp_path)
    evaluator.upstream_commit = "0" * 40

    with pytest.raises(RuntimeError, match="IBM_UPSTREAM_COMMIT_MISMATCH"):
        evaluator.verify_checkout()


def test_missing_selected_source_fails_closed(tmp_path: Path) -> None:
    _, source, relative, _, _, evaluator = _canonical_repo(tmp_path)
    source.unlink()

    with pytest.raises(RuntimeError, match=f"IBM_SELECTED_SOURCE_MISSING:{relative}"):
        evaluator.verify_checkout()


def test_selected_worktree_tamper_fails_closed(tmp_path: Path) -> None:
    _, source, _, _, _, evaluator = _canonical_repo(tmp_path)
    source.write_bytes(b"tampered but uncommitted\n")

    with pytest.raises(RuntimeError, match="IBM_SELECTED_SOURCE_WORKTREE_DIRTY"):
        evaluator.verify_checkout()


def test_official_runner_rejects_missing_checkout(tmp_path: Path) -> None:
    evaluator = PinnedIbmOfficialEvaluator(tmp_path / "missing")
    with pytest.raises(RuntimeError, match="IBM_OFFICIAL_CHECKOUT_NOT_FOUND"):
        evaluator.verify_checkout()


def test_empty_result_policy_preserves_official_subset_metric() -> None:
    result = {
        "execution_accuracy": 1,
        "subset_non_empty_execution_accuracy": 0,
    }
    assert diagnostic_category(result) == "EMPTY_RESULT_POLICY_DIAGNOSTIC_NOT_APPLICABLE"
    assert result["execution_accuracy"] == 1
    assert result["subset_non_empty_execution_accuracy"] == 0


def test_live_gate_authenticates_through_the_chatbi_api_cookie_boundary(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("CHATBI_BOOTSTRAP_ADMIN_PASSWORD", "unit-test-only")
    monkeypatch.setattr(
        official_gate,
        "_api",
        lambda base_url, method, path, body=None: calls.append((base_url, method, path, body)),
    )

    official_gate._authenticate("https://chatbi.invalid/api/v1", "admin@chatbi.local")

    assert calls == [(
        "https://chatbi.invalid/api/v1",
        "POST",
        "/auth/login",
        {"email": "admin@chatbi.local", "password": "unit-test-only"},
    )]


def test_runtime_evidence_contract_from_real_run() -> None:
    evidence_path = Path(
        "E:/ChatBI_V2_Evidence/V1.3.0/Phase2_Closure_20260821_160111/04_ibm_official_runtime.json"
    )
    if not evidence_path.exists():
        pytest.skip("official runtime evidence is produced by the release-gate script")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    official = evidence["official"]
    assert evidence["license_closure"] == "PASS_SELECTED_APACHE_2_0_SOURCE_ONLY"
    assert official["checkout_verification"]["upstream_commit"] == IBM_UPSTREAM_COMMIT
    assert official["implementation_origin"] == "ibm-selected-source"
    assert official["runtime_calls"] >= 50
    assert official["case_count"] >= 50
    assert official["multiple_ground_truth"] is True
    assert official["execution_compare"] == "PASS"
    assert official["error_analysis"] == "PASS"
    g50 = next(item for item in official["cases"] if item["id"] == "G50")
    assert g50["execution_accuracy"] == 1
    assert g50["subset_non_empty_execution_accuracy"] == 0
    assert g50["diagnostic"] == "EMPTY_RESULT_POLICY_DIAGNOSTIC_NOT_APPLICABLE"
    assert evidence["sql_execution_rate"] >= 0.98
    assert evidence["result_value_accuracy"] >= 0.95
    assert evidence["release_gate"] == "PASS"
