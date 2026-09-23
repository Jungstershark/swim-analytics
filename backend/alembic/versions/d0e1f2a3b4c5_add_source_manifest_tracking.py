"""persist source manifests and conservative import snapshots

A source-event manifest is a stable SHA-256 of the discovered page metadata and
canonical document links. It supports cheap refresh comparisons without fetching
canonical document links. An edition records the manifest it imported only when a
source-bound import succeeds. Historical links remain deliberately baseline-free
because the page state at their past import time is unknown.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-09-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MANIFEST_SHA_CK = '"manifestSha256" IS NULL OR length("manifestSha256") = 64'
_CAPTURE_KIND_CK = (
    '"sourceManifestCaptureKind" IS NULL OR '
    '"sourceManifestCaptureKind" IN (\'imported\', \'monitoring_baseline\')'
)
_CAPTURE_PAIR_CK = (
    '("sourceManifestSha256" IS NULL AND "sourceManifestCaptureKind" IS NULL) OR '
    '("sourceManifestSha256" IS NOT NULL AND "sourceManifestCaptureKind" IS NOT NULL)'
)
_CAPTURE_TIME_CK = (
    '"sourceManifestCaptureKind" IS NULL OR "sourceManifestCapturedAt" IS NOT NULL'
)


def _assert_no_duplicate_source_event_links() -> None:
    duplicates = op.get_bind().execute(sa.text(
        'SELECT "sourceEventId" FROM "CompetitionEdition" '
        'WHERE "sourceEventId" IS NOT NULL '
        'GROUP BY "sourceEventId" HAVING COUNT(*) > 1'
    )).fetchall()
    if duplicates:
        event_ids = ", ".join(str(row[0]) for row in duplicates)
        raise RuntimeError(
            "Cannot enforce one source event per competition edition; "
            f"duplicate sourceEventId values: {event_ids}"
        )


def upgrade() -> None:
    with op.batch_alter_table("SourceEvent") as batch:
        batch.add_column(sa.Column("manifestSha256", sa.String(length=64), nullable=True))
        batch.create_check_constraint("SourceEvent_manifest_sha_ck", _MANIFEST_SHA_CK)

    with op.batch_alter_table("CompetitionEdition") as batch:
        batch.add_column(sa.Column("sourceManifestSha256", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("sourceManifestCaptureKind", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("sourceManifestCapturedAt", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint("CompetitionEdition_manifest_capture_kind_ck", _CAPTURE_KIND_CK)
        batch.create_check_constraint("CompetitionEdition_manifest_capture_pair_ck", _CAPTURE_PAIR_CK)
        batch.create_check_constraint("CompetitionEdition_manifest_capture_time_ck", _CAPTURE_TIME_CK)
        batch.create_check_constraint(
            "CompetitionEdition_manifest_sha_ck",
            '"sourceManifestSha256" IS NULL OR length("sourceManifestSha256") = 64',
        )

    _assert_no_duplicate_source_event_links()
    op.create_index(
        "CompetitionEdition_sourceEvent_uq",
        "CompetitionEdition",
        ["sourceEventId"],
        unique=True,
        sqlite_where=sa.text('"sourceEventId" IS NOT NULL'),
        postgresql_where=sa.text('"sourceEventId" IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index("CompetitionEdition_sourceEvent_uq", table_name="CompetitionEdition")
    with op.batch_alter_table("CompetitionEdition") as batch:
        batch.drop_constraint("CompetitionEdition_manifest_sha_ck", type_="check")
        batch.drop_constraint("CompetitionEdition_manifest_capture_time_ck", type_="check")
        batch.drop_constraint("CompetitionEdition_manifest_capture_pair_ck", type_="check")
        batch.drop_constraint("CompetitionEdition_manifest_capture_kind_ck", type_="check")
        batch.drop_column("sourceManifestCapturedAt")
        batch.drop_column("sourceManifestCaptureKind")
        batch.drop_column("sourceManifestSha256")
    with op.batch_alter_table("SourceEvent") as batch:
        batch.drop_constraint("SourceEvent_manifest_sha_ck", type_="check")
        batch.drop_column("manifestSha256")
