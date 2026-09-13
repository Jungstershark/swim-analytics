"""Add explicit result status to individual and relay performances.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = "'finished', 'dq', 'ns', 'dns', 'dnf', 'scratched', 'unknown'"


def upgrade() -> None:
    for table_name in ("Result", "RelayResult"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(sa.Column("resultStatus", sa.String(length=20), nullable=True))

        op.execute(
            sa.text(
                f'UPDATE "{table_name}" SET "resultStatus" = '
                'CASE WHEN "isDQ" IS TRUE THEN \'dq\' '
                'WHEN "time" IS NOT NULL THEN \'finished\' ELSE \'unknown\' END'
            )
        )

        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                "resultStatus",
                existing_type=sa.String(length=20),
                nullable=False,
            )
            batch_op.create_check_constraint(
                f"{table_name}_status_ck",
                f'"resultStatus" IN ({STATUSES})',
            )


def downgrade() -> None:
    for table_name in ("RelayResult", "Result"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(f"{table_name}_status_ck", type_="check")
            batch_op.drop_column("resultStatus")
