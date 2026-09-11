"""add entity resolution registry and swimmer nameKey

Revision ID: a7c1d4e2f9b3
Revises: d4b63ef2a9c0
Create Date: 2026-09-09 00:00:00.000000

Adds:
* ``Swimmer.nameKey`` — normalized identity key used to merge the same swimmer
  whose name is spelled with inconsistent casing/whitespace.
* ``TeamCanon`` / ``TeamAlias`` — canonical team registry mapping every raw
  source spelling to one master name.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c1d4e2f9b3'
down_revision: Union[str, Sequence[str], None] = 'd4b63ef2a9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('Swimmer', sa.Column('nameKey', sa.String(), nullable=True))
    op.add_column('Swimmer', sa.Column('teamKey', sa.String(), nullable=True))
    op.add_column('Result', sa.Column('rawSwimmerName', sa.String(), nullable=True))
    op.add_column('Result', sa.Column('rawTeamName', sa.String(), nullable=True))
    op.add_column('RelayResult', sa.Column('rawTeamName', sa.String(), nullable=True))
    op.create_index('Swimmer_nameKey_idx', 'Swimmer', ['nameKey'])
    # Keys are nullable only so this additive migration can precede the controlled
    # backfill. Once populated, this is the database concurrency guard.
    op.create_index(
        'Swimmer_identity_uq',
        'Swimmer',
        ['nameKey', 'teamKey', 'age'],
        unique=True,
        postgresql_where=sa.text('"teamKey" <> \'\' AND age IS NOT NULL'),
    )

    op.create_table(
        'TeamCanon',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('canonicalName', sa.String(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    op.create_index('TeamCanon_key_idx', 'TeamCanon', ['key'])

    op.create_table(
        'TeamAlias',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('teamCanonId', sa.Integer(), nullable=False),
        sa.Column('rawName', sa.String(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('firstSeenAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lastSeenAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['teamCanonId'], ['TeamCanon.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('rawName', name='TeamAlias_rawName_uq'),
    )
    op.create_index('TeamAlias_key_idx', 'TeamAlias', ['key'])


def downgrade() -> None:
    op.drop_index('TeamAlias_key_idx', table_name='TeamAlias')
    op.drop_table('TeamAlias')

    op.drop_index('TeamCanon_key_idx', table_name='TeamCanon')
    op.drop_table('TeamCanon')

    op.drop_index('Swimmer_identity_uq', table_name='Swimmer')
    op.drop_index('Swimmer_nameKey_idx', table_name='Swimmer')
    op.drop_column('RelayResult', 'rawTeamName')
    op.drop_column('Result', 'rawTeamName')
    op.drop_column('Result', 'rawSwimmerName')
    op.drop_column('Swimmer', 'teamKey')
    op.drop_column('Swimmer', 'nameKey')
