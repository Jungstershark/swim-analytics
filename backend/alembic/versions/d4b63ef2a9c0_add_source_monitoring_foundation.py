"""add source monitoring foundation

Revision ID: d4b63ef2a9c0
Revises: c2f7a6d9e801
Create Date: 2026-07-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4b63ef2a9c0'
down_revision: Union[str, Sequence[str], None] = 'c2f7a6d9e801'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'SourceSite',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('baseUrl', sa.String(), nullable=False),
        sa.Column('adapterType', sa.String(), nullable=False),
        sa.Column('isEnabled', sa.Boolean(), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('adapterType', 'baseUrl', name='SourceSite_adapter_baseUrl_uq'),
    )
    op.create_index('SourceSite_adapterType_idx', 'SourceSite', ['adapterType'])

    op.create_table(
        'SourceRule',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('sourceSiteId', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('indexUrl', sa.String(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('cadencePolicy', sa.Text(), nullable=True),
        sa.Column('activeWindowPolicy', sa.Text(), nullable=True),
        sa.Column('staleWindowPolicy', sa.Text(), nullable=True),
        sa.Column('categoriesToArchive', sa.Text(), nullable=True),
        sa.Column('categoriesToPreview', sa.Text(), nullable=True),
        sa.Column('categoriesAllowedForImport', sa.Text(), nullable=True),
        sa.Column('autoImportPolicy', sa.String(), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['sourceSiteId'], ['SourceSite.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sourceSiteId', 'indexUrl', name='SourceRule_site_indexUrl_uq'),
    )
    op.create_index('SourceRule_enabled_idx', 'SourceRule', ['enabled'])

    op.execute("""
        INSERT INTO SourceSite (name, baseUrl, adapterType, isEnabled)
        VALUES ('SG Aquatics', 'https://www.sgaquatics.org.sg', 'sgaquatics_events', 1)
    """)
    op.execute("""
        INSERT INTO SourceRule (
            sourceSiteId,
            name,
            indexUrl,
            enabled,
            cadencePolicy,
            activeWindowPolicy,
            staleWindowPolicy,
            categoriesToArchive,
            categoriesToPreview,
            categoriesAllowedForImport,
            autoImportPolicy
        )
        SELECT
            id,
            'SG Aquatics Swimming Events',
            'https://www.sgaquatics.org.sg/swimming/events/event-results/',
            1,
            '{"cadence":"manual_only","schedule":"not_configured"}',
            '{"mode":"manual_preview_only"}',
            '{"mode":"manual_preview_only"}',
            '["event_information","official_results","overall_results","programme","psych_sheets","start_lists","team_leader","other_pdf"]',
            '["overall_results","other_pdf"]',
            '["overall_results","other_pdf"]',
            'preview_only'
        FROM SourceSite
        WHERE adapterType = 'sgaquatics_events'
          AND baseUrl = 'https://www.sgaquatics.org.sg'
    """)

    op.create_table(
        'SourceEvent',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('sourceRuleId', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('pageTitle', sa.String(), nullable=True),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('sourceYear', sa.String(), nullable=True),
        sa.Column('sourceDateLabel', sa.String(), nullable=True),
        sa.Column('readinessStatus', sa.String(), nullable=False),
        sa.Column('statusReason', sa.String(), nullable=True),
        sa.Column('isCurrentlyListed', sa.Boolean(), nullable=False),
        sa.Column('pdfCount', sa.Integer(), nullable=False),
        sa.Column('resultPdfCount', sa.Integer(), nullable=False),
        sa.Column('categoryCountsJson', sa.Text(), nullable=True),
        sa.Column('firstSeenAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('lastSeenInIndexAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lastCheckedAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lastChangedAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lastErrorMessage', sa.String(), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['sourceRuleId'], ['SourceRule.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sourceRuleId', 'url', name='SourceEvent_rule_url_uq'),
    )
    op.create_index('SourceEvent_rule_status_idx', 'SourceEvent', ['sourceRuleId', 'readinessStatus'])

    op.create_table(
        'SourceEventDocument',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('sourceEventId', sa.Integer(), nullable=False),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('filename', sa.String(), nullable=False),
        sa.Column('category', sa.String(), nullable=False),
        sa.Column('firstSeenAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('lastSeenAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lastCheckedAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lastHashSha256', sa.String(), nullable=True),
        sa.Column('lastHashCheckedAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('isCurrentlyListed', sa.Boolean(), nullable=False),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['sourceEventId'], ['SourceEvent.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sourceEventId', 'url', name='SourceEventDocument_identity_uq'),
    )
    op.create_index('SourceEventDocument_event_category_idx', 'SourceEventDocument', ['sourceEventId', 'category'])

    op.create_table(
        'MonitorRun',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('sourceRuleId', sa.Integer(), nullable=False),
        sa.Column('triggerType', sa.String(), nullable=False),
        sa.Column('triggeredBy', sa.String(), nullable=True),
        sa.Column('adapterVersion', sa.String(), nullable=True),
        sa.Column('indexUrlSnapshot', sa.String(), nullable=True),
        sa.Column('ruleConfigSnapshotJson', sa.Text(), nullable=True),
        sa.Column('startedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('finishedAt', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('eventsDiscovered', sa.Integer(), nullable=False),
        sa.Column('eventsWithResults', sa.Integer(), nullable=False),
        sa.Column('addedEvents', sa.Integer(), nullable=False),
        sa.Column('updatedEvents', sa.Integer(), nullable=False),
        sa.Column('unchangedEvents', sa.Integer(), nullable=False),
        sa.Column('absentFromIndexEvents', sa.Integer(), nullable=False),
        sa.Column('addedDocuments', sa.Integer(), nullable=False),
        sa.Column('updatedDocuments', sa.Integer(), nullable=False),
        sa.Column('unchangedDocuments', sa.Integer(), nullable=False),
        sa.Column('actionRequiredCount', sa.Integer(), nullable=False),
        sa.Column('errorMessage', sa.String(), nullable=True),
        sa.Column('summaryJson', sa.Text(), nullable=True),
        sa.Column('createdAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updatedAt', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['sourceRuleId'], ['SourceRule.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('MonitorRun_rule_status_idx', 'MonitorRun', ['sourceRuleId', 'status'])
    op.create_index('MonitorRun_startedAt_idx', 'MonitorRun', ['startedAt'])
    op.create_index(
        'MonitorRun_one_running_per_rule_uq',
        'MonitorRun',
        ['sourceRuleId'],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index('MonitorRun_one_running_per_rule_uq', table_name='MonitorRun')
    op.drop_index('MonitorRun_startedAt_idx', table_name='MonitorRun')
    op.drop_index('MonitorRun_rule_status_idx', table_name='MonitorRun')
    op.drop_table('MonitorRun')

    op.drop_index('SourceEventDocument_event_category_idx', table_name='SourceEventDocument')
    op.drop_table('SourceEventDocument')

    op.drop_index('SourceEvent_rule_status_idx', table_name='SourceEvent')
    op.drop_table('SourceEvent')

    op.drop_index('SourceRule_enabled_idx', table_name='SourceRule')
    op.drop_table('SourceRule')

    op.drop_index('SourceSite_adapterType_idx', table_name='SourceSite')
    op.drop_table('SourceSite')
