"""Competition-package metadata resolution and idempotent hierarchy persistence."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import PurePath
from typing import Any

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


@dataclass(frozen=True)
class CompetitionIdentity:
    """Caller-supplied identity for one competition package or segment.

    Parsed values are placeholders only. When an immutable source prints no
    competition name or date range, these values are the source of truth, and
    their provenance is recorded so the database never claims a page printed
    something it did not.

    ``scope`` distinguishes the two jobs the same fields do: a ``package``
    identity names the umbrella competition (55th SNAG 2025) and is only a
    fallback for segment names, while a ``segment`` identity names one document's
    own segment and must therefore agree with anything the page prints.
    """

    title: str
    start_date: date | None = None
    end_date: date | None = None
    source: str = "operator"  # "operator" | "printed"
    scope: str = "package"  # "package" | "segment"


def resolve_segment_identity(
    parsed: ParsedMeet, identity: CompetitionIdentity | None = None
) -> tuple[str, date | None, date | None, str]:
    """Resolve a segment's name and date range, failing closed on disagreement.

    Printed evidence wins over caller input. Caller input fills only what the
    page does not print, and each endpoint is resolved on its own. A supplied
    range scoped to this segment that contradicts the printed range raises; an
    umbrella (package) range is wider by nature, so a narrower printed segment
    range simply wins. A caller-supplied *segment* name that contradicts the
    printed name raises too.
    """
    printed_start, printed_end = parsed.start_date, parsed.end_date
    supplied_start = identity.start_date if identity else None
    supplied_end = identity.end_date if identity else None
    printed_name = parsed.meet_name.strip()
    supplied_name = identity.title.strip() if identity and identity.title else ""
    if (
        printed_name
        and supplied_name
        and identity is not None
        and identity.scope == "segment"
        and printed_name != supplied_name
    ):
        raise ValueError(
            f"Segment name conflict: source prints '{printed_name}', caller "
            f"supplied '{supplied_name}'"
        )
    name = printed_name or supplied_name
    if not name:
        raise ValueError("Competition name is required: the source prints none")

    if supplied_start and supplied_end and supplied_end < supplied_start:
        raise ValueError(
            f"Supplied date range for {name} runs backwards: "
            f"{supplied_start} to {supplied_end}"
        )

    # Each endpoint is resolved on its own. A supplied *segment* range is a claim
    # about this sheet, so a disagreement is a conflict; a packaged (umbrella)
    # range is wider by nature, so the narrower printed segment range wins.
    if identity is not None and identity.scope == "segment":
        conflicts = []
        if printed_start and supplied_start and printed_start != supplied_start:
            conflicts.append(f"start: printed {printed_start}, supplied {supplied_start}")
        if printed_end and supplied_end and printed_end != supplied_end:
            conflicts.append(f"end: printed {printed_end}, supplied {supplied_end}")
        if conflicts:
            raise ValueError(
                f"Competition dates conflict for {name}: " + "; ".join(conflicts)
            )

    # A packaged (umbrella) range may be wider than a printed segment range, but
    # the segment still has to fall inside it: a range that excludes the printed
    # dates is a different contradiction, not a wider claim.
    if (
        identity is not None
        and identity.scope == "package"
        and identity.start_date
        and identity.end_date
        and printed_start
        and printed_end
        and not (
            identity.start_date <= printed_start and printed_end <= identity.end_date
        )
    ):
        raise ValueError(
            f"Competition dates conflict for {name}: printed "
            f"{printed_start} to {printed_end} falls outside the supplied package "
            f"range {identity.start_date} to {identity.end_date}"
        )

    start_date = printed_start or supplied_start
    end_date = printed_end or supplied_end
    if start_date and end_date and end_date < start_date:
        raise ValueError(
            f"Competition dates for {name} run backwards: {start_date} to {end_date}"
        )

    if printed_start and printed_end:
        return name, start_date, end_date, "printed"
    if supplied_start or supplied_end:
        return name, start_date, end_date, identity.source if identity else "operator"
    return name, None, None, "unknown"


def resolve_session_metadata(
    parsed: ParsedMeet, *, identity: CompetitionIdentity | None = None
) -> SessionResolution:
    """Resolve a session's race date without using report-generation time."""
    if parsed.metadata_conflicts:
        return SessionResolution(
            race_date=None,
            status="conflicting",
            diagnostics=tuple(parsed.metadata_conflicts),
        )

    # Day/session are optional metadata: a sheet that prints no such line still
    # contributes results, and its date range may come from the caller.
    if parsed.day_number is None or parsed.session_number is None:
        return SessionResolution(race_date=None, status="unknown")

    if parsed.day_number <= 0 or parsed.session_number <= 0:
        return SessionResolution(
            race_date=None,
            status="conflicting",
            diagnostics=("Day and session numbers must be positive",),
        )

    _, start_date, end_date, _ = resolve_segment_identity(parsed, identity)
    if start_date is None or end_date is None:
        return SessionResolution(race_date=None, status="unknown")

    race_date = start_date + timedelta(days=parsed.day_number - 1)
    if race_date < start_date or race_date > end_date:
        return SessionResolution(
            race_date=None,
            status="conflicting",
            diagnostics=(
                f"Day {parsed.day_number} is outside segment range "
                f"{start_date.isoformat()} to {end_date.isoformat()}",
            ),
        )

    return SessionResolution(race_date=race_date, status="derived")



