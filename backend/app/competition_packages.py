"""Competition-package metadata resolution and idempotent hierarchy persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .models import (
    CompetitionDay,
    CompetitionEdition,
    CompetitionSegment,
    CompetitionSession,
    Meet,
)
from .parsers.hytek import ParsedMeet
from .source_monitoring import canonicalize_url

RESOLVER_VERSION = "competition-metadata-v1"


@dataclass(frozen=True)
class SessionResolution:
    race_date: date | None
    status: str
    diagnostics: tuple[str, ...] = ()


def resolve_session_metadata(parsed: ParsedMeet) -> SessionResolution:
    """Resolve a session's race date without using report-generation time."""
    if parsed.metadata_conflicts:
        return SessionResolution(
            race_date=None,
            status="conflicting",
            diagnostics=tuple(parsed.metadata_conflicts),
        )

    if parsed.day_number is None or parsed.session_number is None:
        return SessionResolution(race_date=None, status="unknown")

    if parsed.day_number <= 0 or parsed.session_number <= 0:
        return SessionResolution(
            race_date=None,
            status="conflicting",
            diagnostics=("Day and session numbers must be positive",),
        )

    if parsed.start_date is None or parsed.end_date is None:
        return SessionResolution(race_date=None, status="unknown")

    race_date = parsed.start_date + timedelta(days=parsed.day_number - 1)
    if race_date < parsed.start_date or race_date > parsed.end_date:
        return SessionResolution(
            race_date=None,
            status="conflicting",
            diagnostics=(
                f"Day {parsed.day_number} is outside segment range "
                f"{parsed.start_date.isoformat()} to {parsed.end_date.isoformat()}",
            ),
        )

    return SessionResolution(race_date=race_date, status="derived")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _apply_segment_dates(
    segment: CompetitionSegment,
    parsed: ParsedMeet,
    *,
    resolved_at: datetime,
) -> None:
    incoming = (parsed.start_date, parsed.end_date)
    existing = (segment.startDate, segment.endDate)

    if incoming == (None, None):
        if existing == (None, None):
            segment.resolutionStatus = "unknown"
        return

    if None in incoming:
        raise ValueError(f"Incomplete date range for segment {parsed.meet_name}")

    if existing != (None, None) and existing != incoming:
        segment.resolutionStatus = "conflicting"
        segment.resolverVersion = RESOLVER_VERSION
        segment.resolvedAt = resolved_at
        raise ValueError(
            f"Conflicting date range for segment {parsed.meet_name}: "
            f"stored {existing[0]} to {existing[1]}, received {incoming[0]} to {incoming[1]}"
        )

    segment.startDate = parsed.start_date
    segment.endDate = parsed.end_date
    segment.resolutionStatus = "verified"
    segment.resolverVersion = RESOLVER_VERSION
    segment.resolvedAt = resolved_at


def _expand_edition_bounds(
    edition: CompetitionEdition,
    *,
    segment_start: date | None,
    segment_end: date | None,
    resolved_at: datetime,
) -> None:
    if segment_start is None or segment_end is None:
        return
    edition.startDate = min(edition.startDate, segment_start) if edition.startDate else segment_start
    edition.endDate = max(edition.endDate, segment_end) if edition.endDate else segment_end
    edition.resolutionStatus = "derived"
    edition.resolverVersion = RESOLVER_VERSION
    edition.resolvedAt = resolved_at


