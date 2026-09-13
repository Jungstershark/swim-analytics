"""add RelayResult and RelayLeg tables

Revision ID: 5792b47f792c
Revises: b27916debd57
Create Date: 2026-03-29 16:08:25.088407

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5792b47f792c"
down_revision: Union[str, Sequence[str], None] = "b27916debd57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "RelayResult",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("meetId", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("teamName", sa.String(), nullable=False),
        sa.Column("relayLetter", sa.String(), nullable=True),
        sa.Column("time", sa.String(), nullable=True),
        sa.Column("seedTime", sa.String(), nullable=True),
        sa.Column("placement", sa.Integer(), nullable=True),
        sa.Column("isDQ", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dqCode", sa.String(), nullable=True),
        sa.Column("dqDescription", sa.String(), nullable=True),
        sa.Column("isExhibition", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("round", sa.String(), nullable=True),
        sa.Column("swimDate", sa.DateTime(timezone=True), nullable=True),
        sa.Column("splits", sa.String(), nullable=True),
        sa.Column("reactionTime", sa.String(), nullable=True),
        sa.Column("contentHash", sa.String(), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["meetId"], ["Meet.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("RelayResult_meetId_idx", "RelayResult", ["meetId"])
    op.create_index("RelayResult_event_idx", "RelayResult", ["event"])
    op.create_index("RelayResult_contentHash_idx", "RelayResult", ["contentHash"])

    op.create_table(
        "RelayLeg",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("relayResultId", sa.Integer(), nullable=False),
        sa.Column("legNumber", sa.Integer(), nullable=False),
        sa.Column("swimmerId", sa.Integer(), nullable=True),
        sa.Column("swimmerName", sa.String(), nullable=False),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("gender", sa.String(), nullable=True),
        sa.Column("isGuest", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reactionTime", sa.String(), nullable=True),
        sa.Column("splitTime", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["relayResultId"], ["RelayResult.id"]),
        sa.ForeignKeyConstraint(["swimmerId"], ["Swimmer.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("RelayLeg_relayResultId_idx", "RelayLeg", ["relayResultId"])
    op.create_index("RelayLeg_swimmerId_idx", "RelayLeg", ["swimmerId"])


def downgrade() -> None:
    op.drop_index("RelayLeg_swimmerId_idx", table_name="RelayLeg")
    op.drop_index("RelayLeg_relayResultId_idx", table_name="RelayLeg")
    op.drop_table("RelayLeg")
    op.drop_index("RelayResult_contentHash_idx", table_name="RelayResult")
    op.drop_index("RelayResult_event_idx", table_name="RelayResult")
    op.drop_index("RelayResult_meetId_idx", table_name="RelayResult")
    op.drop_table("RelayResult")
