"""add parserFormat to Meet

Revision ID: b27916debd57
Revises: ebaf43fb48a5
Create Date: 2026-03-29 15:11:35.092648

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b27916debd57"
down_revision: Union[str, Sequence[str], None] = "ebaf43fb48a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("Meet", sa.Column("parserFormat", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("Meet", "parserFormat")