def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _apply_segment_dates(
    segment: CompetitionSegment,
    *,
    name: str,
    start_date: date | None,
    end_date: date | None,
    source: str,
    resolved_at: datetime,
) -> None:
    incoming = (start_date, end_date)
    existing = (segment.startDate, segment.endDate)

    if incoming == (None, None):
        if existing == (None, None):
            segment.resolutionStatus = "unknown"
        return

    if None in incoming:
        raise ValueError(f"Incomplete date range for segment {name}")

    if existing != (None, None) and existing != incoming:
        segment.resolutionStatus = "conflicting"
        segment.resolverVersion = RESOLVER_VERSION
        segment.resolvedAt = resolved_at
        raise ValueError(
            f"Conflicting date range for segment {name}: "
            f"stored {existing[0]} to {existing[1]}, received {incoming[0]} to {incoming[1]}"
        )

    segment.startDate = start_date
    segment.endDate = end_date
    # Dates read off the page are verified; caller-supplied dates are recorded as
    # derived so the provenance of the range survives in the database.
    segment.resolutionStatus = "verified" if source == "printed" else "derived"
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


_EVENT_NAME_WHITESPACE = re.compile(r"\s+")


def _normalise_event_name(name: str) -> str:
    return _EVENT_NAME_WHITESPACE.sub(" ", name.strip()).casefold()


