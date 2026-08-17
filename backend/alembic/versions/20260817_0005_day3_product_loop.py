"""day3 chart narrative answer dashboard and evaluation loop

Revision ID: 20260817_0005
Revises: 20260817_0004
Create Date: 2026-08-17 17:05:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260817_0005"
down_revision: Union[str, None] = "20260817_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for name in ("chart_spec_payload", "narrative_payload"):
        op.add_column("query_run", sa.Column(name, sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.add_column("query_run", sa.Column("follow_up_payload", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))

    answer_columns = [
        sa.Column("semantic_intent", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("sql_plan", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("result_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("chart_spec", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("narrative", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("semantic_model_id", sa.String(length=36), nullable=True),
        sa.Column("datasource_id", sa.String(length=36), nullable=True),
        sa.Column("oracle_status", sa.String(length=32), nullable=True),
        sa.Column("feedback", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    ]
    with op.batch_alter_table("verified_answer") as batch_op:
        for column in answer_columns:
            batch_op.add_column(column)
        batch_op.create_foreign_key("fk_verified_answer_semantic_model_id", "semantic_model", ["semantic_model_id"], ["id"], ondelete="RESTRICT")
        batch_op.create_foreign_key("fk_verified_answer_datasource_id", "datasource", ["datasource_id"], ["id"], ondelete="RESTRICT")
    for name in ("semantic_model_id", "datasource_id", "oracle_status"):
        op.create_index(op.f(f"ix_verified_answer_{name}"), "verified_answer", [name], unique=False)
    op.execute("UPDATE verified_answer SET status = 'DEPRECATED' WHERE status = 'PUBLISHED'")
    op.execute("UPDATE verified_answer SET status = 'DRAFT' WHERE status = 'REVIEW'")
    op.execute("UPDATE verified_answer SET status = 'DEPRECATED' WHERE status = 'ARCHIVED'")

    op.create_table(
        "answer_version",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("answer_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["answer_id"], ["verified_answer.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("answer_id", "version"),
    )
    op.create_index(op.f("ix_answer_version_answer_id"), "answer_version", ["answer_id"], unique=False)

    op.create_table(
        "dashboard_card",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dashboard_id", sa.String(length=36), nullable=False),
        sa.Column("answer_id", sa.String(length=36), nullable=False),
        sa.Column("query_run_id", sa.String(length=36), nullable=False),
        sa.Column("chart_spec", sa.JSON(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("position", sa.JSON(), nullable=False),
        sa.Column("size", sa.JSON(), nullable=False),
        sa.Column("filter_context", sa.JSON(), nullable=False),
        sa.Column("semantic_model_version", sa.Integer(), nullable=False),
        sa.Column("result_signature", sa.String(length=64), nullable=True),
        sa.Column("refresh_policy", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dashboard_id"], ["dashboard.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["answer_id"], ["verified_answer.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["query_run_id"], ["query_run.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name in ("dashboard_id", "answer_id", "query_run_id", "result_signature"):
        op.create_index(op.f(f"ix_dashboard_card_{name}"), "dashboard_card", [name], unique=False)

    evaluation_columns = [
        sa.Column("manifest_sha256", sa.String(length=64), nullable=True),
        sa.Column("sql_execution_pass_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_value_pass_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("semantic_pass_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dangerous_sql_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dangerous_sql_block_count", sa.Integer(), nullable=False, server_default="0"),
    ]
    for column in evaluation_columns:
        op.add_column("evaluation_run", column)
    op.create_index(op.f("ix_evaluation_run_manifest_sha256"), "evaluation_run", ["manifest_sha256"], unique=False)
    op.execute("DELETE FROM evaluation_run WHERE golden_set_count = 296")

    op.create_table(
        "evaluation_case_result",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("evaluation_run_id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("execution_ok", sa.Boolean(), nullable=False),
        sa.Column("result_ok", sa.Boolean(), nullable=False),
        sa.Column("semantic_ok", sa.Boolean(), nullable=False),
        sa.Column("expected", sa.JSON(), nullable=False),
        sa.Column("actual", sa.JSON(), nullable=False),
        sa.Column("generated_sql", sa.Text(), nullable=True),
        sa.Column("result_diff", sa.JSON(), nullable=False),
        sa.Column("error_category", sa.String(length=64), nullable=True),
        sa.Column("query_run_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["evaluation_run_id"], ["evaluation_run.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["query_run_id"], ["query_run.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evaluation_run_id", "case_id"),
    )
    for name in ("evaluation_run_id", "case_id", "category", "status", "error_category", "query_run_id"):
        op.create_index(op.f(f"ix_evaluation_case_result_{name}"), "evaluation_case_result", [name], unique=False)


def downgrade() -> None:
    for name in ("query_run_id", "error_category", "status", "category", "case_id", "evaluation_run_id"):
        op.drop_index(op.f(f"ix_evaluation_case_result_{name}"), table_name="evaluation_case_result")
    op.drop_table("evaluation_case_result")
    op.drop_index(op.f("ix_evaluation_run_manifest_sha256"), table_name="evaluation_run")
    for name in ("dangerous_sql_block_count", "dangerous_sql_total", "semantic_pass_count", "result_value_pass_count", "sql_execution_pass_count", "manifest_sha256"):
        op.drop_column("evaluation_run", name)
    for name in ("result_signature", "query_run_id", "answer_id", "dashboard_id"):
        op.drop_index(op.f(f"ix_dashboard_card_{name}"), table_name="dashboard_card")
    op.drop_table("dashboard_card")
    op.drop_index(op.f("ix_answer_version_answer_id"), table_name="answer_version")
    op.drop_table("answer_version")
    for name in ("oracle_status", "datasource_id", "semantic_model_id"):
        op.drop_index(op.f(f"ix_verified_answer_{name}"), table_name="verified_answer")
    with op.batch_alter_table("verified_answer") as batch_op:
        batch_op.drop_constraint("fk_verified_answer_datasource_id", type_="foreignkey")
        batch_op.drop_constraint("fk_verified_answer_semantic_model_id", type_="foreignkey")
        for name in ("feedback", "oracle_status", "datasource_id", "semantic_model_id", "narrative", "chart_spec", "result_snapshot", "sql_plan", "semantic_intent"):
            batch_op.drop_column(name)
    for name in ("follow_up_payload", "narrative_payload", "chart_spec_payload"):
        op.drop_column("query_run", name)
