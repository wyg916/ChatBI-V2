"""close the V1 RAG and bounded multi-agent runtime contracts

Revision ID: 20260817_0008
Revises: 20260817_0007
Create Date: 2026-08-17 23:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260817_0008"
down_revision: Union[str, None] = "20260817_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orchestration_profile", sa.Column("max_tool_calls", sa.Integer(), nullable=False, server_default="12"))
    op.add_column("orchestration_profile", sa.Column("max_replan", sa.Integer(), nullable=False, server_default="2"))
    op.add_column("orchestration_profile", sa.Column("max_agent_depth", sa.Integer(), nullable=False, server_default="2"))
    op.add_column("orchestration_run", sa.Column("ttft_ms", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("orchestration_run", sa.Column("total_latency_ms", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("orchestration_run", sa.Column("tool_latency_ms", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("orchestration_run", sa.Column("trace_complete", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.add_column("prompt_version", sa.Column("source", sa.String(length=96), nullable=False, server_default="CHATBI_V1_REIMPLEMENTED"))
    op.add_column("prompt_version", sa.Column("checksum_sha256", sa.String(length=64), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("prompt_version", "checksum_sha256")
    op.drop_column("prompt_version", "source")
    op.drop_column("orchestration_run", "trace_complete")
    op.drop_column("orchestration_run", "tool_latency_ms")
    op.drop_column("orchestration_run", "total_latency_ms")
    op.drop_column("orchestration_run", "ttft_ms")
    op.drop_column("orchestration_profile", "max_agent_depth")
    op.drop_column("orchestration_profile", "max_replan")
    op.drop_column("orchestration_profile", "max_tool_calls")
