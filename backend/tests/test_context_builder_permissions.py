from __future__ import annotations

from app.core.access import Principal
from app.models import (
    AppUser,
    DataSource,
    DataSourceColumn,
    DataSourceSchema,
    DataSourceTable,
    ResourceGrant,
    SemanticModel,
    VerifiedAnswer,
    Workspace,
)
from app.query.context_builder import ContextBuilder


def _datasource(workspace_id: str, name: str) -> DataSource:
    return DataSource(
        workspace_id=workspace_id,
        name=name,
        type="postgresql",
        host="localhost",
        port=5432,
        database="chatbi_test",
        username="readonly",
        password_encrypted="test-only",
        schema="public",
    )


def _verified_answer(
    *,
    workspace_id: str,
    datasource_id: str,
    semantic_model_id: str,
    question: str,
    sql: str,
    status: str = "VERIFIED",
    oracle_status: str = "PASSED",
) -> VerifiedAnswer:
    return VerifiedAnswer(
        workspace_id=workspace_id,
        datasource_id=datasource_id,
        semantic_model_id=semantic_model_id,
        question=question,
        module="TEST",
        model_name="Test model",
        owner_name="Test owner",
        status=status,
        oracle_status=oracle_status,
        accuracy_percent=99.0,
        sql_text=sql,
        result_signature=f"signature-{question}",
    )


def test_verified_examples_are_runtime_scoped_authorized_and_redacted(db_session) -> None:
    workspace = Workspace(name="Context permission workspace")
    db_session.add(workspace)
    db_session.flush()
    analyst = AppUser(
        workspace_id=workspace.id,
        email="context-analyst@chatbi.local",
        display_name="Context Analyst",
        role="ANALYST",
        status="ACTIVE",
    )
    datasource_a = _datasource(workspace.id, "Datasource A")
    datasource_b = _datasource(workspace.id, "Datasource B")
    db_session.add_all([analyst, datasource_a, datasource_b])
    db_session.flush()
    model_a = SemanticModel(
        workspace_id=workspace.id,
        datasource_id=datasource_a.id,
        name="Model A",
        status="PUBLISHED",
    )
    other_model_a = SemanticModel(
        workspace_id=workspace.id,
        datasource_id=datasource_a.id,
        name="Other model on A",
        status="PUBLISHED",
    )
    model_b = SemanticModel(
        workspace_id=workspace.id,
        datasource_id=datasource_b.id,
        name="Model B",
        status="PUBLISHED",
    )
    db_session.add_all([model_a, other_model_a, model_b])
    db_session.flush()

    schema = DataSourceSchema(
        datasource_id=datasource_a.id,
        name="public",
        qualified_name=f"{datasource_a.id}.public",
    )
    db_session.add(schema)
    db_session.flush()
    table = DataSourceTable(
        schema_id=schema.id,
        name="customers",
        qualified_name=f"{datasource_a.id}.public.customers",
    )
    db_session.add(table)
    db_session.flush()
    db_session.add(DataSourceColumn(
        table_id=table.id,
        name="email",
        qualified_name=f"{datasource_a.id}.public.customers.email",
        data_type="TEXT",
        nullable=False,
    ))

    allowed = _verified_answer(
        workspace_id=workspace.id,
        datasource_id=datasource_a.id,
        semantic_model_id=model_a.id,
        question="allowed answer",
        sql="SELECT COUNT(*) FROM customers WHERE email = 'private@example.com'",
    )
    ungranted = _verified_answer(
        workspace_id=workspace.id,
        datasource_id=datasource_a.id,
        semantic_model_id=model_a.id,
        question="ungranted answer",
        sql="SELECT COUNT(*) FROM customers",
    )
    read_only = _verified_answer(
        workspace_id=workspace.id,
        datasource_id=datasource_a.id,
        semantic_model_id=model_a.id,
        question="read-only answer",
        sql="SELECT COUNT(*) FROM customers",
    )
    foreign_datasource = _verified_answer(
        workspace_id=workspace.id,
        datasource_id=datasource_b.id,
        semantic_model_id=model_b.id,
        question="datasource B answer",
        sql="SELECT COUNT(*) FROM foreign_customers",
    )
    foreign_model = _verified_answer(
        workspace_id=workspace.id,
        datasource_id=datasource_a.id,
        semantic_model_id=other_model_a.id,
        question="other semantic model answer",
        sql="SELECT COUNT(*) FROM customers",
    )
    draft = _verified_answer(
        workspace_id=workspace.id,
        datasource_id=datasource_a.id,
        semantic_model_id=model_a.id,
        question="draft answer",
        sql="SELECT COUNT(*) FROM customers",
        status="DRAFT",
    )
    oracle_failed = _verified_answer(
        workspace_id=workspace.id,
        datasource_id=datasource_a.id,
        semantic_model_id=model_a.id,
        question="oracle failed answer",
        sql="SELECT COUNT(*) FROM customers",
        oracle_status="MISMATCH",
    )
    db_session.add_all([
        allowed,
        ungranted,
        read_only,
        foreign_datasource,
        foreign_model,
        draft,
        oracle_failed,
    ])
    db_session.flush()
    db_session.add_all([
        ResourceGrant(
            user_id=analyst.id,
            resource_type="ANSWER",
            resource_id=allowed.id,
            can_read=True,
            can_query=True,
        ),
        ResourceGrant(
            user_id=analyst.id,
            resource_type="ANSWER",
            resource_id=read_only.id,
            can_read=True,
            can_query=False,
        ),
        *[
            ResourceGrant(
                user_id=analyst.id,
                resource_type="ANSWER",
                resource_id=answer.id,
                can_read=True,
                can_query=True,
            )
            for answer in [foreign_datasource, foreign_model, draft, oracle_failed]
        ],
    ])
    db_session.commit()

    context = ContextBuilder().build(
        db_session,
        question="客户数量",
        workspace=workspace,
        datasource=datasource_a,
        semantic_model=model_a,
        row_limit=100,
        principal=Principal(
            analyst.id,
            workspace.id,
            analyst.email,
            analyst.display_name,
            analyst.role,
        ),
    )

    assert [item["question"] for item in context.verified_sql_examples] == ["allowed answer"]
    assert "private@example.com" not in context.verified_sql_examples[0]["sql"]
    assert "***MASKED***" in context.verified_sql_examples[0]["sql"]
