from __future__ import annotations

import hashlib

import pytest

from app.core.access import Principal
from app.evaluation.ibm_adapter import IbmText2SqlEvaluationAdapter
from app.models import AnswerVersion, DataSource, VerifiedAnswer, Workspace
from app.query.service import QueryPipeline
from app.schemas.evaluation import FeedbackReplayRequest, FeedbackReviewRequest
from app.services.feedback_loop import (
    FLOW_ID,
    feedback_provenance,
    replay_verified_sql,
    review_correction,
)
from app.services.seed import seed_demo_semantic_model


def test_ibm_compatibility_adapter_does_not_claim_official_runtime() -> None:
    adapter = IbmText2SqlEvaluationAdapter()

    provenance = adapter.provenance()
    assert provenance == {
        "implementation_origin": "chatbi-clean-room",
        "upstream_repository": "https://github.com/IBM/text2sql-eval-toolkit",
        "upstream_commit": "60dd4515236adb335f2053b7c069397d7d88fe0a",
        "upstream_runtime_status": "BLOCKED_LICENSE_METADATA_CONFLICT",
        "upstream_runtime_calls": 0,
        "license_evidence": {
            "root_license": "Apache-2.0",
            "distribution_metadata_license": "MIT",
            "closure": "CONFLICT_UNRESOLVED",
        },
    }
    summary = adapter.summarize([])
    assert summary["provenance"] == provenance


def _draft_correction(db_session) -> tuple[VerifiedAnswer, Principal]:
    model = seed_demo_semantic_model(db_session)
    datasource = db_session.get(DataSource, model.datasource_id)
    workspace = db_session.get(Workspace, model.workspace_id)
    answer = VerifiedAnswer(
        workspace_id=workspace.id,
        question="按地区统计收入",
        module="评测反馈",
        sql_synced=False,
        model_name=f"Semantic v{model.version}",
        owner_name="Reviewer",
        status="DRAFT",
        accuracy_percent=100,
        query_run_id=None,
        sql_text=None,
        result_signature="a" * 64,
        semantic_model_version=model.version,
        semantic_intent={},
        sql_plan={},
        result_snapshot={"columns": ["region"], "rows": [{"region": "华东"}]},
        semantic_model_id=model.id,
        datasource_id=datasource.id,
        oracle_status="PASSED",
        feedback={
            "flow": FLOW_ID,
            "workflow_state": "CORRECTION_SUBMITTED",
            "corrected_sql": "SELECT region_name AS region FROM demo_business.regions",
            "review_history": [],
            "replays": [],
        },
    )
    db_session.add(answer)
    db_session.flush()
    db_session.add(AnswerVersion(answer_id=answer.id, version=1, snapshot={"status": "DRAFT"}))
    db_session.commit()
    return answer, Principal(None, workspace.id, "reviewer@chatbi.local", "Reviewer", "ADMIN")


def test_review_attests_verified_sql_and_tampering_fails_before_query_pipeline(
    client, db_session, monkeypatch,
) -> None:
    answer, principal = _draft_correction(db_session)

    reviewed = review_correction(
        db_session,
        answer_id=answer.id,
        data=FeedbackReviewRequest(decision="APPROVE", comment="Oracle 与业务口径已复核"),
        principal=principal,
    )
    db_session.refresh(answer)
    assert reviewed["status"] == "VERIFIED"
    assert answer.feedback["verified_sql_sha256"] == hashlib.sha256(
        answer.sql_text.encode("utf-8")
    ).hexdigest()
    assert answer.feedback["verified_datasource_id"] == answer.datasource_id
    assert answer.feedback["verified_semantic_model_id"] == answer.semantic_model_id
    assert feedback_provenance()["upstream_runtime_calls"] == 0

    answer.sql_text = "DELETE FROM demo_business.orders"
    db_session.commit()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("tampered SQL must fail before QueryPipeline execution")

    monkeypatch.setattr(QueryPipeline, "execute", fail_if_called)
    with pytest.raises(ValueError, match="integrity attestation failed"):
        replay_verified_sql(
            db_session,
            answer_id=answer.id,
            data=FeedbackReplayRequest(
                question="按区域统计营收",
                datasource_id=answer.datasource_id,
                semantic_model_id=answer.semantic_model_id,
            ),
            principal=principal,
        )


def test_replay_rejects_resource_rebinding_before_query_pipeline(
    client, db_session, monkeypatch,
) -> None:
    answer, principal = _draft_correction(db_session)
    review_correction(
        db_session,
        answer_id=answer.id,
        data=FeedbackReviewRequest(decision="APPROVE", comment="Oracle 与业务口径已复核"),
        principal=principal,
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("resource rebinding must fail before QueryPipeline execution")

    monkeypatch.setattr(QueryPipeline, "execute", fail_if_called)
    with pytest.raises(ValueError, match="datasource binding"):
        replay_verified_sql(
            db_session,
            answer_id=answer.id,
            data=FeedbackReplayRequest(
                question="按区域统计营收",
                datasource_id="foreign-datasource",
                semantic_model_id=answer.semantic_model_id,
            ),
            principal=principal,
        )
