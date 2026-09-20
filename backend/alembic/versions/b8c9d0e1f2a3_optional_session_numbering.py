"""optional session numbering and source-document identity

Day N / Session N are optional metadata: a sheet that prints no such header must
still be importable, and its session must be recoverable on rebuild. This
migration makes the printed numbers nullable, forbids the zero/negative values
the previous check allowed to slip through the NULL gap, and adds a persisted
source-document key that identifies an unnumbered session.

Revision ID: b8c9d0e1f2a3
Revises: 07b8c9d0e1f2
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "07b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DAY_NUMBER_CK = '"dayNumber" IS NULL OR "dayNumber" > 0'
_SESSION_NUMBER_CK = '"sessionNumber" IS NULL OR "sessionNumber" > 0'


def upgrade() -> None:
    with op.batch_alter_table("CompetitionSession") as batch:
        batch.add_column(
            sa.Column("sourceDocumentSha", sa.String(length=64), nullable=True)
        )
        batch.add_column(
            sa.Column("sourceEvidenceKey", sa.String(length=64), nullable=True)
        )
        batch.add_column(sa.Column("sourceDocuments", sa.Text(), nullable=True))

    with op.batch_alter_table("CompetitionDay") as batch:
        batch.alter_column("dayNumber", existing_type=sa.Integer(), nullable=True)
        batch.drop_constraint("CompetitionDay_segment_day_uq", type_="unique")
        batch.drop_constraint("CompetitionDay_number_ck", type_="check")
        batch.create_check_constraint("CompetitionDay_number_ck", _DAY_NUMBER_CK)
    op.create_index(
        "CompetitionDay_segment_day_uq",
        "CompetitionDay",
        ["competitionSegmentId", "dayNumber"],
        unique=True,
        sqlite_where=sa.text('"dayNumber" IS NOT NULL'),
        postgresql_where=sa.text('"dayNumber" IS NOT NULL'),
    )
    # At most one unnumbered ("unassigned") day row per segment.
    op.create_index(
        "CompetitionDay_segment_unassigned_uq",
        "CompetitionDay",
        ["competitionSegmentId"],
        unique=True,
        sqlite_where=sa.text('"dayNumber" IS NULL'),
        postgresql_where=sa.text('"dayNumber" IS NULL'),
    )

    with op.batch_alter_table("CompetitionSession") as batch:
        batch.alter_column("sessionNumber", existing_type=sa.Integer(), nullable=True)
        batch.drop_constraint("CompetitionSession_day_session_uq", type_="unique")
        batch.drop_constraint("CompetitionSession_number_ck", type_="check")
        batch.create_check_constraint("CompetitionSession_number_ck", _SESSION_NUMBER_CK)
    op.create_index(
        "CompetitionSession_day_session_uq",
        "CompetitionSession",
        ["competitionDayId", "sessionNumber"],
        unique=True,
        sqlite_where=sa.text('"sessionNumber" IS NOT NULL'),
        postgresql_where=sa.text('"sessionNumber" IS NOT NULL'),
    )
    # One session per source document: this is what makes a rebuild map the same
    # sheet back to the same session without inventing a session number.
    op.create_index(
        "CompetitionSession_source_document_uq",
        "CompetitionSession",
        ["sourceDocumentSha"],
        unique=True,
        sqlite_where=sa.text('"sourceDocumentSha" IS NOT NULL'),
        postgresql_where=sa.text('"sourceDocumentSha" IS NOT NULL'),
    )


def _backfill_numbers(
    connection: "Connection",
    table: str,
    parent_column: str,
    number_column: str,
) -> None:
    """Give unnumbered rows distinct provisional numbers.

    Done row by row rather than with one correlated UPDATE: a single statement
    would hand the same ``MAX + 1`` to every NULL row in a parent and then trip
    the still-present partial unique index (PostgreSQL evaluates the whole
    statement against one snapshot).
    """
    rows = connection.execute(
        sa.text(
            f'SELECT id, "{parent_column}" FROM "{table}" '
            f'WHERE "{number_column}" IS NULL ORDER BY id'
        )
    ).fetchall()
    for row_id, parent_id in rows:
        highest = connection.execute(
            sa.text(
                f'SELECT MAX("{number_column}") FROM "{table}" '
                f'WHERE "{parent_column}" = :parent'
            ),
            {"parent": parent_id},
        ).scalar()
        connection.execute(
            sa.text(
                f'UPDATE "{table}" SET "{number_column}" = :number WHERE id = :row_id'
            ),
            {"number": (highest or 0) + 1, "row_id": row_id},
        )


def downgrade() -> None:
    # Unnumbered rows get provisional numbers so the previous NOT NULL
    # constraints can be restored. The numbers are positional, so this is a
    # repair path rather than a faithful inverse.
    connection = op.get_bind()
    _backfill_numbers(connection, "CompetitionDay", "competitionSegmentId", "dayNumber")
    _backfill_numbers(connection, "CompetitionSession", "competitionDayId", "sessionNumber")

    op.drop_index("CompetitionSession_source_document_uq", table_name="CompetitionSession")
    op.drop_index("CompetitionSession_day_session_uq", table_name="CompetitionSession")
    with op.batch_alter_table("CompetitionSession") as batch:
        batch.alter_column("sessionNumber", existing_type=sa.Integer(), nullable=False)
        batch.drop_constraint("CompetitionSession_number_ck", type_="check")
        batch.create_check_constraint("CompetitionSession_number_ck", '"sessionNumber" > 0')
        batch.create_unique_constraint(
            "CompetitionSession_day_session_uq", ["competitionDayId", "sessionNumber"]
        )
        batch.drop_column("sourceEvidenceKey")
        batch.drop_column("sourceDocuments")
        batch.drop_column("sourceDocumentSha")

    op.drop_index("CompetitionDay_segment_unassigned_uq", table_name="CompetitionDay")
    op.drop_index("CompetitionDay_segment_day_uq", table_name="CompetitionDay")
    with op.batch_alter_table("CompetitionDay") as batch:
        batch.alter_column("dayNumber", existing_type=sa.Integer(), nullable=False)
        batch.drop_constraint("CompetitionDay_number_ck", type_="check")
        batch.create_check_constraint("CompetitionDay_number_ck", '"dayNumber" > 0')
        batch.create_unique_constraint(
            "CompetitionDay_segment_day_uq", ["competitionSegmentId", "dayNumber"]
        )