def upsert_competition_hierarchy(
    db: Session,
    *,
    source_key: str,
    competition_title: str,
    parsed: ParsedMeet,
    legacy_meet: Meet | None = None,
    source_event_id: int | None = None,
) -> CompetitionSession:
    """Create/reuse edition → segment → day → session for one parsed sheet.

    The umbrella identity must come from an authoritative source-page/manifest
    key supplied by the caller. This function never guesses it from segment
    names such as "Juniors" or "Seniors".
    """
    canonical_source_key = canonicalize_url(source_key)
    title = competition_title.strip()
    segment_key = parsed.meet_name.strip()
    if not canonical_source_key:
        raise ValueError("Competition source key is required")
    if not title:
        raise ValueError("Competition title is required")
    if not segment_key:
        raise ValueError("Parsed segment name is required")
    if parsed.metadata_conflicts:
        raise ValueError("Cannot persist conflicting competition metadata")
    if parsed.day_number is None or parsed.session_number is None:
        raise ValueError("A structured Day N Session N header is required")

    resolution = resolve_session_metadata(parsed)
    if resolution.status == "conflicting":
        raise ValueError("; ".join(resolution.diagnostics))

    resolved_at = _utc_now()
    edition = db.query(CompetitionEdition).filter(
        CompetitionEdition.sourceKey == canonical_source_key
    ).first()
    if edition is None:
        edition = CompetitionEdition(
            sourceKey=canonical_source_key,
            title=title,
            sourceEventId=source_event_id,
            resolutionStatus="unknown",
            resolverVersion=RESOLVER_VERSION,
        )
        db.add(edition)
        db.flush()
    else:
        if source_event_id is not None and edition.sourceEventId not in {None, source_event_id}:
            raise ValueError("Competition source key is already bound to another source event")
        edition.title = title
        if edition.sourceEventId is None:
            edition.sourceEventId = source_event_id

    segment = db.query(CompetitionSegment).filter(
        CompetitionSegment.competitionEditionId == edition.id,
        CompetitionSegment.key == segment_key,
    ).first()
    if segment is None:
        segment = CompetitionSegment(
            competitionEditionId=edition.id,
            key=segment_key,
            name=segment_key,
            legacyMeetId=legacy_meet.id if legacy_meet else None,
            resolutionStatus="unknown",
            resolverVersion=RESOLVER_VERSION,
        )
        db.add(segment)
        db.flush()
    elif legacy_meet is not None:
        if segment.legacyMeetId not in {None, legacy_meet.id}:
            raise ValueError(f"Segment {segment_key} is already linked to another legacy meet")
        segment.legacyMeetId = legacy_meet.id

    _apply_segment_dates(segment, parsed, resolved_at=resolved_at)
    _expand_edition_bounds(
        edition,
        segment_start=segment.startDate,
        segment_end=segment.endDate,
        resolved_at=resolved_at,
    )

    day = db.query(CompetitionDay).filter(
        CompetitionDay.competitionSegmentId == segment.id,
        CompetitionDay.dayNumber == parsed.day_number,
    ).first()
    if day is None:
        day = CompetitionDay(
            competitionSegmentId=segment.id,
            dayNumber=parsed.day_number,
            date=resolution.race_date,
            resolutionStatus=resolution.status,
            resolverVersion=RESOLVER_VERSION,
            resolvedAt=resolved_at,
        )
        db.add(day)
        db.flush()
    elif day.date not in {None, resolution.race_date}:
        day.resolutionStatus = "conflicting"
        raise ValueError(
            f"Day {parsed.day_number} has conflicting dates: "
            f"stored {day.date}, received {resolution.race_date}"
        )
    elif day.date is None and resolution.race_date is not None:
        day.date = resolution.race_date
        day.resolutionStatus = resolution.status
        day.resolverVersion = RESOLVER_VERSION
        day.resolvedAt = resolved_at

    competition_session = db.query(CompetitionSession).filter(
        CompetitionSession.competitionDayId == day.id,
        CompetitionSession.sessionNumber == parsed.session_number,
    ).first()
    if competition_session is None:
        competition_session = CompetitionSession(
            competitionDayId=day.id,
            sessionNumber=parsed.session_number,
            label=parsed.session,
            resolutionStatus=resolution.status,
            resolverVersion=RESOLVER_VERSION,
            resolvedAt=resolved_at,
        )
        db.add(competition_session)
        db.flush()
    elif (
        competition_session.resolutionStatus != resolution.status
        or competition_session.label != parsed.session
        or competition_session.resolverVersion != RESOLVER_VERSION
    ):
        competition_session.label = parsed.session
        competition_session.resolutionStatus = resolution.status
        competition_session.resolverVersion = RESOLVER_VERSION
        competition_session.resolvedAt = resolved_at

    return competition_session
