from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.evaluation.ibm_adapter import IbmText2SqlEvaluationAdapter
from app.models import (
    DataSource,
    DataSourceColumn,
    DataSourceSchema,
    DataSourceTable,
    EvaluationCaseResult,
    EvaluationRun,
    SemanticModel,
    VerifiedAnswer,
    Workspace,
)
from app.query.contracts import ExecutionResult
from app.query.executor import QueryExecutor
from app.services.seed import DEMO_MODEL_NAME, seed_demo_semantic_model
from app.services.evaluation import load_multiple_ground_truth


def _catalog(db_session):
    model = seed_demo_semantic_model(db_session)
    datasource = db_session.get(DataSource, model.datasource_id)
    if not db_session.scalar(select(DataSourceSchema.id).where(DataSourceSchema.datasource_id == datasource.id)):
        schema = DataSourceSchema(
            datasource_id=datasource.id,
            name="demo_business",
            qualified_name=f"{datasource.id}.demo_business",
        )
        db_session.add(schema)
        db_session.flush()
        definitions = {
            "orders": ["order_id", "region_id", "order_date", "revenue", "cost", "status"],
            "regions": ["region_id", "region_name"],
        }
        for table_name, columns in definitions.items():
            table = DataSourceTable(schema_id=schema.id, name=table_name, qualified_name=f"{schema.qualified_name}.{table_name}")
            db_session.add(table)
            db_session.flush()
            for column_name in columns:
                db_session.add(DataSourceColumn(
                    table_id=table.id,
                    name=column_name,
                    qualified_name=f"{table.qualified_name}.{column_name}",
                    data_type="TEXT",
                    nullable=True,
                ))
    datasource.status = "SYNCED"
    db_session.commit()
    return datasource, db_session.scalar(select(SemanticModel).where(SemanticModel.name == DEMO_MODEL_NAME))


def test_ibm_adapter_accepts_multiple_execution_ground_truths():
    assert set(load_multiple_ground_truth()) == {"G01", "G02", "G03", "G42"}
    result = IbmText2SqlEvaluationAdapter().compare_results(
        actual={"columns": ["revenue"], "rows": [{"revenue": 101.0}], "result_signature": "actual"},
        ground_truths=[
            {"id": "GT1", "columns": ["revenue"], "rows": [{"revenue": 100.0}]},
            {"id": "GT2", "columns": ["revenue"], "rows": [{"revenue": 101.0}]},
        ],
    )
    assert result["passed"] is True
    assert result["matched_ground_truth_id"] == "GT2"
    assert len(result["attempts"]) == 2


def test_evaluation_create_compare_dashboard_and_release_gate(client, db_session):
    seed_demo_semantic_model(db_session)
    created = client.post("/api/v1/evaluation/definitions", json={
        "name": "Prompt B comparison",
        "profile": {
            "model": "deterministic",
            "prompt": "prompt-b",
            "semantic_engine": "chatbi-semantic",
            "nl2sql_engine": "chatbi-nl2sql",
            "version": "v2.1.1",
        },
    })
    assert created.status_code == 201
    assert created.json()["status"] == "CREATED"
    assert created.json()["profile"]["prompt"] == "prompt-b"

    workspace_id = db_session.get(EvaluationRun, created.json()["id"]).workspace_id
    runs = []
    for index, prompt in enumerate(("prompt-a", "prompt-b"), start=1):
        run = EvaluationRun(
            workspace_id=workspace_id,
            release_name=f"Completed {prompt}",
            model_name="deterministic",
            status="PASS",
            is_current=index == 2,
            golden_set_count=50,
            sql_generation_rate=100,
            result_accuracy=100,
            semantic_accuracy=100,
            relevance_accuracy=100,
            average_response_seconds=float(index),
            completed_at=datetime.now(timezone.utc),
            manifest_sha256="a" * 64,
            sql_execution_pass_count=50,
            result_value_pass_count=50,
            semantic_pass_count=50,
            dangerous_sql_total=38,
            dangerous_sql_block_count=38,
            trend_points=[
                {"kind": "evaluation_profile", "profile": {
                    "model": "deterministic", "prompt": prompt, "semantic_engine": "chatbi-semantic",
                    "nl2sql_engine": "chatbi-nl2sql", "version": f"v2.1.{index}",
                }},
                {"date": "08/18", "value": 100},
            ],
        )
        db_session.add(run)
        db_session.flush()
        db_session.add(EvaluationCaseResult(
            evaluation_run_id=run.id,
            case_id=f"T{index}",
            category="metric",
            question="统计收入",
            status="PASS",
            execution_ok=True,
            result_ok=True,
            semantic_ok=True,
            actual={
                "accuracy_checks": {key: True for key in ("metric", "dimension", "time", "filter", "join", "result_value", "chart", "narrative")},
                "ground_truth_count": 2,
                "error_analysis": {"categories": []},
            },
        ))
        runs.append(run)
    db_session.commit()

    compared = client.post("/api/v1/evaluation/compare", json={"run_ids": [run.id for run in runs]})
    assert compared.status_code == 200
    assert compared.json()["axes"] == ["model", "prompt", "semantic_engine", "nl2sql_engine", "version"]
    assert compared.json()["winner_run_id"] == runs[0].id
    dashboard = client.get(f"/api/v1/evaluation/dashboard?run_id={runs[1].id}")
    assert dashboard.status_code == 200
    assert len(dashboard.json()["accuracy_cards"]) == 8
    assert dashboard.json()["current"]["multiple_ground_truth"] is True
    gate = client.get(f"/api/v1/evaluation/runs/{runs[1].id}/gate")
    assert gate.status_code == 200
    assert gate.json()["status"] == "PASS"


