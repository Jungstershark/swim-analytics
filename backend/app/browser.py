"""Browser read models for longitudinal swim result browsing.

These helpers intentionally build v0 display/read models from the current raw
meet/result schema. The project does not yet have normalized Session or
MeetEvent tables, so event keys and round/date groupings are marked as derived
contracts rather than authoritative domain objects.
"""

from __future__ import annotations

import math
import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import case, distinct, func, or_, select, union_all
from sqlalchemy.orm import Session, joinedload

from .models import AthleteProfile, Meet, RawDocument, RelayLeg, RelayResult, Result, SourceReference, Swimmer
from .parsers.hytek import time_to_seconds


_SUSPICIOUS_NAME_FRAGMENTS = (
    "lc meter",
    "event",
    "preliminaries",
    "finals",
    "seed time",
    "prelim time",
    "finals time",
    "mts",
    "qmts",
    "dns",
    "dq",
    # Exact artifact found in persisted source data. Keeping this in the shared
    # fragment contract makes Python projection and SQL filtering agree.
    "r1:02.53",
)


def display_date(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%Y-%m-%d")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "unknown"


def make_event_key(meet_id: int, event: str, source_event_number: str | None = None) -> str:
    """Stable v0 event-group key for direct links.

    Prefer source event number where present, but keep the raw event label in the
    composite to avoid collisions across individual/relay or malformed source
    numbers. This is a display/read-model key, not a normalized MeetEvent ID.
    """
    parts = [f"meet-{meet_id}"]
    if source_event_number:
        parts.append(f"src-{slugify(str(source_event_number))}")
    parts.append(slugify(event))
    return "-".join(parts)


def canonical_individual_event(event: str) -> dict[str, str | int | None]:
    """Derive a course-separated individual-event identity from source text.

    The source label remains authoritative and is still returned on each
    performance row. This derived key exists only for longitudinal browsing;
    ambiguous labels stay visibly unknown instead of being coerced.
    """
    course_match = re.search(r"\b(LC|SC)\s+Meter\b", event, re.IGNORECASE)
    distance_match = re.search(r"\b(\d+)\s+(?:LC|SC)\s+Meter\b", event, re.IGNORECASE)
    course = {"LC": "LCM", "SC": "SCM"}.get(course_match.group(1).upper()) if course_match else None

    stroke = None
    stroke_patterns = (
        (r"\b(?:Individual Medley|IM)\b", "Individual Medley"),
        (r"\bFreestyle\b", "Freestyle"),
        (r"\bBackstroke\b", "Backstroke"),
        (r"\bBreaststroke\b", "Breaststroke"),
        (r"\bButterfly\b", "Butterfly"),
    )
    for pattern, label in stroke_patterns:
        if re.search(pattern, event, re.IGNORECASE):
            stroke = label
            break

    distance = int(distance_match.group(1)) if distance_match else None
    if course and distance and stroke and "Relay" not in event:
        label = f"{distance} {stroke}"
        return {
            "course": course,
            "distance_m": distance,
            "stroke": stroke,
            "event": label,
            "canonical_event_key": f"{course.lower()}-{distance}-{slugify(stroke)}",
            "normalization_status": "derived_from_source_label",
        }
    return {
        "course": "Unknown",
        "distance_m": distance,
        "stroke": stroke,
        "event": event,
        "canonical_event_key": f"unknown-{slugify(event)}",
        "normalization_status": "raw_event_string",
    }


def parsed_splits(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [split for split in parsed if isinstance(split, dict)]


def _is_suspicious_name(name: str | None) -> bool:
    value = name or ""
    normalized_name = value.casefold()
    return len(value) > 90 or any(
        fragment in normalized_name for fragment in _SUSPICIOUS_NAME_FRAGMENTS
    )


def suspicious_name_warnings(swimmer: Swimmer | None, *, sample_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if swimmer is None:
        return []
    name = swimmer.name or ""
    if not _is_suspicious_name(name):
        return []
    return [
        {
            "type": "suspicious_swimmer_name",
            "severity": "warning",
            "entity_kind": "swimmer",
            "entity_id": swimmer.id,
            "message": "Swimmer name contains timing/event-like artifacts.",
            "count": 1,
            "sample_rows": sample_rows or [],
            "source_fields": ["Swimmer.name"],
        }
    ]


def source_warning(entity_kind: str, entity_id: int, source_document_sha256: str | None, parse_job_id: int | None) -> list[dict[str, Any]]:
    if source_document_sha256 and parse_job_id:
        return []
    return [
        {
            "type": "missing_result_source",
            "severity": "warning",
            "entity_kind": entity_kind,
            "entity_id": entity_id,
            "message": "The official source is not linked to this result.",
            "count": 1,
            "sample_rows": [{f"{entity_kind}_id": entity_id}],
            "source_fields": ["sourceDocumentSha256", "parseJobId"],
        }
    ]


def no_time_warning(
    entity_kind: str,
    entity_id: int,
    is_dq: bool,
    time: str | None,
    status: str = "unknown",
) -> list[dict[str, Any]]:
    if is_dq or status in {"dq", "ns", "dns", "dnf", "scratched"} or time_to_seconds(time or "") is not None:
        return []
    return [
        {
            "type": "no_time_result",
            "severity": "info",
            "entity_kind": entity_kind,
            "entity_id": entity_id,
            "message": "This result does not include a valid recorded time.",
            "count": 1,
            "sample_rows": [{f"{entity_kind}_id": entity_id}],
            "source_fields": ["time", "isDQ", "resultStatus"],
        }
    ]


def meet_brief(meet: Meet | None) -> dict[str, Any] | None:
    if meet is None:
        return None
    return {
        "id": meet.id,
        "name": meet.name,
        "date": display_date(meet.startDate),
        "end_date": display_date(meet.endDate),
        "location": meet.location,
    }


def swimmer_brief(swimmer: Swimmer | None) -> dict[str, Any] | None:
    if swimmer is None:
        return None
    return {
        "id": swimmer.id,
        "name": swimmer.name,
        "age": swimmer.age,
        "team": swimmer.team,
    }


def athlete_profile_brief(profile: AthleteProfile, ages: Iterable[int | None]) -> dict[str, Any]:
    """Browser-facing athlete identity while result rows keep their source age."""
    return {
        "athlete_profile_id": profile.id,
        "source_swimmer_id": None,
        "name": profile.name,
        "team": profile.team,
        "ages": sorted({age for age in ages if age is not None}),
        "identity_status": "derived_name_and_club",
    }


def pagination(page: int, limit: int, total: int) -> dict[str, int]:
    return {
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": math.ceil(total / limit) if limit else 0,
    }


def event_group_payload(
    meet_id: int,
    event: str,
    source_event_number: str | None,
    individual_count: int = 0,
    relay_count: int = 0,
    rounds: Iterable[str | None] = (),
    swim_dates: Iterable[datetime | None] = (),
) -> dict[str, Any]:
    return {
        "event_key": make_event_key(meet_id, event, source_event_number),
        "meet_id": meet_id,
        "source_event_number": source_event_number,
        "event_label": event,
        "normalization_status": "raw_event_string",
        "derived": True,
        "rounds": sorted({r for r in rounds if r}),
        "swim_dates": sorted({d for d in (display_date(value) for value in swim_dates if value) if d}),
        "individual_count": individual_count,
        "relay_count": relay_count,
        "total_rows": individual_count + relay_count,
    }


def list_browser_athletes(
    db: Session,
    *,
    page: int = 1,
    limit: int = 50,
    q: str | None = None,
    team: str | None = None,
    min_results: int | None = None,
    has_warnings: bool | None = None,
    sort: str = "name",
    order: str = "asc",
) -> dict[str, Any]:
    """List athlete profiles with source-row counts in a bounded query set."""
    individual_counts = (
        db.query(
            Swimmer.athleteProfileId.label("profile_id"),
            func.count(Result.id).label("individual_result_count"),
        )
        .join(Result, Result.swimmerId == Swimmer.id)
        .filter(Swimmer.athleteProfileId.isnot(None))
        .group_by(Swimmer.athleteProfileId)
        .subquery()
    )
    relay_counts = (
        db.query(
            Swimmer.athleteProfileId.label("profile_id"),
            func.count(distinct(RelayResult.id)).label("relay_result_count"),
        )
        .join(RelayLeg, RelayLeg.swimmerId == Swimmer.id)
        .join(RelayResult, RelayResult.id == RelayLeg.relayResultId)
        .filter(Swimmer.athleteProfileId.isnot(None))
        .group_by(Swimmer.athleteProfileId)
        .subquery()
    )
    participation = union_all(
        select(
            Swimmer.athleteProfileId.label("profile_id"),
            Result.meetId.label("meet_id"),
            Result.event.label("event"),
        ).join(Result, Result.swimmerId == Swimmer.id).where(Swimmer.athleteProfileId.isnot(None)),
        select(
            Swimmer.athleteProfileId.label("profile_id"),
            RelayResult.meetId.label("meet_id"),
            RelayResult.event.label("event"),
        ).join(RelayLeg, RelayLeg.swimmerId == Swimmer.id).join(
            RelayResult, RelayResult.id == RelayLeg.relayResultId
        ).where(Swimmer.athleteProfileId.isnot(None)),
    ).subquery()
    combined_counts = (
        db.query(
            participation.c.profile_id,
            func.count(distinct(participation.c.meet_id)).label("meet_count"),
            func.count(distinct(participation.c.event)).label("event_count"),
            func.max(Meet.startDate).label("latest_date"),
        )
        .join(Meet, Meet.id == participation.c.meet_id)
        .group_by(participation.c.profile_id)
        .subquery()
    )
    warning_profile_ids = (
        db.query(Swimmer.athleteProfileId)
        .filter(Swimmer.athleteProfileId.isnot(None), _suspicious_name_sql_expr(Swimmer.name))
        .distinct()
        .subquery()
    )

    query = db.query(
        AthleteProfile,
        individual_counts.c.individual_result_count,
        combined_counts.c.meet_count,
        combined_counts.c.event_count,
        combined_counts.c.latest_date,
        relay_counts.c.relay_result_count,
    ).outerjoin(
        individual_counts, individual_counts.c.profile_id == AthleteProfile.id
    ).outerjoin(
        combined_counts, combined_counts.c.profile_id == AthleteProfile.id
    ).outerjoin(relay_counts, relay_counts.c.profile_id == AthleteProfile.id)

    if q:
        query = query.filter(AthleteProfile.name.ilike(f"%{q}%"))
    if team:
        query = query.filter(AthleteProfile.team.ilike(f"%{team}%"))
    if min_results is not None:
        query = query.filter(func.coalesce(individual_counts.c.individual_result_count, 0) >= min_results)
    if has_warnings is not None:
        warning_ids = select(warning_profile_ids.c.athleteProfileId)
        query = query.filter(AthleteProfile.id.in_(warning_ids) if has_warnings else ~AthleteProfile.id.in_(warning_ids))

    rows = query.all()
    profile_ids = [profile.id for profile, *_counts in rows]

    source_rows_by_profile: dict[int, list[Swimmer]] = defaultdict(list)
    if profile_ids:
        for swimmer in db.query(Swimmer).filter(Swimmer.athleteProfileId.in_(profile_ids)).all():
            source_rows_by_profile[swimmer.athleteProfileId].append(swimmer)

    latest_meets_by_profile: dict[int, dict[str, Any]] = {}
    if profile_ids:
        latest_rows = (
            db.query(participation.c.profile_id, Meet)
            .join(Meet, Meet.id == participation.c.meet_id)
            .filter(participation.c.profile_id.in_(profile_ids))
            .order_by(participation.c.profile_id, Meet.startDate.desc(), Meet.id.desc())
            .all()
        )
        for profile_id, meet in latest_rows:
            latest_meet = meet_brief(meet)
            if latest_meet is not None:
                latest_meets_by_profile.setdefault(profile_id, latest_meet)

    cards = []
    for profile, individual_count, meet_count, event_count, _latest_date, relay_count in rows:
        source_rows = source_rows_by_profile.get(profile.id, [])
        warnings = [warning for swimmer in source_rows for warning in suspicious_name_warnings(swimmer)]
        cards.append({
            **athlete_profile_brief(profile, (swimmer.age for swimmer in source_rows)),
            "individual_result_count": int(individual_count or 0),
            "relay_result_count": int(relay_count or 0),
            "meet_count": int(meet_count or 0),
            "event_count": int(event_count or 0),
            "latest_meet": latest_meets_by_profile.get(profile.id),
            "warning_count": len(warnings),
            "warnings": warnings,
        })

    # A missing/ambiguous club must not be silently turned into a person-level
    # profile. Keep those source rows visible as explicit ungrouped cards.
    unlinked_ids = {
        swimmer_id for (swimmer_id,) in db.query(Swimmer.id)
        .filter(Swimmer.athleteProfileId.is_(None)).all()
    }
    if unlinked_ids:
        source_cards = list_browser_swimmers(
            db, page=1, limit=100000, q=q, team=team,
            min_results=min_results, has_warnings=has_warnings, sort=sort, order=order,
        )["data"]
        for source in source_cards:
            if source["id"] not in unlinked_ids:
                continue
            cards.append({
                "athlete_profile_id": None,
                "source_swimmer_id": source["id"],
                "name": source["name"],
                "team": source["team"] or "No team",
                "ages": [source["age"]] if source["age"] is not None else [],
                "identity_status": "source_row_unlinked",
                "individual_result_count": source["individual_result_count"],
                "relay_result_count": source["relay_result_count"],
                "meet_count": source["meet_count"],
                "event_count": source["event_count"],
                "latest_meet": source["latest_meet"],
                "warning_count": source["warning_count"],
                "warnings": source["warnings"],
            })

    def sort_value(card: dict[str, Any]) -> Any:
        if sort == "team":
            return card["team"].casefold()
        if sort == "result_count":
            return card["individual_result_count"]
        if sort == "latest_meet":
            return (card["latest_meet"] or {}).get("date") or ""
        return card["name"].casefold()

    cards.sort(key=lambda card: (sort_value(card), card["name"].casefold()), reverse=order == "desc")
    total = len(cards)
    start = (page - 1) * limit
    return {"data": cards[start : start + limit], "pagination": pagination(page, limit, total)}


def list_browser_swimmers(
    db: Session,
    *,
    page: int = 1,
    limit: int = 50,
    q: str | None = None,
    team: str | None = None,
    min_results: int | None = None,
    has_warnings: bool | None = None,
    sort: str = "name",
    order: str = "asc",
) -> dict[str, Any]:
    """Legacy source-swimmer catalogue; IDs always remain ``Swimmer.id``."""
    individual_counts = (
        db.query(Result.swimmerId.label("swimmer_id"), func.count(Result.id).label("individual_result_count"))
        .group_by(Result.swimmerId)
        .subquery()
    )
    relay_counts = (
        db.query(RelayLeg.swimmerId.label("swimmer_id"), func.count(distinct(RelayResult.id)).label("relay_result_count"))
        .join(RelayResult, RelayResult.id == RelayLeg.relayResultId)
        .filter(RelayLeg.swimmerId.isnot(None))
        .group_by(RelayLeg.swimmerId)
        .subquery()
    )
    participation = union_all(
        select(Result.swimmerId.label("swimmer_id"), Result.meetId.label("meet_id"), Result.event.label("event")),
        select(RelayLeg.swimmerId.label("swimmer_id"), RelayResult.meetId.label("meet_id"), RelayResult.event.label("event"))
        .join(RelayResult, RelayResult.id == RelayLeg.relayResultId)
        .where(RelayLeg.swimmerId.isnot(None)),
    ).subquery()
    combined_counts = (
        db.query(
            participation.c.swimmer_id,
            func.count(distinct(participation.c.meet_id)).label("meet_count"),
            func.count(distinct(participation.c.event)).label("event_count"),
            func.max(Meet.startDate).label("latest_date"),
        )
        .join(Meet, Meet.id == participation.c.meet_id)
        .group_by(participation.c.swimmer_id)
        .subquery()
    )
    query = db.query(
        Swimmer,
        individual_counts.c.individual_result_count,
        combined_counts.c.meet_count,
        combined_counts.c.event_count,
        combined_counts.c.latest_date,
        relay_counts.c.relay_result_count,
    ).outerjoin(
        individual_counts, individual_counts.c.swimmer_id == Swimmer.id
    ).outerjoin(
        combined_counts, combined_counts.c.swimmer_id == Swimmer.id
    ).outerjoin(relay_counts, relay_counts.c.swimmer_id == Swimmer.id)
    if q:
        query = query.filter(Swimmer.name.ilike(f"%{q}%"))
    if team:
        query = query.filter(Swimmer.team.ilike(f"%{team}%"))
    if min_results is not None:
        query = query.filter(func.coalesce(individual_counts.c.individual_result_count, 0) >= min_results)
    if has_warnings is not None:
        suspicious_expr = _suspicious_name_sql_expr(Swimmer.name)
        query = query.filter(suspicious_expr if has_warnings else ~suspicious_expr)
    total = query.count()
    sort_map = {
        "name": Swimmer.name,
        "team": Swimmer.team,
        "result_count": func.coalesce(individual_counts.c.individual_result_count, 0),
        "latest_meet": combined_counts.c.latest_date,
    }
    sort_col = sort_map.get(sort, Swimmer.name)
    query = query.order_by(sort_col.desc().nullslast() if order == "desc" else sort_col.asc().nullslast())
    rows = query.offset((page - 1) * limit).limit(limit).all()
    swimmer_ids = [swimmer.id for swimmer, *_counts in rows]
    latest_meets: dict[int, dict[str, Any]] = {}
    if swimmer_ids:
        for swimmer_id, meet in (
            db.query(participation.c.swimmer_id, Meet)
            .join(Meet, Meet.id == participation.c.meet_id)
            .filter(participation.c.swimmer_id.in_(swimmer_ids))
            .order_by(participation.c.swimmer_id, Meet.startDate.desc(), Meet.id.desc())
            .all()
        ):
            if (brief := meet_brief(meet)) is not None:
                latest_meets.setdefault(swimmer_id, brief)
    data = []
    for swimmer, individual_count, meet_count, event_count, _latest_date, relay_count in rows:
        warnings = suspicious_name_warnings(swimmer)
        data.append({
            "id": swimmer.id,
            "name": swimmer.name,
            "age": swimmer.age,
            "team": swimmer.team,
            "individual_result_count": int(individual_count or 0),
            "relay_result_count": int(relay_count or 0),
            "meet_count": int(meet_count or 0),
            "event_count": int(event_count or 0),
            "latest_meet": latest_meets.get(swimmer.id),
            "warning_count": len(warnings),
            "warnings": warnings,
        })
    return {"data": data, "pagination": pagination(page, limit, total)}


def list_browser_meets(
    db: Session,
    *,
    page: int = 1,
    limit: int = 50,
    q: str | None = None,
    sort: str = "date",
    order: str = "desc",
) -> dict[str, Any]:
    """List meets with individual/relay aggregates in a constant query count."""
    event_keys = union_all(
        select(
            Result.meetId.label("meet_id"),
            Result.sourceEventNumber.label("source_event_number"),
            Result.event.label("event"),
        ),
        select(
            RelayResult.meetId.label("meet_id"),
            RelayResult.sourceEventNumber.label("source_event_number"),
            RelayResult.event.label("event"),
        ),
    ).subquery()
    distinct_event_keys = (
        select(
            event_keys.c.meet_id,
            event_keys.c.source_event_number,
            event_keys.c.event,
        )
        .distinct()
        .subquery()
    )
    event_counts = (
        db.query(
            distinct_event_keys.c.meet_id,
            func.count().label("event_group_count"),
        )
        .group_by(distinct_event_keys.c.meet_id)
        .subquery()
    )
    individual_counts = (
        db.query(
            Result.meetId.label("meet_id"),
            func.count(Result.id).label("result_count"),
            func.sum(
                case(
                    (or_(Result.sourceDocumentSha256.is_(None), Result.parseJobId.is_(None)), 1),
                    else_=0,
                )
            ).label("missing_source_count"),
        )
        .group_by(Result.meetId)
        .subquery()
    )
    relay_counts = (
        db.query(
            RelayResult.meetId.label("meet_id"),
            func.count(RelayResult.id).label("result_count"),
            func.sum(
                case(
                    (or_(RelayResult.sourceDocumentSha256.is_(None), RelayResult.parseJobId.is_(None)), 1),
                    else_=0,
                )
            ).label("missing_source_count"),
        )
        .group_by(RelayResult.meetId)
        .subquery()
    )

    query = (
        db.query(
            Meet,
            event_counts.c.event_group_count,
            individual_counts.c.result_count,
            relay_counts.c.result_count,
            individual_counts.c.missing_source_count,
            relay_counts.c.missing_source_count,
        )
        .outerjoin(event_counts, event_counts.c.meet_id == Meet.id)
        .outerjoin(individual_counts, individual_counts.c.meet_id == Meet.id)
        .outerjoin(relay_counts, relay_counts.c.meet_id == Meet.id)
    )
    if q:
        query = query.filter(Meet.name.ilike(f"%{q}%"))

    total = query.count()
    sort_col = Meet.startDate if sort == "date" else Meet.name
    primary_order = sort_col.desc().nullslast() if order == "desc" else sort_col.asc().nullslast()
    rows = query.order_by(primary_order, Meet.id.asc()).offset((page - 1) * limit).limit(limit).all()

    data = []
    for meet, event_count, individual_count, relay_count, missing_individual, missing_relay in rows:
        individual_count = int(individual_count or 0)
        relay_count = int(relay_count or 0)
        data.append({
            **meet_brief(meet),
            "event_group_count": int(event_count or 0),
            "individual_result_count": individual_count,
            "relay_result_count": relay_count,
            "total_rows": individual_count + relay_count,
            "missing_source_count": int(missing_individual or 0) + int(missing_relay or 0),
        })
    return {"data": data, "pagination": pagination(page, limit, total)}


def browser_overview(db: Session) -> dict[str, Any]:
    top_events = (
        db.query(Result.event, func.count(Result.id).label("count"))
        .group_by(Result.event)
        .order_by(func.count(Result.id).desc())
        .limit(10)
        .all()
    )
    latest_meets = db.query(Meet).order_by(Meet.startDate.desc()).limit(5).all()
    missing_individual = db.query(func.count(Result.id)).filter(or_(Result.sourceDocumentSha256.is_(None), Result.parseJobId.is_(None))).scalar() or 0
    missing_relay = db.query(func.count(RelayResult.id)).filter(or_(RelayResult.sourceDocumentSha256.is_(None), RelayResult.parseJobId.is_(None))).scalar() or 0
    return {
        "counts": {
            "meets": db.query(Meet).count(),
            "swimmers": (
                db.query(AthleteProfile).count()
                + db.query(Swimmer).filter(Swimmer.athleteProfileId.is_(None)).count()
            ),
            "individual_results": db.query(Result).count(),
            "relay_results": db.query(RelayResult).count(),
            "raw_documents": db.query(RawDocument).count(),
            "source_references": db.query(SourceReference).count(),
        },
        "latest_meets": [meet_brief(m) for m in latest_meets],
        "top_events": [{"event_label": event, "individual_count": count} for event, count in top_events],
        "source_summary": {
            "missing_individual_result_source_count": missing_individual,
            "missing_relay_result_source_count": missing_relay,
        },
    }


def browser_meet(db: Session, meet_id: int) -> dict[str, Any] | None:
    meet = db.query(Meet).filter(Meet.id == meet_id).first()
    if meet is None:
        return None

    groups: dict[tuple[str | None, str], dict[str, Any]] = {}
    ind_rows = (
        db.query(
            Result.sourceEventNumber,
            Result.event,
            func.count(Result.id),
            func.count(distinct(Result.round)),
            func.min(Result.swimDate),
            func.max(Result.swimDate),
        )
        .filter(Result.meetId == meet_id)
        .group_by(Result.sourceEventNumber, Result.event)
        .all()
    )
    relay_rows = (
        db.query(
            RelayResult.sourceEventNumber,
            RelayResult.event,
            func.count(RelayResult.id),
            func.count(distinct(RelayResult.round)),
            func.min(RelayResult.swimDate),
            func.max(RelayResult.swimDate),
        )
        .filter(RelayResult.meetId == meet_id)
        .group_by(RelayResult.sourceEventNumber, RelayResult.event)
        .all()
    )

    for source_no, event, count, _round_count, min_date, max_date in ind_rows:
        groups[(source_no, event)] = event_group_payload(
            meet_id, event, source_no, individual_count=count, relay_count=0, swim_dates=[min_date, max_date]
        )
    for source_no, event, count, _round_count, min_date, max_date in relay_rows:
        key = (source_no, event)
        if key not in groups:
            groups[key] = event_group_payload(meet_id, event, source_no, swim_dates=[min_date, max_date])
        groups[key]["relay_count"] = count
        groups[key]["total_rows"] = groups[key]["individual_count"] + count
        groups[key]["swim_dates"] = sorted(set(groups[key]["swim_dates"]) | {d for d in [display_date(min_date), display_date(max_date)] if d})

    # Fill round labels in one pass per result table.
    for source_no, event, rnd in db.query(Result.sourceEventNumber, Result.event, Result.round).filter(Result.meetId == meet_id).distinct():
        if rnd and (source_no, event) in groups:
            groups[(source_no, event)].setdefault("rounds", [])
            if rnd not in groups[(source_no, event)]["rounds"]:
                groups[(source_no, event)]["rounds"].append(rnd)
    for source_no, event, rnd in db.query(RelayResult.sourceEventNumber, RelayResult.event, RelayResult.round).filter(RelayResult.meetId == meet_id).distinct():
        if rnd and (source_no, event) in groups:
            groups[(source_no, event)].setdefault("rounds", [])
            if rnd not in groups[(source_no, event)]["rounds"]:
                groups[(source_no, event)]["rounds"].append(rnd)

    event_groups = sorted(groups.values(), key=lambda g: (_source_no_sort(g["source_event_number"]), g["event_label"]))
    missing_source = (db.query(func.count(Result.id)).filter(Result.meetId == meet_id, or_(Result.sourceDocumentSha256.is_(None), Result.parseJobId.is_(None))).scalar() or 0) + (
        db.query(func.count(RelayResult.id)).filter(RelayResult.meetId == meet_id, or_(RelayResult.sourceDocumentSha256.is_(None), RelayResult.parseJobId.is_(None))).scalar() or 0
    )
    return {
        "meet": meet_brief(meet),
        "event_groups": event_groups,
        "summary": {
            "event_group_count": len(event_groups),
            "individual_result_count": sum(g["individual_count"] for g in event_groups),
            "relay_result_count": sum(g["relay_count"] for g in event_groups),
            "total_rows": sum(g["total_rows"] for g in event_groups),
        },
        "source_summary": {"missing_source_count": missing_source},
        "warnings": [],
    }


def browser_event(
    db: Session,
    *,
    meet_id: int,
    event_key: str,
    page: int = 1,
    limit: int = 50,
    round_name: str | None = None,
    row_type: str = "all",
    order: str = "place",
) -> dict[str, Any] | None:
    meet_payload = browser_meet(db, meet_id)
    if meet_payload is None:
        return None
    event_group = next((g for g in meet_payload["event_groups"] if g["event_key"] == event_key), None)
    if event_group is None:
        return {"event_group": None, "data": [], "pagination": pagination(page, limit, 0), "warnings": [{"type": "event_key_not_found", "severity": "warning", "message": "This event was not found for the meet."}]}

    individual_rows = []
    relay_rows = []
    if row_type in {"all", "individual"}:
        q = db.query(Result).options(joinedload(Result.swimmer), joinedload(Result.meet)).filter(
            Result.meetId == meet_id,
            Result.event == event_group["event_label"],
        )
        if event_group["source_event_number"] is not None:
            q = q.filter(Result.sourceEventNumber == event_group["source_event_number"])
        if round_name:
            q = q.filter(Result.round == round_name)
        individual_rows = q.all()
    if row_type in {"all", "relay"}:
        q = db.query(RelayResult).options(joinedload(RelayResult.legs).joinedload(RelayLeg.swimmer), joinedload(RelayResult.meet)).filter(
            RelayResult.meetId == meet_id,
            RelayResult.event == event_group["event_label"],
        )
        if event_group["source_event_number"] is not None:
            q = q.filter(RelayResult.sourceEventNumber == event_group["source_event_number"])
        if round_name:
            q = q.filter(RelayResult.round == round_name)
        relay_rows = q.all()

    rows = [_individual_event_row(r) for r in individual_rows] + [_relay_event_row(rr) for rr in relay_rows]
    rows = _sort_event_rows(rows, order)
    total = len(rows)
    start = (page - 1) * limit
    return {"event_group": event_group, "data": rows[start : start + limit], "pagination": pagination(page, limit, total), "warnings": []}


def browser_athlete_profile_detail(
    db: Session,
    athlete_profile_id: int | None = None,
    *,
    source_swimmer: Swimmer | None = None,
) -> dict[str, Any] | None:
    """Return a combined profile, or preserve one unlinked source-row detail."""
    is_unlinked_source = source_swimmer is not None
    if source_swimmer is not None:
        # This transient projection preserves old links for ambiguous source rows
        # without creating or claiming an athlete profile for them.
        profile = AthleteProfile(
            id=source_swimmer.id,
            name=source_swimmer.name,
            nameKey=source_swimmer.nameKey or "source",
            team=source_swimmer.team or "No team",
            teamKey=source_swimmer.teamKey or "source",
        )
        swimmers = [source_swimmer]
    else:
        if athlete_profile_id is None:
            return None
        profile = db.query(AthleteProfile).filter(AthleteProfile.id == athlete_profile_id).first()
        if profile is None:
            return None
        swimmers = db.query(Swimmer).filter(Swimmer.athleteProfileId == profile.id).all()
    swimmer_ids = [swimmer.id for swimmer in swimmers]
    results = (
        db.query(Result)
        .options(joinedload(Result.meet), joinedload(Result.swimmer))
        .filter(Result.swimmerId.in_(swimmer_ids))
        .all()
    ) if swimmer_ids else []
    relays = (
        db.query(RelayResult)
        .options(joinedload(RelayResult.meet), joinedload(RelayResult.legs).joinedload(RelayLeg.swimmer))
        .join(RelayLeg)
        .filter(RelayLeg.swimmerId.in_(swimmer_ids))
        .distinct()
        .all()
    ) if swimmer_ids else []

    pbs = []
    by_event: dict[str, tuple[Result, float]] = {}
    for r in results:
        if r.isDQ or r.resultStatus != "finished":
            continue
        seconds = time_to_seconds(r.time or "")
        if seconds is None:
            continue
        if r.event not in by_event or seconds < by_event[r.event][1]:
            by_event[r.event] = (r, seconds)
    for event, (r, seconds) in sorted(by_event.items()):
        pbs.append({"event": event, "time": r.time, "time_in_seconds": seconds, "meet": meet_brief(r.meet), "date": display_date(r.swimDate or r.meet.startDate), "round": r.round})

    event_history = []
    for event in sorted({r.event for r in results}):
        event_results = sorted([r for r in results if r.event == event], key=lambda r: r.swimDate or r.meet.startDate)
        first = event_results[0]
        event_key = make_event_key(first.meetId, first.event, first.sourceEventNumber)
        event_history.append({
            "event": event,
            "event_key": event_key,
            "derived": True,
            "normalization_status": "raw_event_string",
            "result_count": len(event_results),
            "results": [_individual_event_row(r) for r in event_results],
        })

    canonical_groups: dict[tuple[str, str], dict[str, Any]] = {}
    for result in results:
        dimensions = canonical_individual_event(result.event)
        group_key = (str(dimensions["course"]), str(dimensions["canonical_event_key"]))
        group = canonical_groups.setdefault(group_key, {**dimensions, "source_event_labels": set(), "results": []})
        group["source_event_labels"].add(result.event)
        group["results"].append(result)

    course_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (_course, _event_key), group in canonical_groups.items():
        event_results = sorted(
            group.pop("results"),
            key=lambda result: (
                display_date(result.swimDate or result.meet.startDate) or "9999-12-31",
                result.id,
            ),
        )
        eligible = []
        for result in event_results:
            seconds = time_to_seconds(result.time or "")
            if result.isDQ or result.resultStatus != "finished" or seconds is None:
                continue
            eligible.append((result, seconds))
        fastest = min(eligible, key=lambda item: item[1])[0] if eligible else None
        performance_rows = [_individual_event_row(result) for result in event_results]
        event_payload = {
            **group,
            "source_event_labels": sorted(group["source_event_labels"]),
            "performance_count": len(event_results),
            "finished_performance_count": len(eligible),
            "fastest_recorded": _individual_event_row(fastest) if fastest else None,
            "split_coverage": {
                "available": sum(bool(row["splits"]) for row in performance_rows),
                "total": len(performance_rows),
            },
            "performances": performance_rows,
        }
        course_events[str(group["course"])].append(event_payload)

    course_order = {"LCM": 0, "SCM": 1, "Unknown": 2}
    course_history = []
    for course, events in sorted(course_events.items(), key=lambda item: course_order.get(item[0], 99)):
        events.sort(key=lambda event: (event["distance_m"] is None, event["distance_m"] or 999999, event["stroke"] or "", event["event"]))
        course_history.append({"course": course, "event_count": len(events), "events": events})

    relay_history = []
    for rr in sorted(relays, key=lambda rr: rr.swimDate or rr.meet.startDate):
        relay_history.append(_relay_event_row(rr))

    warnings = [warning for swimmer in swimmers for warning in suspicious_name_warnings(swimmer)]
    profile_payload = athlete_profile_brief(profile, (swimmer.age for swimmer in swimmers))
    if is_unlinked_source:
        profile_payload["athlete_profile_id"] = None
        profile_payload["source_swimmer_id"] = source_swimmer.id
        profile_payload["identity_status"] = "source_row_unlinked"
    return {
        "swimmer": profile_payload,
        "stats": {
            "individual_result_count": len(results),
            "relay_result_count": len(relays),
            "meet_count": len({r.meetId for r in results} | {rr.meetId for rr in relays}),
            "event_count": (
                sum(group["event_count"] for group in course_history)
                + len({rr.event for rr in relays})
            ),
            "warning_count": len(warnings),
        },
        "personal_bests": pbs,
        "event_history": event_history,
        "course_history": course_history,
        "relay_history": relay_history,
        "warnings": warnings,
    }


def browser_swimmer_detail(db: Session, swimmer_id: int) -> dict[str, Any] | None:
    """Resolve an old source-row URL to its athlete profile when available."""
    swimmer = db.query(Swimmer).filter(Swimmer.id == swimmer_id).first()
    if swimmer is None:
        return None
    if swimmer.athleteProfileId is None:
        return browser_athlete_profile_detail(db, source_swimmer=swimmer)
    return browser_athlete_profile_detail(db, swimmer.athleteProfileId)


def browser_data_quality(db: Session, *, page: int = 1, limit: int = 50) -> dict[str, Any]:
    warnings = []
    suspicious = db.query(Swimmer).filter(_suspicious_name_sql_expr(Swimmer.name)).all()
    for s in suspicious:
        warnings.extend(suspicious_name_warnings(s))
    missing_results = db.query(Result).filter(or_(Result.sourceDocumentSha256.is_(None), Result.parseJobId.is_(None))).all()
    for r in missing_results:
        warnings.extend(source_warning("result", r.id, r.sourceDocumentSha256, r.parseJobId))
    missing_relays = db.query(RelayResult).filter(or_(RelayResult.sourceDocumentSha256.is_(None), RelayResult.parseJobId.is_(None))).all()
    for rr in missing_relays:
        warnings.extend(source_warning("relay_result", rr.id, rr.sourceDocumentSha256, rr.parseJobId))

    summary: dict[str, int] = defaultdict(int)
    for w in warnings:
        summary[w["type"]] += 1
    total = len(warnings)
    start = (page - 1) * limit
    return {"summary": dict(summary), "data": warnings[start : start + limit], "pagination": pagination(page, limit, total)}


def _individual_event_row(r: Result) -> dict[str, Any]:
    warnings = []
    warnings.extend(suspicious_name_warnings(r.swimmer, sample_rows=[{"result_id": r.id, "meet_id": r.meetId, "event_key": make_event_key(r.meetId, r.event, r.sourceEventNumber)}]))
    warnings.extend(source_warning("result", r.id, r.sourceDocumentSha256, r.parseJobId))
    warnings.extend(no_time_warning("result", r.id, r.isDQ, r.time, r.resultStatus))
    return {
        "row_type": "individual",
        "id": r.id,
        "event_key": make_event_key(r.meetId, r.event, r.sourceEventNumber),
        "event_label": r.event,
        "round": r.round,
        "swim_date": display_date(r.swimDate),
        "placement": r.placement,
        "time": r.time,
        "seed_time": r.seedTime,
        "is_dq": r.isDQ,
        "status": r.resultStatus,
        "dq_code": r.dqCode,
        "dq_description": r.dqDescription,
        "is_guest": r.isGuest,
        "is_exhibition": r.isExhibition,
        "qualifier": r.qualifier,
        "splits": parsed_splits(r.splits),
        "swimmer": swimmer_brief(r.swimmer),
        "meet": meet_brief(r.meet),
        "source": {"document_sha256": r.sourceDocumentSha256, "parse_job_id": r.parseJobId, "source_scope": "result"},
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def _relay_event_row(rr: RelayResult) -> dict[str, Any]:
    warnings = []
    warnings.extend(source_warning("relay_result", rr.id, rr.sourceDocumentSha256, rr.parseJobId))
    warnings.extend(no_time_warning("relay_result", rr.id, rr.isDQ, rr.time, rr.resultStatus))
    if rr.legParseStatus in {"partial", "unavailable"}:
        warnings.append({
            "type": "relay_legs_quarantined",
            "severity": "warning",
            "entity_kind": "relay_result",
            "entity_id": rr.id,
            "message": "Some relay swimmers could not be verified from the official result.",
            "count": 1,
            "sample_rows": [{"relay_result_id": rr.id}],
            "source_fields": ["RelayResult.legParseStatus", "RelayResult.legParseWarning"],
        })
    legs = []
    for leg in sorted(rr.legs, key=lambda l: l.legNumber):
        linked_name = leg.swimmer.name if leg.swimmer is not None else leg.swimmerName
        suspicious_identity = bool(leg.swimmerId) and (
            _is_suspicious_name(leg.swimmerName) or _is_suspicious_name(linked_name)
        )
        confidence = "needs_review" if suspicious_identity else ("high" if leg.swimmerId else "unmatched")
        matched_by = "relay_leg_swimmer_id" if leg.swimmerId else "none"
        identity_status = "needs_review" if suspicious_identity else ("linked" if leg.swimmerId else "unmatched")
        leg_warnings = []
        if suspicious_identity:
            warning = {
                "type": "relay_identity_needs_review",
                "severity": "warning",
                "entity_kind": "relay_leg",
                "entity_id": leg.id,
                "message": "This relay swimmer name could not be verified.",
                "count": 1,
                "sample_rows": [{"relay_result_id": rr.id, "relay_leg_id": leg.id}],
                "source_fields": ["RelayLeg.swimmerId", "RelayLeg.swimmerName", "Swimmer.name"],
            }
            leg_warnings.append(warning)
            warnings.append(warning)
        if not leg.swimmerId:
            warning = {
                "type": "relay_identity_unmatched",
                "severity": "warning",
                "entity_kind": "relay_leg",
                "entity_id": leg.id,
                "message": "Relay leg is not linked to a swimmer profile.",
                "count": 1,
                "sample_rows": [{"relay_result_id": rr.id, "relay_leg_id": leg.id}],
                "source_fields": ["RelayLeg.swimmerId", "RelayLeg.swimmerName"],
            }
            leg_warnings.append(warning)
            warnings.append(warning)
        legs.append({
            "leg_number": leg.legNumber,
            "swimmer_id": leg.swimmerId,
            "swimmer_name": leg.swimmerName,
            "age": leg.age,
            "gender": leg.gender,
            "split_time": leg.splitTime,
            "reaction_time": leg.reactionTime,
            "matched_by": matched_by,
            "identity_match_confidence": confidence,
            "identity_status": identity_status,
            "warning_count": len(leg_warnings),
            "warnings": leg_warnings,
        })
    return {
        "row_type": "relay",
        "id": rr.id,
        "event_key": make_event_key(rr.meetId, rr.event, rr.sourceEventNumber),
        "event_label": rr.event,
        "round": rr.round,
        "swim_date": display_date(rr.swimDate),
        "placement": rr.placement,
        "time": rr.time,
        "seed_time": rr.seedTime,
        "is_dq": rr.isDQ,
        "status": rr.resultStatus,
        "team_name": rr.teamName,
        "relay_letter": rr.relayLetter,
        "is_exhibition": rr.isExhibition,
        "leg_parse_status": rr.legParseStatus,
        "leg_parse_warning": rr.legParseWarning,
        "legs": legs,
        "meet": meet_brief(rr.meet),
        "source": {"document_sha256": rr.sourceDocumentSha256, "parse_job_id": rr.parseJobId, "source_scope": "parent_relay_result"},
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def _sort_event_rows(rows: list[dict[str, Any]], order: str) -> list[dict[str, Any]]:
    if order == "time":
        return sorted(rows, key=lambda r: (time_to_seconds(r.get("time") or "") is None, time_to_seconds(r.get("time") or "") or 999999, r.get("row_type"), r.get("id")))
    if order == "name":
        return sorted(rows, key=lambda r: ((r.get("swimmer") or {}).get("name") or r.get("team_name") or "", r.get("id")))
    return sorted(rows, key=lambda r: (r.get("placement") is None, r.get("placement") or 999999, r.get("row_type"), r.get("id")))


def _source_no_sort(value: str | None) -> tuple[int, str]:
    if value and value.isdigit():
        return (int(value), value)
    return (999999, value or "")


def _suspicious_name_sql_expr(column: Any) -> Any:
    return or_(
        func.length(column) > 90,
        *(column.ilike(f"%{fragment}%") for fragment in _SUSPICIOUS_NAME_FRAGMENTS),
    )
