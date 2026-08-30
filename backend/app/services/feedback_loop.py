from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased

from app.core.access import (
    Principal,
    ensure_query_run_access,
    ensure_resource_access,
    grant_created_resource,
    has_resource_access,
)
from app.models import (
    AnswerVersion,
    BusinessTerm,
    EvaluationCaseResult,
    EvaluationRun,
    QueryFeedback,
    QueryRun,
    ResourceGrant,
    SemanticModel,
    VerifiedAnswer,
)
from app.query.contracts import AskRequest, ExpectedResult
from app.query.service import QueryPipeline
from app.schemas.evaluation import (
    FeedbackCorrectionCreate,
    FeedbackDecisionRequest,
    FeedbackRecallRequest,
    FeedbackReplayRequest,
    FeedbackReviewStartRequest,
    FeedbackReviewRequest,
    UserFeedbackCreate,
)
from app.services.content import public_answer_payload


FLOW_ID = "SQLBOT_FEEDBACK_V2_1"
PHASE4_FLOW_ID = "CHATBI_FEEDBACK_V1_3"
IMPLEMENTATION_ORIGIN = "chatbi-clean-room"
SQLBOT_UPSTREAM_COMMIT = "2a86aa926c4a22400a4ab4506c3ec384f7855a9d"
SQLBOT_RUNTIME_STATUS = "BLOCKED_MODIFIED_GPL_BRANDING_CONDITIONS"
SQLBOT_RUNTIME_CALLS = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sql_sha256(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def feedback_provenance() -> dict[str, Any]:
    """Describe the clean-room boundary without claiming SQLBot reuse."""
    return {
        "implementation_origin": IMPLEMENTATION_ORIGIN,
        "upstream_repository": "https://github.com/dataease/SQLBot",
        "upstream_commit": SQLBOT_UPSTREAM_COMMIT,
        "upstream_runtime_status": SQLBOT_RUNTIME_STATUS,
        "upstream_runtime_calls": SQLBOT_RUNTIME_CALLS,
    }


def _verified_sql_attestation(answer: VerifiedAnswer, sql: str) -> dict[str, Any]:
    return {
        "verified_sql_sha256": _sql_sha256(sql),
        "verified_workspace_id": answer.workspace_id,
        "verified_datasource_id": answer.datasource_id,
        "verified_semantic_model_id": answer.semantic_model_id,
        "verified_semantic_model_version": answer.semantic_model_version,
        "verified_result_signature": answer.result_signature,
    }


def _assert_verified_sql_integrity(answer: VerifiedAnswer) -> None:
    feedback = answer.feedback or {}
    if feedback.get("flow") not in {FLOW_ID, PHASE4_FLOW_ID}:
        raise ValueError("Verified SQL is not a ChatBI feedback correction")
    sql = answer.sql_text or ""
    expected = feedback.get("verified_sql_sha256")
    if not expected or expected != _sql_sha256(sql):
        raise ValueError("Verified SQL integrity attestation failed")
    bindings = {
        "verified_datasource_id": answer.datasource_id,
        "verified_semantic_model_id": answer.semantic_model_id,
        "verified_semantic_model_version": answer.semantic_model_version,
        "verified_result_signature": answer.result_signature,
    }
    if feedback.get("flow") == PHASE4_FLOW_ID:
        bindings["verified_workspace_id"] = answer.workspace_id
    if any(feedback.get(name) != value for name, value in bindings.items()):
        raise ValueError("Verified SQL resource attestation failed")


def _tokens(value: str) -> set[str]:
    compact = re.sub(r"\s+", "", value.lower())
    chinese_bigrams = {compact[index:index + 2] for index in range(max(0, len(compact) - 1))}
    words = set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", value.lower()))
    return chinese_bigrams | words


def _score(question: str, candidate: str) -> float:
    left = _tokens(question)
    right = _tokens(candidate)
    jaccard = len(left & right) / len(left | right) if left or right else 0.0
    sequence = SequenceMatcher(None, question.lower(), candidate.lower()).ratio()
    return round(jaccard * 0.65 + sequence * 0.35, 4)


def _version(db: Session, answer_id: str) -> int:
    return int(db.scalar(select(func.coalesce(func.max(AnswerVersion.version), 0)).where(AnswerVersion.answer_id == answer_id)) or 0)


def _snapshot(answer: VerifiedAnswer) -> dict[str, Any]:
    return {
        "question": answer.question,
        "status": answer.status,
        "sql": answer.sql_text,
        "result_signature": answer.result_signature,
        "semantic_intent": answer.semantic_intent,
        "sql_plan": answer.sql_plan,
        "result_snapshot": answer.result_snapshot,
        "oracle_status": answer.oracle_status,
        "feedback": answer.feedback,
    }


def _workflow(answer: VerifiedAnswer, version: int) -> dict[str, Any]:
    feedback = answer.feedback or {}
    return {
        "answer_id": answer.id,
        "query_run_id": answer.query_run_id,
        "status": answer.status,
        "workflow_state": str(feedback.get("workflow_state") or "UNKNOWN"),
        "question": answer.question,
        "corrected_sql": answer.sql_text or feedback.get("corrected_sql"),
        "oracle_status": answer.oracle_status,
        "version": version,
        "feedback": feedback,
        "reviewer": feedback.get("reviewer_email"),
        "question_pattern": feedback.get("question_pattern"),
        "replay_count": len(feedback.get("replays") or []),
    }


def _public_workflow(
    db: Session,
    answer: VerifiedAnswer,
    version: int,
) -> dict[str, Any]:
    """Return one workflow without exposing stored SQL literals or errors."""

    payload = _workflow(answer, version)
    public_answer = public_answer_payload(db, answer)
    public_feedback = public_answer.get("feedback") or {}
    payload["question"] = public_answer.get("question") or answer.question
    payload["corrected_sql"] = (
        public_answer.get("sql_text")
        or public_feedback.get("corrected_sql")
        or public_feedback.get("candidate_sql")
    )
    payload["feedback"] = public_feedback
    return payload


def _public_candidate(
    db: Session,
    answer: VerifiedAnswer,
    *,
    score: float,
) -> dict[str, Any]:
    public_answer = public_answer_payload(db, answer)
    return {
        "answer_id": answer.id,
        "question": str(public_answer.get("question") or ""),
        "sql": str(public_answer.get("sql_text") or ""),
        "score": score,
        "version": _version(db, answer.id),
        "status": answer.status,
    }


def _authorized_answer_statement(statement, principal: Principal):
    """Scope Answer reads through all three executable resource grants."""

    statement = statement.where(VerifiedAnswer.workspace_id == principal.workspace_id)
    if principal.role == "ADMIN":
        return statement
    if not principal.user_id:
        return statement.where(VerifiedAnswer.id == "")

    answer_grant = aliased(ResourceGrant)
    datasource_grant = aliased(ResourceGrant)
    model_grant = aliased(ResourceGrant)
    return (
        statement
        .join(answer_grant, and_(
            answer_grant.user_id == principal.user_id,
            answer_grant.resource_type == "ANSWER",
            answer_grant.resource_id == VerifiedAnswer.id,
            answer_grant.can_read.is_(True),
            answer_grant.can_query.is_(True),
        ))
        .join(datasource_grant, and_(
            datasource_grant.user_id == principal.user_id,
            datasource_grant.resource_type == "DATASOURCE",
            datasource_grant.resource_id == VerifiedAnswer.datasource_id,
            datasource_grant.can_query.is_(True),
        ))
        .join(model_grant, and_(
            model_grant.user_id == principal.user_id,
            model_grant.resource_type == "SEMANTIC_MODEL",
            model_grant.resource_id == VerifiedAnswer.semantic_model_id,
            model_grant.can_query.is_(True),
        ))
    )


def _ensure_answer_query_access(
    db: Session,
    principal: Principal,
    answer: VerifiedAnswer,
) -> None:
    ensure_resource_access(
        db, principal, resource_type="ANSWER", resource_id=answer.id, query=True,
    )
    ensure_resource_access(
        db,
        principal,
        resource_type="DATASOURCE",
        resource_id=answer.datasource_id or "",
        query=True,
    )
    ensure_resource_access(
        db,
        principal,
        resource_type="SEMANTIC_MODEL",
        resource_id=answer.semantic_model_id or "",
        query=True,
    )


def _run(db: Session, query_run_id: str, principal: Principal) -> QueryRun:
    run = db.get(QueryRun, query_run_id)
    if run is None or run.workspace_id != principal.workspace_id:
        raise LookupError("Query run not found")
    ensure_query_run_access(db, principal, run, require_owner=True)
    return run


def record_correct_feedback(
    db: Session,
    *,
    query_run_id: str,
    comment: str | None,
    principal: Principal,
) -> QueryFeedback:
    run = _run(db, query_run_id, principal)
    if run.status != "SUCCEEDED" or (run.oracle_payload or {}).get("status") != "PASSED":
        raise ValueError("Only an Oracle-passed answer can receive correct feedback")
    feedback = db.scalar(select(QueryFeedback).where(
        QueryFeedback.query_run_id == run.id,
        QueryFeedback.feedback_type == "HELPFUL",
    ))
    if feedback is None:
        feedback = QueryFeedback(query_run_id=run.id, feedback_type="HELPFUL", comment=comment)
        db.add(feedback)
    else:
        feedback.comment = comment
    db.commit()
    db.refresh(feedback)
    return feedback


def record_user_feedback(
    db: Session,
    *,
    data: UserFeedbackCreate,
    principal: Principal,
) -> dict[str, Any]:
    """Create one persisted OPEN review item without promoting user SQL."""
    source = _run(db, data.query_run_id, principal)
    if data.sentiment == "THUMB_DOWN" and not data.reason:
        raise ValueError("Thumb down feedback requires a reason")
    if data.sentiment == "THUMB_UP" and (
        source.status != "SUCCEEDED" or (source.oracle_payload or {}).get("status") != "PASSED"
    ):
        raise ValueError("Thumb up requires an Oracle-passed query result")

    feedback_type = "HELPFUL" if data.sentiment == "THUMB_UP" else "INCORRECT"
    feedback_row = db.scalar(select(QueryFeedback).where(
        QueryFeedback.query_run_id == source.id,
        QueryFeedback.feedback_type == feedback_type,
    ))
    if feedback_row is None:
        feedback_row = QueryFeedback(
            query_run_id=source.id,
            feedback_type=feedback_type,
            comment=data.comment,
        )
        db.add(feedback_row)
    else:
        feedback_row.comment = data.comment

    existing = [answer for answer in db.scalars(select(VerifiedAnswer).where(
        VerifiedAnswer.workspace_id == principal.workspace_id,
        VerifiedAnswer.query_run_id == source.id,
        VerifiedAnswer.status == "DRAFT",
    )) if (answer.feedback or {}).get("flow") == PHASE4_FLOW_ID]
    if existing:
        raise ValueError("This query already has an open feedback review")

    candidate_sql = source.normalized_sql or source.generated_sql
    answer = VerifiedAnswer(
        workspace_id=source.workspace_id,
        question=source.question,
        module="评测反馈",
        sql_synced=False,
        model_name=f"Semantic v{source.semantic_model_version}",
        owner_name=principal.display_name,
        status="DRAFT",
        accuracy_percent=round(float((source.oracle_payload or {}).get("confidence") or 0) * 100, 2),
        sort_order=int(db.scalar(select(func.coalesce(func.max(VerifiedAnswer.sort_order), 0))) or 0) + 1,
        query_run_id=source.id,
        sql_text=None,
        result_signature=source.result_signature,
        semantic_model_version=source.semantic_model_version,
        semantic_intent={
            "intent": (source.plan_payload or {}).get("intent"),
            "metrics": (source.plan_payload or {}).get("metrics", []),
            "dimensions": (source.plan_payload or {}).get("dimensions", []),
            "filters": (source.plan_payload or {}).get("filters", []),
            "time_range": (source.plan_payload or {}).get("time_range"),
        },
        sql_plan=source.plan_payload or {},
        result_snapshot=source.execution_payload or {},
        chart_spec=source.chart_spec_payload or {},
        narrative=source.narrative_payload or {},
        semantic_model_id=source.semantic_model_id,
        datasource_id=source.datasource_id,
        oracle_status=(source.oracle_payload or {}).get("status"),
        feedback={
            "flow": PHASE4_FLOW_ID,
            "workflow_state": "OPEN",
            "source_query_run_id": source.id,
            "sentiment": data.sentiment,
            "reason": data.reason,
            "user_comment": data.comment,
            "candidate_sql": candidate_sql,
            "opened_at": _now(),
            "review_history": [],
            "replays": [],
        },
    )
    db.add(answer)
    db.flush()
    grant_created_resource(
        db, principal, resource_type="ANSWER", resource_id=answer.id,
    )
    db.add(AnswerVersion(answer_id=answer.id, version=1, snapshot=_snapshot(answer)))
    db.commit()
    db.refresh(answer)
    return _public_workflow(db, answer, 1)


def start_feedback_review(
    db: Session,
    *,
    answer_id: str,
    data: FeedbackReviewStartRequest,
    principal: Principal,
) -> dict[str, Any]:
    answer = db.get(VerifiedAnswer, answer_id)
    if answer is None or answer.workspace_id != principal.workspace_id:
        raise LookupError("Feedback review not found")
    _ensure_answer_query_access(db, principal, answer)
    feedback = answer.feedback or {}
    if feedback.get("flow") != PHASE4_FLOW_ID:
        raise ValueError("Answer is not a Phase 4 feedback review")
    if feedback.get("workflow_state") != "OPEN" or answer.status != "DRAFT":
        raise ValueError("Only an OPEN feedback item can enter review")
    history = list(feedback.get("review_history") or [])
    history.append({
        "action": "START_REVIEW",
        "comment": data.comment,
        "reviewer_id": principal.user_id,
        "reviewer": principal.email,
        "at": _now(),
    })
    answer.feedback = {
        **feedback,
        "workflow_state": "IN_REVIEW",
        "reviewer_id": principal.user_id,
        "reviewer_email": principal.email,
        "review_started_at": _now(),
        "review_history": history,
    }
    next_version = _version(db, answer.id) + 1
    db.flush()
    db.add(AnswerVersion(answer_id=answer.id, version=next_version, snapshot=_snapshot(answer)))
    db.commit()
    db.refresh(answer)
    return _public_workflow(db, answer, next_version)


def _feedback_regression_case(
    db: Session,
    *,
    answer: VerifiedAnswer,
    verification: QueryRun,
    question_pattern: str,
) -> None:
    evaluation = db.scalar(select(EvaluationRun).where(
        EvaluationRun.workspace_id == answer.workspace_id,
        EvaluationRun.release_name == "Feedback Regression v1.3",
    ).order_by(EvaluationRun.created_at.desc()))
    if evaluation is None:
        evaluation = EvaluationRun(
            workspace_id=answer.workspace_id,
            release_name="Feedback Regression v1.3",
            model_name=answer.model_name,
            status="COMPLETED",
            is_current=False,
            trend_points=[{
                "kind": "evaluation_profile",
                "profile": {"version": "v1.3", "artifacts": ["db:evaluation_case_result"]},
            }],
        )
        db.add(evaluation)
        db.flush()
    case_id = f"feedback-{answer.id}-v{_version(db, answer.id) + 1}"
    db.add(EvaluationCaseResult(
        evaluation_run_id=evaluation.id,
        case_id=case_id,
        category="FEEDBACK_VERIFIED_SQL",
        question=question_pattern,
        status="PASSED",
        execution_ok=True,
        result_ok=True,
        semantic_ok=True,
        expected={
            "workspace_id": answer.workspace_id,
            "datasource_id": answer.datasource_id,
            "semantic_model_id": answer.semantic_model_id,
            "result_signature": answer.result_signature,
        },
        actual={
            "guard_allowed": bool((verification.guard_payload or {}).get("allowed")),
            "execution_status": (verification.execution_payload or {}).get("status"),
            "oracle_status": (verification.oracle_payload or {}).get("status"),
            "result_signature": verification.result_signature,
        },
        generated_sql=verification.normalized_sql or verification.generated_sql,
        query_run_id=verification.id,
    ))
    evaluation.golden_set_count += 1
    evaluation.sql_execution_pass_count += 1
    evaluation.result_value_pass_count += 1
    evaluation.semantic_pass_count += 1
    evaluation.sql_generation_rate = 100.0
    evaluation.result_accuracy = 100.0
    evaluation.semantic_accuracy = 100.0
    evaluation.completed_at = datetime.now(timezone.utc)
    evaluation.manifest_sha256 = hashlib.sha256(
        f"{evaluation.id}:{case_id}:{verification.result_signature}".encode("utf-8")
    ).hexdigest()


def decide_feedback_review(
    db: Session,
    *,
    answer_id: str,
    data: FeedbackDecisionRequest,
    principal: Principal,
) -> dict[str, Any]:
    answer = db.get(VerifiedAnswer, answer_id)
    if answer is None or answer.workspace_id != principal.workspace_id:
        raise LookupError("Feedback review not found")
    _ensure_answer_query_access(db, principal, answer)
    feedback = answer.feedback or {}
    if feedback.get("flow") != PHASE4_FLOW_ID:
        raise ValueError("Answer is not a Phase 4 feedback review")
    if feedback.get("workflow_state") != "IN_REVIEW" or answer.status != "DRAFT":
        raise ValueError("Only an IN_REVIEW feedback item can be decided")
    if feedback.get("reviewer_id") and feedback.get("reviewer_id") != principal.user_id:
        raise ValueError("Feedback review is assigned to another reviewer")
    history = list(feedback.get("review_history") or [])
    history.append({
        "action": "DECISION",
        "decision": data.decision,
        "comment": data.comment,
        "reviewer_id": principal.user_id,
        "reviewer": principal.email,
        "at": _now(),
    })
    next_version = _version(db, answer.id) + 1
    if data.decision == "REJECT":
        answer.status = "REJECTED"
        answer.sql_synced = False
        answer.feedback = {
            **feedback,
            "workflow_state": "REJECTED",
            "review_history": history,
            "decided_at": _now(),
        }
        db.flush()
        db.add(AnswerVersion(answer_id=answer.id, version=next_version, snapshot=_snapshot(answer)))
        db.commit()
        db.refresh(answer)
        return _public_workflow(db, answer, next_version)

    source = _run(db, str(feedback.get("source_query_run_id") or ""), principal)
    if source.datasource_id != answer.datasource_id or source.semantic_model_id != answer.semantic_model_id:
        raise ValueError("Feedback resource binding changed before verification")
    sql = data.corrected_sql or feedback.get("candidate_sql")
    if not sql:
        raise ValueError("Accepted feedback requires reviewer SQL")
    expected_rows = data.expected_rows
    if expected_rows is None:
        expected_rows = list((answer.result_snapshot or {}).get("rows") or [])
    expected_columns = data.expected_columns or list((answer.result_snapshot or {}).get("columns") or [])
    pipeline = QueryPipeline()
    verification = pipeline.execute(db, AskRequest(
        question=str(sql),
        datasource_id=answer.datasource_id,
        semantic_model_id=answer.semantic_model_id,
        row_limit=500,
    ), principal=principal)
    if (verification.execution_payload or {}).get("status") == "SUCCEEDED":
        verification = pipeline.verify(db, verification, ExpectedResult(
            columns=expected_columns,
            rows=expected_rows,
            tolerance=0.0001,
            order_independent=True,
        ))
    verification_passed = bool(
        verification.workspace_id == answer.workspace_id
        and verification.datasource_id == answer.datasource_id
        and verification.semantic_model_id == answer.semantic_model_id
        and (verification.guard_payload or {}).get("allowed")
        and (verification.execution_payload or {}).get("status") == "SUCCEEDED"
        and (verification.oracle_payload or {}).get("status") == "PASSED"
    )
    if not verification_passed:
        raise ValueError("Verified SQL requires Guard, resource binding, execution and Result Oracle PASS")

    answer.status = "VERIFIED"
    answer.sql_synced = True
    answer.sql_text = verification.normalized_sql or verification.generated_sql
    answer.query_run_id = verification.id
    answer.result_signature = verification.result_signature
    answer.result_snapshot = verification.execution_payload or {}
    answer.oracle_status = "PASSED"
    question_pattern = data.question_pattern or answer.question
    attestation = _verified_sql_attestation(answer, answer.sql_text or "")
    answer.feedback = {
        **feedback,
        "workflow_state": "ACCEPTED",
        "review_history": history,
        "reviewer_id": principal.user_id,
        "reviewer_email": principal.email,
        "question_pattern": question_pattern,
        "verification_query_run_id": verification.id,
        "verification_result": {
            "guard_allowed": True,
            "execution_status": "SUCCEEDED",
            "oracle_status": "PASSED",
            "result_signature": verification.result_signature,
        },
        "accepted_at": _now(),
        **attestation,
    }
    _feedback_regression_case(
        db,
        answer=answer,
        verification=verification,
        question_pattern=question_pattern,
    )
    db.flush()
    db.add(AnswerVersion(answer_id=answer.id, version=next_version, snapshot=_snapshot(answer)))
    db.commit()
    db.refresh(answer)
    return _public_workflow(db, answer, next_version)


def submit_correction(
    db: Session,
    *,
    data: FeedbackCorrectionCreate,
    principal: Principal,
) -> dict[str, Any]:
    source = _run(db, data.query_run_id, principal)
    feedback = db.scalar(select(QueryFeedback).where(
        QueryFeedback.query_run_id == source.id,
        QueryFeedback.feedback_type == "INCORRECT",
    ))
    if feedback is None:
        feedback = QueryFeedback(query_run_id=source.id, feedback_type="INCORRECT", comment=data.comment)
        db.add(feedback)
    else:
        feedback.comment = data.comment
    db.commit()

    # A correction is never executed directly. Direct SQL re-enters the public
    # QueryPipeline and must pass Context -> NL2SQL -> AST Guard -> Executor.
    pipeline = QueryPipeline()
    corrected = pipeline.execute(db, AskRequest(
        question=data.corrected_sql,
        datasource_id=source.datasource_id,
        semantic_model_id=source.semantic_model_id,
        row_limit=500,
    ), principal=principal)
    columns = data.expected_columns or (list(data.expected_rows[0]) if data.expected_rows else list((corrected.execution_payload or {}).get("columns") or []))
    if (corrected.execution_payload or {}).get("status") == "SUCCEEDED":
        corrected = pipeline.verify(db, corrected, ExpectedResult(
            columns=columns,
            rows=data.expected_rows,
            tolerance=0.0001,
            order_independent=True,
        ))

    answer = VerifiedAnswer(
        workspace_id=source.workspace_id,
        question=source.question,
        module="评测反馈",
        sql_synced=False,
        model_name=f"Semantic v{source.semantic_model_version}",
        owner_name=data.owner_name,
        status="DRAFT",
        accuracy_percent=round(float((corrected.oracle_payload or {}).get("confidence") or 0) * 100, 2),
        sort_order=int(db.scalar(select(func.coalesce(func.max(VerifiedAnswer.sort_order), 0))) or 0) + 1,
        query_run_id=corrected.id,
        # Keep unreviewed SQL out of ContextBuilder, which only sees non-null
        # sql_text values. It is promoted into sql_text after approval.
        sql_text=None,
        result_signature=corrected.result_signature,
        semantic_model_version=source.semantic_model_version,
        semantic_intent={
            "intent": (source.plan_payload or {}).get("intent"),
            "metrics": (source.plan_payload or {}).get("metrics", []),
            "dimensions": (source.plan_payload or {}).get("dimensions", []),
            "filters": (source.plan_payload or {}).get("filters", []),
            "time_range": (source.plan_payload or {}).get("time_range"),
        },
        sql_plan=corrected.plan_payload or {},
        result_snapshot=corrected.execution_payload or {},
        chart_spec=corrected.chart_spec_payload or {},
        narrative=corrected.narrative_payload or {},
        semantic_model_id=source.semantic_model_id,
        datasource_id=source.datasource_id,
        oracle_status=(corrected.oracle_payload or {}).get("status"),
        feedback={
            "flow": FLOW_ID,
            "workflow_state": "CORRECTION_SUBMITTED",
            "source_query_run_id": source.id,
            "correction_query_run_id": corrected.id,
            "corrected_sql": corrected.normalized_sql or corrected.generated_sql,
            "user_verdict": "INCORRECT",
            "user_comment": data.comment,
            "submitted_at": _now(),
            "review_history": [],
            "replays": [],
        },
    )
    db.add(answer)
    db.flush()
    grant_created_resource(
        db, principal, resource_type="ANSWER", resource_id=answer.id,
    )
    db.add(AnswerVersion(answer_id=answer.id, version=1, snapshot=_snapshot(answer)))
    db.commit()
    db.refresh(answer)
    return _public_workflow(db, answer, 1)


def review_correction(
    db: Session,
    *,
    answer_id: str,
    data: FeedbackReviewRequest,
    principal: Principal,
) -> dict[str, Any]:
    answer = db.get(VerifiedAnswer, answer_id)
    if answer is None or answer.workspace_id != principal.workspace_id:
        raise LookupError("Feedback correction not found")
    _ensure_answer_query_access(db, principal, answer)
    if (answer.feedback or {}).get("flow") != FLOW_ID:
        raise ValueError("Answer is not a feedback correction")
    if answer.status != "DRAFT":
        raise ValueError("Only a DRAFT correction can be reviewed")
    if data.decision == "APPROVE" and answer.oracle_status != "PASSED":
        raise ValueError("Only an Oracle-passed correction can be promoted to Verified SQL")

    next_version = _version(db, answer.id) + 1
    history = list((answer.feedback or {}).get("review_history") or [])
    history.append({
        "decision": data.decision,
        "comment": data.comment,
        "reviewer": principal.email,
        "at": _now(),
    })
    answer.status = "VERIFIED" if data.decision == "APPROVE" else "REJECTED"
    answer.sql_synced = data.decision == "APPROVE"
    if data.decision == "APPROVE":
        answer.sql_text = str((answer.feedback or {}).get("corrected_sql") or "") or None
        if not answer.sql_text:
            raise ValueError("Correction has no SQL to promote")
    attestation = _verified_sql_attestation(answer, answer.sql_text) if data.decision == "APPROVE" else {}
    answer.feedback = {
        **(answer.feedback or {}),
        "workflow_state": "VERIFIED_SQL" if data.decision == "APPROVE" else "REVIEW_REJECTED",
        "review_history": history,
        "verified_at": _now() if data.decision == "APPROVE" else None,
        **attestation,
    }
    db.flush()
    db.add(AnswerVersion(answer_id=answer.id, version=next_version, snapshot=_snapshot(answer)))
    db.commit()
    db.refresh(answer)
    return _public_workflow(db, answer, next_version)


def recall_candidates(
    db: Session,
    *,
    data: FeedbackRecallRequest,
    principal: Principal,
    limit: int = 5,
) -> list[dict[str, Any]]:
    statement = _authorized_answer_statement(select(VerifiedAnswer).where(
        VerifiedAnswer.status == "VERIFIED",
        VerifiedAnswer.oracle_status == "PASSED",
        VerifiedAnswer.sql_text.is_not(None),
    ), principal)
    if data.datasource_id:
        statement = statement.where(VerifiedAnswer.datasource_id == data.datasource_id)
    if data.semantic_model_id:
        statement = statement.where(VerifiedAnswer.semantic_model_id == data.semantic_model_id)
    answers = list(db.scalars(
        statement.order_by(
            VerifiedAnswer.accuracy_percent.desc(),
            VerifiedAnswer.updated_at.desc(),
        ).limit(100)
    ))
    # Preserve the database's accuracy/freshness order when lexical scores tie.
    # Sorting tied rows by random UUID makes a newly approved correction fall
    # outside the top five after repeated feedback runs with the same wording.
    ranked = sorted(
        ((_score(data.question, answer.question), rank, answer) for rank, answer in enumerate(answers)),
        key=lambda item: (-item[0], item[1], item[2].id),
    )
    return [
        _public_candidate(db, answer, score=score)
        for score, _, answer in ranked[:limit]
        if score > 0
    ]


def replay_verified_sql(
    db: Session,
    *,
    answer_id: str,
    data: FeedbackReplayRequest,
    principal: Principal,
) -> dict[str, Any]:
    answer = db.get(VerifiedAnswer, answer_id)
    if answer is None or answer.workspace_id != principal.workspace_id:
        raise LookupError("Verified SQL not found")
    _ensure_answer_query_access(db, principal, answer)
    if answer.status != "VERIFIED" or answer.oracle_status != "PASSED" or not answer.sql_text:
        raise ValueError("Candidate is not an approved Verified SQL")
    _assert_verified_sql_integrity(answer)
    if data.datasource_id and data.datasource_id != answer.datasource_id:
        raise ValueError("Verified SQL datasource binding does not match replay request")
    if data.semantic_model_id and data.semantic_model_id != answer.semantic_model_id:
        raise ValueError("Verified SQL semantic-model binding does not match replay request")
    candidates = recall_candidates(db, data=data, principal=principal)
    candidate = next((item for item in candidates if item["answer_id"] == answer.id), None)
    if candidate is None:
        raise ValueError("Verified SQL was not recalled for the similar question")

    pipeline = QueryPipeline()
    replay = pipeline.execute(db, AskRequest(
        question=answer.sql_text,
        datasource_id=answer.datasource_id,
        semantic_model_id=answer.semantic_model_id,
        row_limit=500,
    ), principal=principal)
    expected_rows = data.expected_rows if data.expected_rows is not None else list((answer.result_snapshot or {}).get("rows") or [])
    expected_columns = data.expected_columns or list((answer.result_snapshot or {}).get("columns") or [])
    if (replay.execution_payload or {}).get("status") == "SUCCEEDED":
        replay = pipeline.verify(db, replay, ExpectedResult(
            columns=expected_columns,
            rows=expected_rows,
            tolerance=0.0001,
            order_independent=True,
            expected_signature=answer.result_signature if data.expected_rows is None else None,
        ))
    replay_passed = bool(
        (replay.guard_payload or {}).get("allowed")
        and (replay.oracle_payload or {}).get("status") == "PASSED"
    )
    events = list((answer.feedback or {}).get("replays") or [])
    events.append({
        "question": data.question,
        "candidate_score": candidate["score"],
        "query_run_id": replay.id,
        "guard_allowed": bool((replay.guard_payload or {}).get("allowed")),
        "oracle_status": (replay.oracle_payload or {}).get("status"),
        "passed": replay_passed,
        "workspace_id": principal.workspace_id,
        "at": _now(),
    })
    current_feedback = answer.feedback or {}
    answer.feedback = {
        **current_feedback,
        "workflow_state": (
            "ACCEPTED"
            if current_feedback.get("flow") == PHASE4_FLOW_ID
            else "REGRESSION_PASS" if replay_passed else "REGRESSION_FAIL"
        ),
        "last_replay_status": "PASS" if replay_passed else "FAIL",
        "replays": events,
    }
    answer.adoption_count += 1
    answer.monthly_adoption_count += 1
    next_version = _version(db, answer.id) + 1
    db.flush()
    db.add(AnswerVersion(answer_id=answer.id, version=next_version, snapshot=_snapshot(answer)))
    db.commit()
    total, passed = replay_totals(db, principal=principal)
    return {
        "candidate": candidate,
        "query_run_id": replay.id,
        "guard_status": "PASS" if (replay.guard_payload or {}).get("allowed") else "FAIL",
        "oracle_status": str((replay.oracle_payload or {}).get("status") or "NOT_RUN"),
        "result_signature": replay.result_signature,
        "replay_passed": replay_passed,
        "replay_rate": round(passed / total, 4) if total else 0.0,
    }


def replay_totals(db: Session, *, principal: Principal) -> tuple[int, int]:
    statement = _authorized_answer_statement(
        select(VerifiedAnswer).where(VerifiedAnswer.status == "VERIFIED"),
        principal,
    )
    events = [event for answer in db.scalars(statement) for event in ((answer.feedback or {}).get("replays") or [])]
    return len(events), sum(bool(event.get("passed")) for event in events)


def _term_business_key(item: BusinessTerm) -> tuple[str, str]:
    return (
        " ".join(item.term.split()).casefold(),
        " ".join(item.mapped_object.split()).casefold(),
    )


def feedback_dashboard(db: Session, *, principal: Principal) -> dict[str, Any]:
    workflow_statement = _authorized_answer_statement(
        select(VerifiedAnswer).where(VerifiedAnswer.feedback.is_not(None)),
        principal,
    )
    answers = [
        answer
        for answer in db.scalars(
            workflow_statement.order_by(VerifiedAnswer.updated_at.desc())
        )
        if (answer.feedback or {}).get("flow") in {FLOW_ID, PHASE4_FLOW_ID}
    ]
    term_rows = list(db.execute(
        select(BusinessTerm, SemanticModel)
        .join(SemanticModel, SemanticModel.id == BusinessTerm.semantic_model_id)
        .where(SemanticModel.workspace_id == principal.workspace_id)
        .order_by(
            BusinessTerm.term,
            BusinessTerm.mapped_object,
            BusinessTerm.semantic_model_id,
            BusinessTerm.id,
        )
    ))
    if principal.role != "ADMIN":
        term_rows = [
            (item, model)
            for item, model in term_rows
            if has_resource_access(
                db,
                principal,
                resource_type="SEMANTIC_MODEL",
                resource_id=model.id,
                query=True,
            )
            and has_resource_access(
                db,
                principal,
                resource_type="DATASOURCE",
                resource_id=model.datasource_id,
                query=True,
            )
        ]
    # Duplicate copies of the same term-to-object mapping can exist across
    # semantic-model versions. Collapse that stable business key, but retain
    # the same term when it deliberately maps to a different semantic object.
    terms_by_key: dict[tuple[str, str], BusinessTerm] = {}
    for item, _ in term_rows:
        terms_by_key.setdefault(_term_business_key(item), item)
    terms = list(terms_by_key.values())
    examples = recall_candidates(
        db,
        data=FeedbackRecallRequest(question="经营分析"),
        principal=principal,
        limit=20,
    )
    # The dashboard shows all approved examples, even if a generic probe has no
    # lexical overlap. Recall endpoints still require a positive similarity.
    if not examples:
        verified_statement = _authorized_answer_statement(select(VerifiedAnswer).where(
            VerifiedAnswer.status == "VERIFIED",
            VerifiedAnswer.oracle_status == "PASSED",
            VerifiedAnswer.sql_text.is_not(None),
        ), principal)
        verified = list(db.scalars(
            verified_statement.order_by(VerifiedAnswer.updated_at.desc()).limit(20)
        ))
        examples = [
            _public_candidate(db, answer, score=1.0)
            for answer in verified
        ]
    total, passed = replay_totals(db, principal=principal)
    return {
        "provenance": feedback_provenance(),
        "terminology": [{
            "id": item.id,
            "semantic_model_id": item.semantic_model_id,
            "business_key": "::".join(_term_business_key(item)),
            "term": item.term,
            "synonyms": item.synonyms,
            "definition": item.definition,
            "mapped_object": item.mapped_object,
        } for item in terms],
        "sql_examples": examples,
        "workflows": [
            _public_workflow(db, answer, _version(db, answer.id))
            for answer in answers
        ],
        "total_replays": total,
        "passed_replays": passed,
        "feedback_replay_rate": round(passed / total, 4) if total else 0.0,
    }
