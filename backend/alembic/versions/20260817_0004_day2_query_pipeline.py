"""day2 query pipeline, audit, feedback, and verified answer evidence

Revision ID: 20260817_0004
Revises: 20260817_0003
Create Date: 2026-08-17 15:15:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260817_0004"
down_revision: Union[str, None] = "20260817_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "query_run",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("datasource_id", sa.String(length=36), nullable=False),
        sa.Column("semantic_model_id", sa.String(length=36), nullable=False),
        sa.Column("semantic_model_version", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("context_payload", sa.JSON(), nullable=False),
        sa.Column("plan_payload", sa.JSON(), nullable=False),
        sa.Column("guard_payload", sa.JSON(), nullable=False),
        sa.Column("execution_payload", sa.JSON(), nullable=False),
        sa.Column("oracle_payload", sa.JSON(), nullable=False),
        sa.Column("generated_sql", sa.Text(), nullable=True),
        sa.Column("normalized_sql", sa.Text(), nullable=True),
        sa.Column("result_signature", sa.String(length=64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["datasource_id"], ["datasource.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["semantic_model_id"], ["semantic_model.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("workspace_id", "datasource_id", "semantic_model_id", "status", "result_signature"):
        op.create_index(op.f(f"ix_query_run_{column}"), "query_run", [column], unique=False)

    op.create_table(
        "query_audit_event",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("query_run_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["query_run_id"], ["query_run.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("query_run_id", "event_type", "created_at"):
        op.create_index(op.f(f"ix_query_audit_event_{column}"), "query_audit_event", [column], unique=False)

    op.create_table(
        "query_feedback",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("query_run_id", sa.String(length=36), nullable=False),
        sa.Column("feedback_type", sa.String(length=32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["query_run_id"], ["query_run.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("query_run_id", "feedback_type"),
    )
    op.create_index(op.f("ix_query_feedback_query_run_id"), "query_feedback", ["query_run_id"], unique=False)

    op.add_column("verified_answer", sa.Column("query_run_id", sa.String(length=36), nullable=True))
    op.add_column("verified_answer", sa.Column("sql_text", sa.Text(), nullable=True))
    op.add_column("verified_answer", sa.Column("result_signature", sa.String(length=64), nullable=True))
    op.add_column("verified_answer", sa.Column("semantic_model_version", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_verified_answer_query_run_id"), "verified_answer", ["query_run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_verified_answer_query_run_id"), table_name="verified_answer")
    op.drop_column("verified_answer", "semantic_model_version")
    op.drop_column("verified_answer", "result_signature")
    op.drop_column("verified_answer", "sql_text")
    op.drop_column("verified_answer", "query_run_id")
    op.drop_index(op.f("ix_query_feedback_query_run_id"), table_name="query_feedback")
    op.drop_table("query_feedback")
    for column in ("created_at", "event_type", "query_run_id"):
        op.drop_index(op.f(f"ix_query_audit_event_{column}"), table_name="query_audit_event")
    op.drop_table("query_audit_event")
    for column in ("result_signature", "status", "semantic_model_id", "datasource_id", "workspace_id"):
        op.drop_index(op.f(f"ix_query_run_{column}"), table_name="query_run")
    op.drop_table("query_run")
