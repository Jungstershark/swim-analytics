"""add competition hierarchy and performance session links

Revision ID: e5f6a7b8c9d0
Revises: a7c1d4e2f9b3
Create Date: 2026-09-12 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "a7c1d4e2f9b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RESOLUTION_VALUES = "'unknown', 'derived', 'verified', 'conflicting'"


def upgrade() -> None:
    op.create_table(
        "CompetitionEdition",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sourceKey", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("sourceEventId", sa.Integer(), nullable=True),
        sa.Column("startDate", sa.Date(), nullable=True),
        sa.Column("endDate", sa.Date(), nullable=True),
        sa.Column("resolutionStatus", sa.String(), nullable=False),
        sa.Column("resolverVersion", sa.String(), nullable=False),
        sa.Column("resolvedAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            '"endDate" IS NULL OR "startDate" IS NULL OR "endDate" >= "startDate"',
            name="CompetitionEdition_date_range_ck",
        ),
        sa.CheckConstraint(
            f'"resolutionStatus" IN ({_RESOLUTION_VALUES})',
            name="CompetitionEdition_resolution_status_ck",
        ),
        sa.ForeignKeyConstraint(["sourceEventId"], ["SourceEvent.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sourceKey"),
    )
    op.create_index("CompetitionEdition_sourceKey_idx", "CompetitionEdition", ["sourceKey"])
    op.create_index("CompetitionEdition_dates_idx", "CompetitionEdition", ["startDate", "endDate"])

    op.create_table(
        "CompetitionSegment",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("competitionEditionId", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("legacyMeetId", sa.Integer(), nullable=True),
        sa.Column("startDate", sa.Date(), nullable=True),
        sa.Column("endDate", sa.Date(), nullable=True),
        sa.Column("resolutionStatus", sa.String(), nullable=False),
        sa.Column("resolverVersion", sa.String(), nullable=False),
        sa.Column("resolvedAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            '"endDate" IS NULL OR "startDate" IS NULL OR "endDate" >= "startDate"',
            name="CompetitionSegment_date_range_ck",
        ),
        sa.CheckConstraint(
            f'"resolutionStatus" IN ({_RESOLUTION_VALUES})',
            name="CompetitionSegment_resolution_status_ck",
        ),
        sa.ForeignKeyConstraint(["competitionEditionId"], ["CompetitionEdition.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["legacyMeetId"], ["Meet.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("competitionEditionId", "key", name="CompetitionSegment_edition_key_uq"),
        sa.UniqueConstraint("legacyMeetId"),
    )
    op.create_index("CompetitionSegment_competition_idx", "CompetitionSegment", ["competitionEditionId"])

    op.create_table(
        "CompetitionDay",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("competitionSegmentId", sa.Integer(), nullable=False),
        sa.Column("dayNumber", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("resolutionStatus", sa.String(), nullable=False),
        sa.Column("resolverVersion", sa.String(), nullable=False),
        sa.Column("resolvedAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('"dayNumber" > 0', name="CompetitionDay_number_ck"),
        sa.CheckConstraint(
            f'"resolutionStatus" IN ({_RESOLUTION_VALUES})',
            name="CompetitionDay_resolution_status_ck",
        ),
        sa.ForeignKeyConstraint(["competitionSegmentId"], ["CompetitionSegment.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("competitionSegmentId", "dayNumber", name="CompetitionDay_segment_day_uq"),
    )
    op.create_index("CompetitionDay_segment_date_idx", "CompetitionDay", ["competitionSegmentId", "date"])

    op.create_table(
        "CompetitionSession",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("competitionDayId", sa.Integer(), nullable=False),
        sa.Column("sessionNumber", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("resolutionStatus", sa.String(), nullable=False),
        sa.Column("resolverVersion", sa.String(), nullable=False),
        sa.Column("resolvedAt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('"sessionNumber" > 0', name="CompetitionSession_number_ck"),
        sa.CheckConstraint(
            f'"resolutionStatus" IN ({_RESOLUTION_VALUES})',
            name="CompetitionSession_resolution_status_ck",
        ),
        sa.ForeignKeyConstraint(["competitionDayId"], ["CompetitionDay.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("competitionDayId", "sessionNumber", name="CompetitionSession_day_session_uq"),
    )
    op.create_index("CompetitionSession_day_idx", "CompetitionSession", ["competitionDayId"])

    for table_name in ("Result", "RelayResult"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(sa.Column("sessionId", sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                f"{table_name}_sessionId_fkey",
                "CompetitionSession",
                ["sessionId"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch_op.create_index(f"{table_name}_sessionId_idx", ["sessionId"])

    with op.batch_alter_table("RelayResult") as batch_op:
        batch_op.add_column(sa.Column("legParseStatus", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("legParseWarning", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "RelayResult_leg_parse_status_ck",
            '"legParseStatus" IS NULL OR "legParseStatus" IN (\'complete\', \'partial\', \'unavailable\')',
        )

    op.drop_index("Result_contentHash_idx", table_name="Result")
    op.drop_index("RelayResult_contentHash_idx", table_name="RelayResult")
    op.create_index("Result_contentHash_uq", "Result", ["contentHash"], unique=True)
    op.create_index("RelayResult_contentHash_uq", "RelayResult", ["contentHash"], unique=True)


def downgrade() -> None:
    op.drop_index("RelayResult_contentHash_uq", table_name="RelayResult")
    op.drop_index("Result_contentHash_uq", table_name="Result")
    op.create_index("RelayResult_contentHash_idx", "RelayResult", ["contentHash"])
    op.create_index("Result_contentHash_idx", "Result", ["contentHash"])

    with op.batch_alter_table("RelayResult") as batch_op:
        batch_op.drop_constraint("RelayResult_leg_parse_status_ck", type_="check")
        batch_op.drop_column("legParseWarning")
        batch_op.drop_column("legParseStatus")

    for table_name in ("RelayResult", "Result"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_index(f"{table_name}_sessionId_idx")
            batch_op.drop_constraint(f"{table_name}_sessionId_fkey", type_="foreignkey")
            batch_op.drop_column("sessionId")

    op.drop_index("CompetitionSession_day_idx", table_name="CompetitionSession")
    op.drop_table("CompetitionSession")
    op.drop_index("CompetitionDay_segment_date_idx", table_name="CompetitionDay")
    op.drop_table("CompetitionDay")
    op.drop_index("CompetitionSegment_competition_idx", table_name="CompetitionSegment")
    op.drop_table("CompetitionSegment")
    op.drop_index("CompetitionEdition_dates_idx", table_name="CompetitionEdition")
    op.drop_index("CompetitionEdition_sourceKey_idx", table_name="CompetitionEdition")
    op.drop_table("CompetitionEdition")
