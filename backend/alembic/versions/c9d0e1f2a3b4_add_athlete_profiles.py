"""add reversible browser athlete profiles

Athlete profiles aggregate source-faithful Swimmer rows only when their exact
normalized name and canonical club agree. Source rows, Results, and RelayLegs
remain untouched; the nullable link is populated by an explicit operator
backfill after deployment and by runtime ingestion thereafter.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "AthleteProfile",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("nameKey", sa.String(), nullable=False),
        sa.Column("team", sa.String(), nullable=False),
        sa.Column("teamKey", sa.String(), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("nameKey", "teamKey", name="AthleteProfile_identity_uq"),
        sa.CheckConstraint('"nameKey" <> \'\' AND "nameKey" <> \'|\'', name="AthleteProfile_name_key_ck"),
        sa.CheckConstraint('"teamKey" <> \'\'', name="AthleteProfile_team_key_ck"),
    )
    op.create_index("AthleteProfile_name_idx", "AthleteProfile", ["name"])
    op.create_index("AthleteProfile_nameKey_idx", "AthleteProfile", ["nameKey"])
    op.create_index("AthleteProfile_team_idx", "AthleteProfile", ["team"])

    # Batch mode is required for SQLite bootstrap tests; PostgreSQL executes the
    # same logical alter without changing the production schema contract.
    with op.batch_alter_table("Swimmer") as batch:
        batch.add_column(sa.Column("athleteProfileId", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "Swimmer_athleteProfile_fkey",
            "AthleteProfile",
            ["athleteProfileId"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("Swimmer_athleteProfile_idx", ["athleteProfileId"])


def downgrade() -> None:
    with op.batch_alter_table("Swimmer") as batch:
        batch.drop_index("Swimmer_athleteProfile_idx")
        batch.drop_constraint("Swimmer_athleteProfile_fkey", type_="foreignkey")
        batch.drop_column("athleteProfileId")
    op.drop_index("AthleteProfile_team_idx", table_name="AthleteProfile")
    op.drop_index("AthleteProfile_nameKey_idx", table_name="AthleteProfile")
    op.drop_index("AthleteProfile_name_idx", table_name="AthleteProfile")
    op.drop_table("AthleteProfile")
