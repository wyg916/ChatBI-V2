"""Preserve SQL workspace history after datasource deletion.

Revision ID: 20260829_0015
Revises: 20260829_0014
"""

from alembic import op
import sqlalchemy as sa


revision = "20260829_0015"
down_revision = "20260829_0014"
branch_labels = None
depends_on = None


_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}
_STABLE_FK_NAME = "fk_sql_workspace_run_datasource_id_datasource"


def _datasource_fk_name(bind) -> str:
    for foreign_key in sa.inspect(bind).get_foreign_keys("sql_workspace_run"):
        if foreign_key.get("constrained_columns") == ["datasource_id"]:
            return foreign_key.get("name") or _STABLE_FK_NAME
    raise RuntimeError("sql_workspace_run datasource foreign key is missing")


def _replace_datasource_fk(*, nullable: bool, ondelete: str) -> None:
    bind = op.get_bind()
    existing_name = _datasource_fk_name(bind)
    with op.batch_alter_table(
        "sql_workspace_run",
        naming_convention=_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(existing_name, type_="foreignkey")
        batch_op.alter_column(
            "datasource_id",
            existing_type=sa.String(length=36),
            nullable=nullable,
        )
        batch_op.create_foreign_key(
            _STABLE_FK_NAME,
            "datasource",
            ["datasource_id"],
            ["id"],
            ondelete=ondelete,
        )


def upgrade() -> None:
    _replace_datasource_fk(nullable=True, ondelete="SET NULL")


def downgrade() -> None:
    bind = op.get_bind()
    has_detached_history = bind.execute(
        sa.text("SELECT 1 FROM sql_workspace_run WHERE datasource_id IS NULL LIMIT 1")
    ).first() is not None
    if has_detached_history:
        raise RuntimeError(
            "Cannot downgrade 20260829_0015 while detached SQL workspace history exists; "
            "restore the referenced datasource or retain migration 0015."
        )
    _replace_datasource_fk(nullable=False, ondelete="RESTRICT")