def test_evaluation_and_feedback_endpoints_hide_foreign_workspace_records(client, db_session):
    foreign_workspace = Workspace(name="Foreign Workspace")
    db_session.add(foreign_workspace)
    db_session.flush()
    foreign_run = EvaluationRun(
        workspace_id=foreign_workspace.id,
        release_name="Foreign evaluation",
        model_name="deterministic",
        status="PASS",
        golden_set_count=50,
        manifest_sha256="f" * 64,
    )
    db_session.add(foreign_run)
    db_session.flush()
    second_foreign_run = EvaluationRun(
        workspace_id=foreign_workspace.id,
        release_name="Second foreign evaluation",
        model_name="deterministic",
        status="PASS",
        golden_set_count=50,
        manifest_sha256="e" * 64,
    )
    foreign_case = EvaluationCaseResult(
        evaluation_run_id=foreign_run.id,
        case_id="FOREIGN-1",
        category="metric",
        question="foreign question",
        status="PASS",
    )
    foreign_answer = VerifiedAnswer(
        workspace_id=foreign_workspace.id,
        question="foreign verified SQL",
        module="评测反馈",
        model_name="deterministic",
        owner_name="Foreign Reviewer",
        status="VERIFIED",
        sql_text="SELECT 1",
        oracle_status="PASSED",
    )
    db_session.add_all([second_foreign_run, foreign_case, foreign_answer])
    db_session.commit()

    assert client.get(f"/api/v1/evaluation/runs/{foreign_run.id}").status_code == 404
    assert client.get(f"/api/v1/evaluation/cases/{foreign_case.id}").status_code == 404
    assert client.get(f"/api/v1/evaluation/dashboard?run_id={foreign_run.id}").status_code == 404
    assert client.get(f"/api/v1/evaluation/runs/{foreign_run.id}/gate").status_code == 404
    assert client.post(
        "/api/v1/evaluation/compare",
        json={"run_ids": [foreign_run.id, second_foreign_run.id]},
    ).status_code == 404
    assert client.post(
        f"/api/v1/evaluation/feedback/{foreign_answer.id}/review",
        json={"decision": "APPROVE", "comment": "must stay isolated"},
    ).status_code == 404
    assert client.post(
        f"/api/v1/evaluation/feedback/{foreign_answer.id}/replay",
        json={"question": "foreign question"},
    ).status_code == 404


def test_sqlbot_feedback_verified_sql_recall_and_replay(client, db_session, monkeypatch):
    datasource, model = _catalog(db_session)

    def fake_execute(self, *, datasource, normalized_sql, row_limit, timeout_ms):
        return ExecutionResult(
            status="SUCCEEDED",
            columns=["region", "revenue"],
            column_types=["TEXT", "NUMERIC"],
            rows=[{"region": "华东", "revenue": 100.0}],
            row_count=1,
            duration_ms=3,
            datasource_id=datasource.id,
            dialect=datasource.type,
            normalized_sql=normalized_sql,
            result_signature="b" * 64,
        )

    monkeypatch.setattr(QueryExecutor, "execute", fake_execute)
    asked = client.post("/api/v1/ask", json={
        "question": "按地区统计订单收入",
        "datasource_id": datasource.id,
        "semantic_model_id": model.id,
    })
    assert asked.status_code == 201
    query_id = asked.json()["id"]

    correct = client.post("/api/v1/evaluation/feedback/correct", json={"query_run_id": query_id, "comment": "结果正确"})
    assert correct.status_code == 201
    assert correct.json()["feedback_type"] == "HELPFUL"

    correction = client.post("/api/v1/evaluation/feedback/incorrect", json={
        "query_run_id": query_id,
        "comment": "业务口径需要人工修正",
        "corrected_sql": "SELECT r.region_name AS region, SUM(o.revenue) AS revenue FROM demo_business.orders o JOIN demo_business.regions r ON r.region_id = o.region_id GROUP BY r.region_name",
        "expected_columns": ["region", "revenue"],
        "expected_rows": [{"region": "华东", "revenue": 100.0}],
        "owner_name": "Reviewer",
    })
    assert correction.status_code == 201
    assert correction.json()["workflow_state"] == "CORRECTION_SUBMITTED"
    assert correction.json()["oracle_status"] == "PASSED"
    answer_id = correction.json()["answer_id"]
    assert db_session.get(VerifiedAnswer, answer_id).sql_text is None

    reviewed = client.post(f"/api/v1/evaluation/feedback/{answer_id}/review", json={
        "decision": "APPROVE",
        "comment": "Oracle 与业务口径均已复核",
    })
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "VERIFIED"
    assert reviewed.json()["version"] == 2
    assert db_session.get(VerifiedAnswer, answer_id).sql_text

    recall = client.post("/api/v1/evaluation/feedback/recall", json={
        "question": "按区域统计订单营收",
        "datasource_id": datasource.id,
        "semantic_model_id": model.id,
    })
    assert recall.status_code == 200
    assert recall.json()["candidates"][0]["answer_id"] == answer_id

    replay = client.post(f"/api/v1/evaluation/feedback/{answer_id}/replay", json={
        "question": "按区域统计订单营收",
        "datasource_id": datasource.id,
        "semantic_model_id": model.id,
    })
    assert replay.status_code == 200
    assert replay.json()["guard_status"] == "PASS"
    assert replay.json()["oracle_status"] == "PASSED"
    assert replay.json()["replay_passed"] is True
    assert replay.json()["replay_rate"] == 1.0

    dashboard = client.get("/api/v1/evaluation/feedback/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["feedback_replay_rate"] == 1.0
    assert dashboard.json()["workflows"][0]["workflow_state"] == "REGRESSION_PASS"
