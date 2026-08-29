"""Managed Excel/CSV datasource provenance.

Revision ID: 20260829_0014
Revises: 20260828_0013
"""

from alembic import op
import sqlalchemy as sa


revision = "20260829_0014"
down_revision = "20260828_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "datasource_import",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "datasource_id",
            sa.String(36),
            sa.ForeignKey("datasource.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_schema", sa.String(255), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("column_count", sa.Integer(), nullable=False),
        sa.Column("sheet_metadata", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="READY"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("datasource_id", name="uq_datasource_import_datasource_id"),
    )
    op.create_index("ix_datasource_import_sha256", "datasource_import", ["file_sha256"])
    op.create_index("ix_datasource_import_status", "datasource_import", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    has_managed_imports = bind.execute(
        sa.text("SELECT 1 FROM datasource_import LIMIT 1")
    ).first() is not None
    has_excel_datasources = bind.execute(
        sa.text("SELECT 1 FROM datasource WHERE type = 'excel' LIMIT 1")
    ).first() is not None
    if has_managed_imports or has_excel_datasources:
        raise RuntimeError(
            "Cannot downgrade 20260829_0014 while managed spreadsheet datasources exist; "
            "delete them through the Backend API first so owned schemas are removed safely."
        )
    op.drop_table("datasource_import")