def overlap_key_for_document(parsed: ParsedMeet, segment_name: str) -> str:
    """Coarse signature of the *shape* of what a sheet contributes.

    Two sheets carrying the same segment, events, rounds and row counts are
    candidate reprints of one another. A heats/finals pair differs in round, so
    it does not collide; wording-only differences are normalised before hashing.
    This is deliberately coarse: it answers "do these two documents describe the
    same races", not "did this document change".
    """
    payload = json.dumps(
        {
            "segment": _normalise_event_name(segment_name),
            "events": [
                [
                    event.event_number,
                    _normalise_event_name(event.event_name),
                    event.time_type,
                    len(event.results),
                    len(event.relay_results),
                ]
                for event in parsed.events
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fingerprint_value(value: Any) -> Any:
    """Deterministically serialise parser output for change detection.

    Every branch is order- and run-stable: dataclass fields keep declaration
    order, mappings are sorted by the caller, sets are sorted by their own
    serialised form (so mixed types cannot raise), and an unrecognised object
    contributes its type name rather than a repr with a memory address - a
    pointer in the digest would make a clean rebuild look like a changed parse.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _fingerprint_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _fingerprint_value(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        serialised = [_fingerprint_value(item) for item in value]
        return sorted(
            serialised,
            key=lambda item: json.dumps(item, sort_keys=True, default=str),
        )
    if isinstance(value, (list, tuple)):
        return [_fingerprint_value(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return f"{type(value).__qualname__}.{value.name}"
    if isinstance(value, PurePath):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return f"<{type(value).__module__}.{type(value).__qualname__}>"


def evidence_key_for_document(parsed: ParsedMeet, segment_name: str) -> str:
    """Full fingerprint of the evidence a sheet carries.

    Unlike the overlap signature this covers every semantic field of the parse:
    numbering and label, and each row's athlete, team, times, status and splits.
    A rebuild that reuses a source document compares this fingerprint, so a
    changed parse - even one that keeps the same event numbers and row counts -
    is detected instead of silently accepted.
    """
    payload = json.dumps(
        {
            "segment": _normalise_event_name(segment_name),
            "parsed": _fingerprint_value(parsed),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _document_index(session: CompetitionSession) -> list[dict[str, Any]]:
    """Every document known to have fed a session."""
    if session.sourceDocuments:
        try:
            stored = json.loads(session.sourceDocuments)
        except ValueError:
            stored = None
        if isinstance(stored, list):
            return [
                {"sha": str(entry.get("sha")), "evidence": entry.get("evidence")}
                for entry in stored
                if isinstance(entry, dict) and entry.get("sha")
            ]
    # Rows written before the index column existed still know their first sheet.
    if session.sourceDocumentSha:
        return [
            {"sha": session.sourceDocumentSha, "evidence": session.sourceEvidenceKey}
        ]
    return []


def _record_document(
    session: CompetitionSession, sha: str | None, evidence_key: str | None
) -> None:
    """Record one document feeding this session, failing closed if it changed.

    A printed session can legitimately be fed by more than one curated sheet, so
    each contributor is tracked separately: a later changed parse of any one of
    them is a conflict, not a silent overwrite.
    """
    if not sha:
        return
    index = _document_index(session)
    for entry in index:
        if entry["sha"] != sha:
            continue
        if entry.get("evidence") and evidence_key and entry["evidence"] != evidence_key:
            raise ValueError(
                f"Source document {sha} now parses to different evidence than the "
                "stored session"
            )
        entry["evidence"] = evidence_key or entry.get("evidence")
        break
    else:
        index.append({"sha": sha, "evidence": evidence_key})
    session.sourceDocuments = json.dumps(
        sorted(index, key=lambda entry: entry["sha"]),
        sort_keys=True,
        separators=(",", ":"),
    )
    if session.sourceDocumentSha is None:
        session.sourceDocumentSha = sha
        session.sourceEvidenceKey = evidence_key


def _row_identity_text(row: Any, *names: str) -> str:
    """First non-empty attribute among ``names``, normalised."""
    for name in names:
        value = getattr(row, name, None)
        if value:
            return _normalise_event_name(str(value))
    return ""


def performance_signatures(
    parsed: ParsedMeet,
    segment_name: str,
    *,
    session_key: tuple[Any, ...] | None = None,
) -> dict[tuple[Any, ...], tuple[str, ...]]:
    """Map each performance's identity to its sorted row digests, per session.

    A document-shape hash answers "does this look like the same sheet"; it cannot
    see two sheets that overlap on one race and disagree about it. The identity is
    therefore scoped to the session the row belongs to: the same prelim result
    legitimately reprints on a later session's sheet, so only documents claiming
    the *same session*, event, round and athlete have to agree. An unnumbered
    sheet is its own session in this model, so it is keyed by its document - it
    can never collide with another document's rows.
    """
    segment = _normalise_event_name(segment_name)
    if session_key is None:
        session_key = (
            ("numbered", parsed.day_number, parsed.session_number)
            if parsed.day_number is not None and parsed.session_number is not None
            else ("document", None)
        )
    signatures: dict[tuple[Any, ...], list[str]] = {}
    for event in parsed.events:
        event_key = (
            segment,
            session_key,
            event.event_number,
            _normalise_event_name(event.event_name),
            event.time_type,
        )
        for row in event.results:
            identity = (
                event_key,
                "individual",
                _row_identity_text(row, "name"),
                _row_identity_text(row, "team"),
            )
            signatures.setdefault(identity, []).append(_row_digest(row))
        for relay in event.relay_results:
            identity = (
                event_key,
                "relay",
                _row_identity_text(relay, "team_name", "team", "name"),
                _row_identity_text(relay, "relay_letter"),
            )
            signatures.setdefault(identity, []).append(_row_digest(relay))
    return {
        identity: tuple(sorted(digests)) for identity, digests in signatures.items()
    }


def _row_digest(row: Any) -> str:
    payload = json.dumps(
        _fingerprint_value(row), sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_document_identity_payload(payload: object) -> dict[str, CompetitionIdentity]:
    """Build per-document identities from an operator-supplied JSON payload.

    Accepted shape::

        {"documents": [{"filename": "day-2-heats.pdf",
                        "segment_name": "20th SNSC 2025",
                        "start_date": "2025-05-31",
                        "end_date": "2025-06-03"}]}

    Each entry supplies identity only for the document it names; documents whose
    pages already print their identity need no entry and stay untouched.
    """
    if not isinstance(payload, dict):
        raise ValueError("Identity payload must be a JSON object")
    entries = payload.get("documents")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Identity payload needs a non-empty 'documents' list")

    identities: dict[str, CompetitionIdentity] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each identity entry must be a JSON object")
        filename = str(entry.get("filename") or "").strip()
        if not filename:
            raise ValueError("Each identity entry needs a 'filename'")
        if filename in identities:
            raise ValueError(f"Duplicate identity entry for {filename}")
        name = str(entry.get("segment_name") or "").strip()
        if not name:
            raise ValueError(f"Identity entry for {filename} needs a 'segment_name'")
        identities[filename] = CompetitionIdentity(
            title=name,
            start_date=_parse_optional_date(entry.get("start_date"), filename),
            end_date=_parse_optional_date(entry.get("end_date"), filename),
            source="operator",
            scope="segment",
        )
    return identities


def _parse_optional_date(value: object, filename: str) -> date | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"Identity dates for {filename} must be ISO strings")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(
            f"Identity dates for {filename} must be ISO dates (YYYY-MM-DD)"
        ) from exc


def upsert_competition_hierarchy(
    db: Session,
    *,
    source_key: str,
    competition_title: str,
    parsed: ParsedMeet,
    legacy_meet: Meet | None = None,
    source_event_id: int | None = None,
    identity: CompetitionIdentity | None = None,
    source_document_sha: str | None = None,
    evidence_key: str | None = None,
) -> CompetitionSession:
    """Create/reuse edition → segment → day → session for one parsed sheet.

    The umbrella identity must come from an authoritative source-page/manifest
    key supplied by the caller. This function never guesses it from segment
    names such as "Juniors" or "Seniors". Day/session headers are optional
    metadata: a sheet that prints none is still persisted, with a derived
    session number recorded as derived rather than verified.
    """
    canonical_source_key = canonicalize_url(source_key)
    title = competition_title.strip()
    segment_key, segment_start, segment_end, date_source = resolve_segment_identity(
        parsed, identity
    )
    if not canonical_source_key:
        raise ValueError("Competition source key is required")
    if not title:
        raise ValueError("Competition title is required")
    if not segment_key:
        raise ValueError("Competition name is required: the source prints none")
    if parsed.metadata_conflicts:
        raise ValueError("Cannot persist conflicting competition metadata")

    resolution = resolve_session_metadata(parsed, identity=identity)
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

    _apply_segment_dates(
        segment,
        name=segment_key,
        start_date=segment_start,
        end_date=segment_end,
        source=date_source,
        resolved_at=resolved_at,
    )
    _expand_edition_bounds(
        edition,
        segment_start=segment.startDate,
        segment_end=segment.endDate,
        resolved_at=resolved_at,
    )

    # Day/session are optional metadata. A sheet that prints them keeps exactly
    # what it printed; a sheet that prints none stores NULL numbering and is
    # identified by its source document, so a rebuild finds the same session
    # instead of picking a new surrogate number. Numbering is all-or-nothing:
    # a sheet that prints a day but no session (or a nonpositive number) is a
    # source defect, never an invitation to invent or discard a number.
    has_day_number = parsed.day_number is not None
    has_session_number = parsed.session_number is not None
    if has_day_number != has_session_number:
        raise ValueError(
            "Partial Day/Session metadata: the sheet must print both or neither"
        )
    if has_day_number and min(parsed.day_number or 0, parsed.session_number or 0) <= 0:
        raise ValueError("Day and session numbers must be positive")

    printed_numbering = has_day_number and has_session_number
    if not printed_numbering and not source_document_sha:
        raise ValueError(
            "A sheet without a Day N Session N header needs its source document "
            "identity to be persisted"
        )
    day_number = parsed.day_number if printed_numbering else None
    session_number = parsed.session_number if printed_numbering else None
    numbering_status = resolution.status if printed_numbering else "derived"

    if source_document_sha:
        # A session can be fed by several sheets, so a document that is not the
        # primary one is still found through the recorded index - otherwise its
        # stored fingerprint would never be re-checked.
        existing_session = (
            db.query(CompetitionSession)
            .filter(
                (CompetitionSession.sourceDocumentSha == source_document_sha)
                | CompetitionSession.sourceDocuments.like(
                    f'%"{source_document_sha}"%'
                )
            )
            .first()
        )
        if existing_session is not None:
            if existing_session.day.competitionSegmentId != segment.id:
                raise ValueError(
                    f"Source document {source_document_sha} is already bound to "
                    "another segment"
                )
            if (
                existing_session.sessionNumber != session_number
                or existing_session.day.dayNumber != day_number
            ):
                raise ValueError(
                    f"Source document {source_document_sha} was stored as "
                    f"day {existing_session.day.dayNumber} session "
                    f"{existing_session.sessionNumber} and now claims day "
                    f"{day_number} session {session_number}"
                )
            if (
                evidence_key
                and existing_session.sourceEvidenceKey
                and existing_session.sourceEvidenceKey != evidence_key
            ):
                raise ValueError(
                    f"Source document {source_document_sha} now parses to different "
                    "evidence than the stored session"
                )
            _record_document(existing_session, source_document_sha, evidence_key)
            existing_session.label = parsed.session
            existing_session.resolutionStatus = numbering_status
            existing_session.resolverVersion = RESOLVER_VERSION
            existing_session.resolvedAt = resolved_at
            return existing_session

    day = db.query(CompetitionDay).filter(
        CompetitionDay.competitionSegmentId == segment.id,
        (
            CompetitionDay.dayNumber.is_(None)
            if day_number is None
            else CompetitionDay.dayNumber == day_number
        ),
    ).first()
    if day is None:
        day = CompetitionDay(
            competitionSegmentId=segment.id,
            dayNumber=day_number,
            date=resolution.race_date,
            resolutionStatus=numbering_status,
            resolverVersion=RESOLVER_VERSION,
            resolvedAt=resolved_at,
        )
        db.add(day)
        db.flush()
    elif day.date not in {None, resolution.race_date}:
        day.resolutionStatus = "conflicting"
        raise ValueError(
            f"Day {day_number} has conflicting dates: "
            f"stored {day.date}, received {resolution.race_date}"
        )
    elif day.date is None and resolution.race_date is not None:
        day.date = resolution.race_date
        day.resolutionStatus = numbering_status
        day.resolverVersion = RESOLVER_VERSION
        day.resolvedAt = resolved_at

    if not printed_numbering:
        # An unnumbered sheet is its own session: the document identity, not the
        # (day, NULL) pair, is what a later rebuild matches on. Two unnumbered
        # sheets therefore stay two sessions regardless of their import order.
        competition_session = CompetitionSession(
            competitionDayId=day.id,
            sessionNumber=None,
            sourceDocumentSha=source_document_sha,
            sourceEvidenceKey=evidence_key,
            label=parsed.session,
            resolutionStatus=numbering_status,
            resolverVersion=RESOLVER_VERSION,
            resolvedAt=resolved_at,
        )
        db.add(competition_session)
        db.flush()
        _record_document(competition_session, source_document_sha, evidence_key)
        return competition_session

    competition_session = db.query(CompetitionSession).filter(
        CompetitionSession.competitionDayId == day.id,
        CompetitionSession.sessionNumber == session_number,
    ).first()
    if competition_session is None:
        competition_session = CompetitionSession(
            competitionDayId=day.id,
            sessionNumber=session_number,
            sourceDocumentSha=source_document_sha,
            sourceEvidenceKey=evidence_key,
            label=parsed.session,
            resolutionStatus=numbering_status,
            resolverVersion=RESOLVER_VERSION,
            resolvedAt=resolved_at,
        )
        db.add(competition_session)
        db.flush()
        _record_document(competition_session, source_document_sha, evidence_key)
        return competition_session

    # A printed session may legitimately be fed by more than one curated sheet, so
    # a second document does not take over the row. Every contributor is recorded
    # and re-checked, so a changed parse of any of them is still caught.
    _record_document(competition_session, source_document_sha, evidence_key)
    if (
        competition_session.resolutionStatus != numbering_status
        or competition_session.label != parsed.session
        or competition_session.resolverVersion != RESOLVER_VERSION
    ):
        competition_session.label = parsed.session
        competition_session.resolutionStatus = numbering_status
        competition_session.resolverVersion = RESOLVER_VERSION
        competition_session.resolvedAt = resolved_at

    return competition_session
