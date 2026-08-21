from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation.ibm_adapter import IbmText2SqlEvaluationAdapter
from app.evaluation.ibm_official.runner import (
    IBM_UPSTREAM_COMMIT,
    PinnedIbmOfficialEvaluator,
    SELECTED_SOURCE_SHA256,
)
from app.evaluation.ibm_official.runtime_bridge import diagnostic_category


def test_official_runner_is_pinned_and_separate_from_clean_room_adapter() -> None:
    adapter = IbmText2SqlEvaluationAdapter()
    assert IBM_UPSTREAM_COMMIT == adapter.upstream_commit
    assert adapter.implementation_origin == "chatbi-clean-room"
    assert adapter.upstream_runtime_calls == 0
    assert len(SELECTED_SOURCE_SHA256) == 11
    assert all(len(value) == 64 for value in SELECTED_SOURCE_SHA256.values())


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
