"""
SQLAlchemy ORM models.

Models: Swimmer, Meet, Result, RelayResult, RelayLeg
"""

from datetime import date as calendar_date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class SourceSite(Base):
    __tablename__ = "SourceSite"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    baseUrl: Mapped[str] = mapped_column(String, nullable=False)
    adapterType: Mapped[str] = mapped_column(String, nullable=False)
    isEnabled: Mapped[bool] = mapped_column(Boolean, default=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    rules: Mapped[list["SourceRule"]] = relationship(back_populates="source_site", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("adapterType", "baseUrl", name="SourceSite_adapter_baseUrl_uq"),
        Index("SourceSite_adapterType_idx", "adapterType"),
    )


class SourceRule(Base):
    __tablename__ = "SourceRule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sourceSiteId: Mapped[int] = mapped_column(Integer, ForeignKey("SourceSite.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    indexUrl: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    cadencePolicy: Mapped[str | None] = mapped_column(Text, nullable=True)
    activeWindowPolicy: Mapped[str | None] = mapped_column(Text, nullable=True)
    staleWindowPolicy: Mapped[str | None] = mapped_column(Text, nullable=True)
    categoriesToArchive: Mapped[str | None] = mapped_column(Text, nullable=True)
    categoriesToPreview: Mapped[str | None] = mapped_column(Text, nullable=True)
    categoriesAllowedForImport: Mapped[str | None] = mapped_column(Text, nullable=True)
    autoImportPolicy: Mapped[str] = mapped_column(String, nullable=False, default="preview_only")
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    source_site: Mapped["SourceSite"] = relationship(back_populates="rules")
    source_events: Mapped[list["SourceEvent"]] = relationship(back_populates="source_rule", cascade="all, delete-orphan")
    monitor_runs: Mapped[list["MonitorRun"]] = relationship(back_populates="source_rule", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("sourceSiteId", "indexUrl", name="SourceRule_site_indexUrl_uq"),
        Index("SourceRule_enabled_idx", "enabled"),
    )


class SourceEvent(Base):
    __tablename__ = "SourceEvent"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sourceRuleId: Mapped[int] = mapped_column(Integer, ForeignKey("SourceRule.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    pageTitle: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str] = mapped_column(String, nullable=False)
    sourceYear: Mapped[str | None] = mapped_column(String, nullable=True)
    sourceDateLabel: Mapped[str | None] = mapped_column(String, nullable=True)
    readinessStatus: Mapped[str] = mapped_column(String, nullable=False)
    statusReason: Mapped[str | None] = mapped_column(String, nullable=True)
    isCurrentlyListed: Mapped[bool] = mapped_column(Boolean, default=True)
    pdfCount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resultPdfCount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    categoryCountsJson: Mapped[str | None] = mapped_column(Text, nullable=True)
    firstSeenAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lastSeenInIndexAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lastCheckedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lastChangedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lastErrorMessage: Mapped[str | None] = mapped_column(String, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    source_rule: Mapped["SourceRule"] = relationship(back_populates="source_events")
    documents: Mapped[list["SourceEventDocument"]] = relationship(back_populates="source_event", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("sourceRuleId", "url", name="SourceEvent_rule_url_uq"),
        Index("SourceEvent_rule_status_idx", "sourceRuleId", "readinessStatus"),
    )


class SourceEventDocument(Base):
    __tablename__ = "SourceEventDocument"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sourceEventId: Mapped[int] = mapped_column(Integer, ForeignKey("SourceEvent.id"), nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    firstSeenAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lastSeenAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lastCheckedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lastHashSha256: Mapped[str | None] = mapped_column(String, nullable=True)
    lastHashCheckedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    isCurrentlyListed: Mapped[bool] = mapped_column(Boolean, default=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    source_event: Mapped["SourceEvent"] = relationship(back_populates="documents")

    __table_args__ = (
        UniqueConstraint("sourceEventId", "url", name="SourceEventDocument_identity_uq"),
        Index("SourceEventDocument_event_category_idx", "sourceEventId", "category"),
    )


class MonitorRun(Base):
    __tablename__ = "MonitorRun"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sourceRuleId: Mapped[int] = mapped_column(Integer, ForeignKey("SourceRule.id"), nullable=False)
    triggerType: Mapped[str] = mapped_column(String, nullable=False, default="manual_api")
    triggeredBy: Mapped[str | None] = mapped_column(String, nullable=True)
    adapterVersion: Mapped[str | None] = mapped_column(String, nullable=True)
    indexUrlSnapshot: Mapped[str | None] = mapped_column(String, nullable=True)
    ruleConfigSnapshotJson: Mapped[str | None] = mapped_column(Text, nullable=True)
    startedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finishedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    eventsDiscovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eventsWithResults: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    addedEvents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updatedEvents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchangedEvents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    absentFromIndexEvents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    addedDocuments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updatedDocuments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchangedDocuments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actionRequiredCount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errorMessage: Mapped[str | None] = mapped_column(String, nullable=True)
    summaryJson: Mapped[str | None] = mapped_column(Text, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    source_rule: Mapped["SourceRule"] = relationship(back_populates="monitor_runs")

    __table_args__ = (
        Index("MonitorRun_rule_status_idx", "sourceRuleId", "status"),
        Index("MonitorRun_startedAt_idx", "startedAt"),
        Index(
            "MonitorRun_one_running_per_rule_uq",
            "sourceRuleId",
            unique=True,
            sqlite_where=text("status = 'running'"),
            postgresql_where=text("status = 'running'"),
        ),
    )


class RawDocument(Base):
    __tablename__ = "RawDocument"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sha256: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    byteSize: Mapped[int] = mapped_column(Integer, nullable=False)
    contentType: Mapped[str | None] = mapped_column(String, nullable=True)
    storagePath: Mapped[str] = mapped_column(String, nullable=False)
    originalFilename: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    isValidPdf: Mapped[bool] = mapped_column(Boolean, default=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    source_references: Mapped[list["SourceReference"]] = relationship(back_populates="raw_document", cascade="all, delete-orphan")

    __table_args__ = (
        Index("RawDocument_sha256_idx", "sha256"),
        Index("RawDocument_category_idx", "category"),
    )


class SourceReference(Base):
    __tablename__ = "SourceReference"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rawDocumentId: Mapped[int] = mapped_column(Integer, ForeignKey("RawDocument.id"), nullable=False)
    sourceType: Mapped[str] = mapped_column(String, nullable=False)  # upload, sg-aquatics, manual, etc.
    sourceLabel: Mapped[str | None] = mapped_column(String, nullable=True)
    sourceUrl: Mapped[str | None] = mapped_column(String, nullable=True)
    sourcePageUrl: Mapped[str | None] = mapped_column(String, nullable=True)
    filenameSeen: Mapped[str | None] = mapped_column(String, nullable=True)
    sourceIdentity: Mapped[str] = mapped_column(String, nullable=False)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    raw_document: Mapped["RawDocument"] = relationship(back_populates="source_references")

    __table_args__ = (
        Index("SourceReference_rawDocumentId_idx", "rawDocumentId"),
        Index("SourceReference_sourceType_idx", "sourceType"),
        UniqueConstraint("rawDocumentId", "sourceIdentity", name="SourceReference_identity_uq"),
    )


class DocumentClassification(Base):
    __tablename__ = "DocumentClassification"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rawDocumentId: Mapped[int] = mapped_column(Integer, ForeignKey("RawDocument.id"), nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    classifierVersion: Mapped[str] = mapped_column(String, nullable=False, default="filename-v1")
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    isCurrent: Mapped[bool] = mapped_column(Boolean, default=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("DocumentClassification_rawDocumentId_idx", "rawDocumentId"),
        Index("DocumentClassification_category_idx", "category"),
    )


class IngestionRun(Base):
    __tablename__ = "IngestionRun"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String, nullable=False)  # preview, append, replace, rebuild
    inputScope: Mapped[str | None] = mapped_column(String, nullable=True)
    parserVersion: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    recordsInserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recordsUpdated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicatesSkipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validationErrors: Mapped[str | None] = mapped_column(String, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("IngestionRun_mode_idx", "mode"),
        Index("IngestionRun_status_idx", "status"),
    )


class ParseJob(Base):
    __tablename__ = "ParseJob"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rawDocumentId: Mapped[int] = mapped_column(Integer, ForeignKey("RawDocument.id"), nullable=False)
    parserName: Mapped[str] = mapped_column(String, nullable=False)
    parserVersion: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    confidenceScore: Mapped[int | None] = mapped_column(Integer, nullable=True)  # percentage 0-100
    confidencePassed: Mapped[bool] = mapped_column(Boolean, default=False)
    eventsCount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    individualResultsCount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relayResultsCount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unmatchedLinesCount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errorMessage: Mapped[str | None] = mapped_column(String, nullable=True)
    parsedArtifactPath: Mapped[str | None] = mapped_column(String, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    raw_document: Mapped["RawDocument"] = relationship()

    __table_args__ = (
        Index("ParseJob_rawDocumentId_idx", "rawDocumentId"),
        Index("ParseJob_parser_idx", "parserName", "parserVersion"),
        Index("ParseJob_status_idx", "status"),
    )


class TeamCanon(Base):
    __tablename__ = "TeamCanon"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonicalName: Mapped[str] = mapped_column(String, nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False, unique=True)  # normalized identity key
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    aliases: Mapped[list["TeamAlias"]] = relationship(back_populates="canonical", cascade="all, delete-orphan")

    __table_args__ = (
        Index("TeamCanon_key_idx", "key"),
    )


class TeamAlias(Base):
    __tablename__ = "TeamAlias"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    teamCanonId: Mapped[int] = mapped_column(Integer, ForeignKey("TeamCanon.id"), nullable=False)
    rawName: Mapped[str] = mapped_column(String, nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)  # normalized key of rawName
    firstSeenAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lastSeenAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    canonical: Mapped["TeamCanon"] = relationship(back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("rawName", name="TeamAlias_rawName_uq"),
        Index("TeamAlias_key_idx", "key"),
    )


class Swimmer(Base):
    __tablename__ = "Swimmer"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    nameKey: Mapped[str | None] = mapped_column(String, nullable=True)  # normalized identity key (see entity_resolution)
    teamKey: Mapped[str | None] = mapped_column(String, nullable=True)  # normalized team identity key
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team: Mapped[str | None] = mapped_column(String, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    results: Mapped[list["Result"]] = relationship(back_populates="swimmer", cascade="all, delete-orphan")

    __table_args__ = (
        Index("Swimmer_name_idx", "name"),
        Index("Swimmer_nameKey_idx", "nameKey"),
        Index(
            "Swimmer_identity_uq",
            "nameKey",
            "teamKey",
            "age",
            unique=True,
            postgresql_where=text('"teamKey" <> \'\' AND age IS NOT NULL'),
            sqlite_where=text('"teamKey" <> \'\' AND age IS NOT NULL'),
        ),
        Index("Swimmer_team_idx", "team"),
    )

    def __repr__(self) -> str:
        return f"<Swimmer(id={self.id}, name='{self.name}', team='{self.team}')>"


class CompetitionEdition(Base):
    """One official competition edition, independent of its DB projection."""

    __tablename__ = "CompetitionEdition"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sourceKey: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    sourceEventId: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("SourceEvent.id", ondelete="SET NULL"), nullable=True
    )
    startDate: Mapped[calendar_date | None] = mapped_column(Date, nullable=True)
    endDate: Mapped[calendar_date | None] = mapped_column(Date, nullable=True)
    resolutionStatus: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    resolverVersion: Mapped[str] = mapped_column(String, nullable=False)
    resolvedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    segments: Mapped[list["CompetitionSegment"]] = relationship(
        back_populates="competition", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            '"endDate" IS NULL OR "startDate" IS NULL OR "endDate" >= "startDate"',
            name="CompetitionEdition_date_range_ck",
        ),
        CheckConstraint(
            '"resolutionStatus" IN (\'unknown\', \'derived\', \'verified\', \'conflicting\')',
            name="CompetitionEdition_resolution_status_ck",
        ),
        Index("CompetitionEdition_sourceKey_idx", "sourceKey"),
        Index("CompetitionEdition_dates_idx", "startDate", "endDate"),
    )


class CompetitionSegment(Base):
    """A competition part whose day/session numbering is internally coherent."""

    __tablename__ = "CompetitionSegment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    competitionEditionId: Mapped[int] = mapped_column(
        Integer, ForeignKey("CompetitionEdition.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    legacyMeetId: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("Meet.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    startDate: Mapped[calendar_date | None] = mapped_column(Date, nullable=True)
    endDate: Mapped[calendar_date | None] = mapped_column(Date, nullable=True)
    resolutionStatus: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    resolverVersion: Mapped[str] = mapped_column(String, nullable=False)
    resolvedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    competition: Mapped["CompetitionEdition"] = relationship(back_populates="segments")
    legacy_meet: Mapped["Meet | None"] = relationship(back_populates="competition_segment")
    days: Mapped[list["CompetitionDay"]] = relationship(
        back_populates="segment", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("competitionEditionId", "key", name="CompetitionSegment_edition_key_uq"),
        CheckConstraint(
            '"endDate" IS NULL OR "startDate" IS NULL OR "endDate" >= "startDate"',
            name="CompetitionSegment_date_range_ck",
        ),
        CheckConstraint(
            '"resolutionStatus" IN (\'unknown\', \'derived\', \'verified\', \'conflicting\')',
            name="CompetitionSegment_resolution_status_ck",
        ),
        Index("CompetitionSegment_competition_idx", "competitionEditionId"),
    )


class CompetitionDay(Base):
    __tablename__ = "CompetitionDay"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    competitionSegmentId: Mapped[int] = mapped_column(
        Integer, ForeignKey("CompetitionSegment.id", ondelete="CASCADE"), nullable=False
    )
    dayNumber: Mapped[int] = mapped_column(Integer, nullable=False)
    date: Mapped[calendar_date | None] = mapped_column(Date, nullable=True)
    resolutionStatus: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    resolverVersion: Mapped[str] = mapped_column(String, nullable=False)
    resolvedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    segment: Mapped["CompetitionSegment"] = relationship(back_populates="days")
    sessions: Mapped[list["CompetitionSession"]] = relationship(
        back_populates="day", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("competitionSegmentId", "dayNumber", name="CompetitionDay_segment_day_uq"),
        CheckConstraint('"dayNumber" > 0', name="CompetitionDay_number_ck"),
        CheckConstraint(
            '"resolutionStatus" IN (\'unknown\', \'derived\', \'verified\', \'conflicting\')',
            name="CompetitionDay_resolution_status_ck",
        ),
        Index("CompetitionDay_segment_date_idx", "competitionSegmentId", "date"),
    )


class CompetitionSession(Base):
    __tablename__ = "CompetitionSession"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    competitionDayId: Mapped[int] = mapped_column(
        Integer, ForeignKey("CompetitionDay.id", ondelete="CASCADE"), nullable=False
    )
    sessionNumber: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    resolutionStatus: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    resolverVersion: Mapped[str] = mapped_column(String, nullable=False)
    resolvedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    day: Mapped["CompetitionDay"] = relationship(back_populates="sessions")
    results: Mapped[list["Result"]] = relationship(back_populates="competition_session")
    relay_results: Mapped[list["RelayResult"]] = relationship(back_populates="competition_session")

    __table_args__ = (
        UniqueConstraint("competitionDayId", "sessionNumber", name="CompetitionSession_day_session_uq"),
        CheckConstraint('"sessionNumber" > 0', name="CompetitionSession_number_ck"),
        CheckConstraint(
            '"resolutionStatus" IN (\'unknown\', \'derived\', \'verified\', \'conflicting\')',
            name="CompetitionSession_resolution_status_ck",
        ),
        Index("CompetitionSession_day_idx", "competitionDayId"),
    )


class Meet(Base):
    __tablename__ = "Meet"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    startDate: Mapped[datetime] = mapped_column("date", DateTime(timezone=True), nullable=False)
    endDate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    parserFormat: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "hytek"
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    results: Mapped[list["Result"]] = relationship(back_populates="meet", cascade="all, delete-orphan")
    competition_segment: Mapped["CompetitionSegment | None"] = relationship(
        back_populates="legacy_meet", uselist=False
    )

    __table_args__ = (
        Index("Meet_date_idx", "date"),
    )

    def __repr__(self) -> str:
        return f"<Meet(id={self.id}, name='{self.name}', startDate={self.startDate})>"


class Result(Base):
    __tablename__ = "Result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    swimmerId: Mapped[int] = mapped_column(Integer, ForeignKey("Swimmer.id"), nullable=False)
    meetId: Mapped[int] = mapped_column(Integer, ForeignKey("Meet.id"), nullable=False)
    event: Mapped[str] = mapped_column(String, nullable=False)
    time: Mapped[str | None] = mapped_column(String, nullable=True)
    seedTime: Mapped[str | None] = mapped_column(String, nullable=True)
    placement: Mapped[int | None] = mapped_column(Integer, nullable=True)
    isDQ: Mapped[bool] = mapped_column(Boolean, default=False)
    resultStatus: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    dqCode: Mapped[str | None] = mapped_column(String, nullable=True)
    dqDescription: Mapped[str | None] = mapped_column(String, nullable=True)
    isGuest: Mapped[bool] = mapped_column(Boolean, default=False)
    qualifier: Mapped[str | None] = mapped_column(String, nullable=True)
    reactionTime: Mapped[str | None] = mapped_column(String, nullable=True)
    splits: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON string of split data
    round: Mapped[str | None] = mapped_column(String, nullable=True)  # "Prelim", "Final", "Timed Final", "Semifinal"
    swimDate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # Actual date of this swim
    contentHash: Mapped[str | None] = mapped_column(String, nullable=True)  # SHA-256 for deduplication
    rawSwimmerName: Mapped[str | None] = mapped_column(String, nullable=True)  # immutable parsed source value
    rawTeamName: Mapped[str | None] = mapped_column(String, nullable=True)  # immutable parsed source value
    sourceDocumentSha256: Mapped[str | None] = mapped_column(String, nullable=True)
    parseJobId: Mapped[int | None] = mapped_column(Integer, ForeignKey("ParseJob.id"), nullable=True)
    ingestionRunId: Mapped[int | None] = mapped_column(Integer, ForeignKey("IngestionRun.id"), nullable=True)
    parserVersion: Mapped[str | None] = mapped_column(String, nullable=True)
    sourceEventNumber: Mapped[str | None] = mapped_column(String, nullable=True)
    sessionId: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("CompetitionSession.id", ondelete="RESTRICT"), nullable=True
    )
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    swimmer: Mapped["Swimmer"] = relationship(back_populates="results")
    meet: Mapped["Meet"] = relationship(back_populates="results")
    competition_session: Mapped["CompetitionSession | None"] = relationship(back_populates="results")

    __table_args__ = (
        Index("Result_swimmerId_idx", "swimmerId"),
        Index("Result_meetId_idx", "meetId"),
        Index("Result_event_idx", "event"),
        Index("Result_contentHash_uq", "contentHash", unique=True),
        Index("Result_sessionId_idx", "sessionId"),
        Index("Result_dedup_idx", "swimmerId", "meetId", "event", "round", "swimDate"),
        CheckConstraint(
            '"resultStatus" IN (\'finished\', \'dq\', \'ns\', \'dns\', \'dnf\', \'scratched\', \'unknown\')',
            name="Result_status_ck",
        ),
    )

    def __repr__(self) -> str:
        return f"<Result(id={self.id}, event='{self.event}', time='{self.time}')>"


class RelayResult(Base):
    __tablename__ = "RelayResult"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meetId: Mapped[int] = mapped_column(Integer, ForeignKey("Meet.id"), nullable=False)
    event: Mapped[str] = mapped_column(String, nullable=False)
    teamName: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "Olympians Swimming (Can)"
    relayLetter: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "A", "B"
    time: Mapped[str | None] = mapped_column(String, nullable=True)
    seedTime: Mapped[str | None] = mapped_column(String, nullable=True)
    placement: Mapped[int | None] = mapped_column(Integer, nullable=True)
    isDQ: Mapped[bool] = mapped_column(Boolean, default=False)
    resultStatus: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    dqCode: Mapped[str | None] = mapped_column(String, nullable=True)
    dqDescription: Mapped[str | None] = mapped_column(String, nullable=True)
    isExhibition: Mapped[bool] = mapped_column(Boolean, default=False)
    round: Mapped[str | None] = mapped_column(String, nullable=True)
    swimDate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    splits: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON string
    reactionTime: Mapped[str | None] = mapped_column(String, nullable=True)
    legParseStatus: Mapped[str | None] = mapped_column(String(20), nullable=True)
    legParseWarning: Mapped[str | None] = mapped_column(Text, nullable=True)
    contentHash: Mapped[str | None] = mapped_column(String, nullable=True)
    rawTeamName: Mapped[str | None] = mapped_column(String, nullable=True)  # immutable parsed source value
    sourceDocumentSha256: Mapped[str | None] = mapped_column(String, nullable=True)
    parseJobId: Mapped[int | None] = mapped_column(Integer, ForeignKey("ParseJob.id"), nullable=True)
    ingestionRunId: Mapped[int | None] = mapped_column(Integer, ForeignKey("IngestionRun.id"), nullable=True)
    parserVersion: Mapped[str | None] = mapped_column(String, nullable=True)
    sourceEventNumber: Mapped[str | None] = mapped_column(String, nullable=True)
    sessionId: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("CompetitionSession.id", ondelete="RESTRICT"), nullable=True
    )
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    meet: Mapped["Meet"] = relationship()
    competition_session: Mapped["CompetitionSession | None"] = relationship(back_populates="relay_results")
    legs: Mapped[list["RelayLeg"]] = relationship(back_populates="relay_result", cascade="all, delete-orphan")

    __table_args__ = (
        Index("RelayResult_meetId_idx", "meetId"),
        Index("RelayResult_event_idx", "event"),
        Index("RelayResult_contentHash_uq", "contentHash", unique=True),
        Index("RelayResult_sessionId_idx", "sessionId"),
        CheckConstraint(
            '"legParseStatus" IS NULL OR "legParseStatus" IN (\'complete\', \'partial\', \'unavailable\')',
            name="RelayResult_leg_parse_status_ck",
        ),
        CheckConstraint(
            '"resultStatus" IN (\'finished\', \'dq\', \'ns\', \'dns\', \'dnf\', \'scratched\', \'unknown\')',
            name="RelayResult_status_ck",
        ),
    )

    def __repr__(self) -> str:
        return f"<RelayResult(id={self.id}, event='{self.event}', team='{self.teamName}')>"


class RelayLeg(Base):
    __tablename__ = "RelayLeg"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    relayResultId: Mapped[int] = mapped_column(Integer, ForeignKey("RelayResult.id"), nullable=False)
    legNumber: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-4
    swimmerId: Mapped[int | None] = mapped_column(Integer, ForeignKey("Swimmer.id"), nullable=True)
    swimmerName: Mapped[str] = mapped_column(String, nullable=False)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str | None] = mapped_column(String, nullable=True)  # "M" or "W" (from mixed relays)
    isGuest: Mapped[bool] = mapped_column(Boolean, default=False)
    reactionTime: Mapped[str | None] = mapped_column(String, nullable=True)  # Exchange RT
    splitTime: Mapped[str | None] = mapped_column(String, nullable=True)  # Their total leg time
    splits: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON: per-swimmer lap splits

    relay_result: Mapped["RelayResult"] = relationship(back_populates="legs")
    swimmer: Mapped["Swimmer"] = relationship()

    __table_args__ = (
        Index("RelayLeg_relayResultId_idx", "relayResultId"),
        Index("RelayLeg_swimmerId_idx", "swimmerId"),
    )
