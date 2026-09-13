"""baseline: existing schema

Revision ID: ebaf43fb48a5
Revises:
Create Date: 2026-03-29 13:52:02.101979

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ebaf43fb48a5"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "Swimmer",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("team", sa.String(), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("Swimmer_name_idx", "Swimmer", ["name"])
    op.create_index("Swimmer_team_idx", "Swimmer", ["team"])

    op.create_table(
        "Meet",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("endDate", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("Meet_date_idx", "Meet", ["date"])

    op.create_table(
        "Result",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("swimmerId", sa.Integer(), nullable=False),
        sa.Column("meetId", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("time", sa.String(), nullable=True),
        sa.Column("seedTime", sa.String(), nullable=True),
        sa.Column("placement", sa.Integer(), nullable=True),
        sa.Column("isDQ", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dqCode", sa.String(), nullable=True),
        sa.Column("dqDescription", sa.String(), nullable=True),
        sa.Column("isGuest", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("qualifier", sa.String(), nullable=True),
        sa.Column("reactionTime", sa.String(), nullable=True),
        sa.Column("splits", sa.String(), nullable=True),
        sa.Column("round", sa.String(), nullable=True),
        sa.Column("swimDate", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contentHash", sa.String(), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["meetId"], ["Meet.id"]),
        sa.ForeignKeyConstraint(["swimmerId"], ["Swimmer.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("Result_swimmerId_idx", "Result", ["swimmerId"])
    op.create_index("Result_meetId_idx", "Result", ["meetId"])
    op.create_index("Result_event_idx", "Result", ["event"])
    op.create_index("Result_contentHash_idx", "Result", ["contentHash"])
    op.create_index(
        "Result_dedup_idx",
        "Result",
        ["swimmerId", "meetId", "event", "round", "swimDate"],
    )


def downgrade() -> None:
    op.drop_index("Result_dedup_idx", table_name="Result")
    op.drop_index("Result_contentHash_idx", table_name="Result")
    op.drop_index("Result_event_idx", table_name="Result")
    op.drop_index("Result_meetId_idx", table_name="Result")
    op.drop_index("Result_swimmerId_idx", table_name="Result")
    op.drop_table("Result")
    op.drop_index("Meet_date_idx", table_name="Meet")
    op.drop_table("Meet")
    op.drop_index("Swimmer_team_idx", table_name="Swimmer")
    op.drop_index("Swimmer_name_idx", table_name="Swimmer")
    op.drop_table("Swimmer")
