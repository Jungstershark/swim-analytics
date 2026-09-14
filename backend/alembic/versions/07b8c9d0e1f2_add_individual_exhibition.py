"""Add exhibition provenance to individual results.

Revision ID: 07b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "07b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("Result") as batch_op:
        batch_op.add_column(
            sa.Column(
                "isExhibition",
                sa.Boolean(),
                nullable=True,
                server_default=sa.false(),
            )
        )

    op.execute(
        sa.text('UPDATE "Result" SET "isExhibition" = false WHERE "isExhibition" IS NULL')
    )

    with op.batch_alter_table("Result") as batch_op:
        batch_op.alter_column(
            "isExhibition",
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        )


def downgrade() -> None:
    with op.batch_alter_table("Result") as batch_op:
        batch_op.drop_column("isExhibition")
