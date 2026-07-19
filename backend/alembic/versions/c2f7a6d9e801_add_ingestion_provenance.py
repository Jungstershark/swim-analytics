"""add ingestion provenance

Revision ID: c2f7a6d9e801
Revises: b0aed82fb3bd
Create Date: 2026-07-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2f7a6d9e801'
down_revision: Union[str, Sequence[str], None] = 'b0aed82fb3bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'RawDocument',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('sha256', sa.String(), nullable=False),
        sa.Column('byteSize', sa.Integer(), nullable=False),
        sa.Column('contentType', sa.String(), nullable=True),
        sa.Column('storagePath', sa.String(), nullable=False),
        sa.Column('originalFilename', sa.String(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('isValidPdf', sa.Boolean(), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sha256'),
    )
    op.create_index('RawDocument_sha256_idx', 'RawDocument', ['sha256'])
    op.create_index('RawDocument_category_idx', 'RawDocument', ['category'])

    op.create_table(
        'SourceReference',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('rawDocumentId', sa.Integer(), nullable=False),
        sa.Column('sourceType', sa.String(), nullable=False),
        sa.Column('sourceLabel', sa.String(), nullable=True),
        sa.Column('sourceUrl', sa.String(), nullable=True),
        sa.Column('sourcePageUrl', sa.String(), nullable=True),
        sa.Column('filenameSeen', sa.String(), nullable=True),
        sa.Column('sourceIdentity', sa.String(), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['rawDocumentId'], ['RawDocument.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('rawDocumentId', 'sourceIdentity', name='SourceReference_identity_uq'),
    )
    op.create_index('SourceReference_rawDocumentId_idx', 'SourceReference', ['rawDocumentId'])
    op.create_index('SourceReference_sourceType_idx', 'SourceReference', ['sourceType'])

    op.create_table(
        'DocumentClassification',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('rawDocumentId', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('confidence', sa.Integer(), nullable=False),
        sa.Column('classifierVersion', sa.String(), nullable=False),
        sa.Column('reason', sa.String(), nullable=True),
        sa.Column('isCurrent', sa.Boolean(), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['rawDocumentId'], ['RawDocument.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('DocumentClassification_rawDocumentId_idx', 'DocumentClassification', ['rawDocumentId'])
    op.create_index('DocumentClassification_category_idx', 'DocumentClassification', ['category'])

    op.create_table(
        'IngestionRun',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('mode', sa.String(), nullable=False),
        sa.Column('inputScope', sa.String(), nullable=True),
        sa.Column('parserVersion', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('recordsInserted', sa.Integer(), nullable=False),
        sa.Column('recordsUpdated', sa.Integer(), nullable=False),
        sa.Column('duplicatesSkipped', sa.Integer(), nullable=False),
        sa.Column('validationErrors', sa.String(), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('IngestionRun_mode_idx', 'IngestionRun', ['mode'])
    op.create_index('IngestionRun_status_idx', 'IngestionRun', ['status'])

    op.create_table(
        'ParseJob',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('rawDocumentId', sa.Integer(), nullable=False),
        sa.Column('parserName', sa.String(), nullable=False),
        sa.Column('parserVersion', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('confidenceScore', sa.Integer(), nullable=True),
        sa.Column('confidencePassed', sa.Boolean(), nullable=False),
        sa.Column('eventsCount', sa.Integer(), nullable=False),
        sa.Column('individualResultsCount', sa.Integer(), nullable=False),
        sa.Column('relayResultsCount', sa.Integer(), nullable=False),
        sa.Column('unmatchedLinesCount', sa.Integer(), nullable=False),
        sa.Column('errorMessage', sa.String(), nullable=True),
        sa.Column('parsedArtifactPath', sa.String(), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['rawDocumentId'], ['RawDocument.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ParseJob_rawDocumentId_idx', 'ParseJob', ['rawDocumentId'])
    op.create_index('ParseJob_parser_idx', 'ParseJob', ['parserName', 'parserVersion'])
    op.create_index('ParseJob_status_idx', 'ParseJob', ['status'])

    for table_name in ('Result', 'RelayResult'):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(sa.Column('sourceDocumentSha256', sa.String(), nullable=True))
            batch_op.add_column(sa.Column('parseJobId', sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column('ingestionRunId', sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column('parserVersion', sa.String(), nullable=True))
            batch_op.add_column(sa.Column('sourceEventNumber', sa.String(), nullable=True))
            batch_op.create_foreign_key(f'{table_name}_parseJobId_fkey', 'ParseJob', ['parseJobId'], ['id'])
            batch_op.create_foreign_key(f'{table_name}_ingestionRunId_fkey', 'IngestionRun', ['ingestionRunId'], ['id'])


def downgrade() -> None:
    for table_name in ('RelayResult', 'Result'):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(f'{table_name}_ingestionRunId_fkey', type_='foreignkey')
            batch_op.drop_constraint(f'{table_name}_parseJobId_fkey', type_='foreignkey')
            batch_op.drop_column('sourceEventNumber')
            batch_op.drop_column('parserVersion')
            batch_op.drop_column('ingestionRunId')
            batch_op.drop_column('parseJobId')
            batch_op.drop_column('sourceDocumentSha256')

    op.drop_index('ParseJob_status_idx', table_name='ParseJob')
    op.drop_index('ParseJob_parser_idx', table_name='ParseJob')
    op.drop_index('ParseJob_rawDocumentId_idx', table_name='ParseJob')
    op.drop_table('ParseJob')

    op.drop_index('IngestionRun_status_idx', table_name='IngestionRun')
    op.drop_index('IngestionRun_mode_idx', table_name='IngestionRun')
    op.drop_table('IngestionRun')

    op.drop_index('DocumentClassification_category_idx', table_name='DocumentClassification')
    op.drop_index('DocumentClassification_rawDocumentId_idx', table_name='DocumentClassification')
    op.drop_table('DocumentClassification')

    op.drop_index('SourceReference_sourceType_idx', table_name='SourceReference')
    op.drop_index('SourceReference_rawDocumentId_idx', table_name='SourceReference')
    op.drop_table('SourceReference')

    op.drop_index('RawDocument_category_idx', table_name='RawDocument')
    op.drop_index('RawDocument_sha256_idx', table_name='RawDocument')
    op.drop_table('RawDocument')
