"""
FastAPI application — Swim Analytics API

Endpoints:
  POST /api/upload          Upload & parse a HY-TEK PDF
  GET  /api/meets           List meets (paginated)
  GET  /api/meets/{id}      Meet detail with results grouped by event
  GET  /api/swimmers        List/search swimmers (paginated)
  GET  /api/swimmers/{id}   Swimmer profile with personal bests
  GET  /api/results         Query results with filters (paginated)
  GET  /api/analytics/progression  Swimmer time progression for an event
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import distinct, func, or_
from sqlalchemy.orm import Session, joinedload

from .database import Base, engine, get_db
from .models import Meet, RelayLeg, RelayResult, Result, Swimmer
from .parsers.base import detect_and_parse
from .parsers.hytek import ConfidenceReport, parse_hytek_pdf, time_to_seconds
from .schemas import (
    CombinedResultItem,
    CombinedResultsResponse,
    ConfidenceCheck,
    DuplicateEntry,
    EventGroup,
    MeetBrief,
    MeetDetail,
    MeetListItem,
    MeetListResponse,
    PaginationInfo,
    PersonalBest,
    PreviewEventGroup,
    PreviewResultRow,
    ProgressionDataPoint,
    ProgressionResponse,
    ResultBrief,
    ResultDetail,
    ResultListItem,
    ResultListResponse,
    SwimmerBrief,
    SwimmerDetail,
    SwimmerListItem,
    SwimmerListResponse,
    RelayLegBrief,
    RelayListResponse,
    RelayResultBrief,
    RelayResultDetail,
    UploadPreviewResponse,
    UploadResponse,
)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Swim Analytics API",
    description="SSA Swim Meet Results Parsing & Analytics Platform",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _paginate(query, page: int, limit: int, db: Session):
    total = query.count()
    total_pages = math.ceil(total / limit) if limit > 0 else 0
    items = query.offset((page - 1) * limit).limit(limit).all()
    pagination = PaginationInfo(page=page, limit=limit, total=total, total_pages=total_pages)
    return items, pagination


def _splits_to_json(splits) -> Optional[str]:
    if not splits:
        return None
    return json.dumps([
        {"cumulative": s.cumulative_time, "split": s.split_time, "distance": s.distance}
        for s in splits
    ])


def _time_type_to_round(time_type: str) -> str:
    """Convert parser time_type to round label."""
    mapping = {
        "Prelim Time": "Prelim",
        "Finals Time": "Final",
    }
    return mapping.get(time_type, time_type or "Final")


def _compute_result_hash(
    meet_id: int, event: str, swimmer_name: str, team: str | None,
    round_name: str | None, time: str | None,
) -> str:
    """SHA-256 hash for result deduplication."""
    raw = f"{meet_id}|{event}|{swimmer_name}|{team or ''}|{round_name or ''}|{time or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _swimmer_brief(s: Swimmer) -> SwimmerBrief:
    return SwimmerBrief(id=s.id, name=s.name, age=s.age, team=s.team)


def _meet_brief(m: Meet) -> MeetBrief:
    return MeetBrief(id=m.id, name=m.name, date=m.startDate, location=m.location)


def _result_to_list_item(r: Result) -> ResultListItem:
    """Slim result for list views — no splits or reaction_time."""
    return ResultListItem(
        id=r.id,
        event=r.event,
        time=r.time,
        seed_time=r.seedTime,
        placement=r.placement,
        is_dq=r.isDQ,
        dq_code=r.dqCode,
        dq_description=r.dqDescription,
        is_guest=r.isGuest,
        qualifier=r.qualifier,
        round=r.round,
        swim_date=r.swimDate,
        swimmer=_swimmer_brief(r.swimmer),
        meet=_meet_brief(r.meet),
    )


def _result_to_brief(r: Result) -> ResultBrief:
    """Slim result for embedded views — no splits or reaction_time."""
    return ResultBrief(
        id=r.id,
        event=r.event,
        time=r.time,
        seed_time=r.seedTime,
        placement=r.placement,
        is_dq=r.isDQ,
        dq_code=r.dqCode,
        dq_description=r.dqDescription,
        is_guest=r.isGuest,
        qualifier=r.qualifier,
        round=r.round,
        swim_date=r.swimDate,
        swimmer=_swimmer_brief(r.swimmer),
    )


def _relay_leg_brief(leg: RelayLeg) -> RelayLegBrief:
    swimmer = SwimmerBrief(id=leg.swimmerId or 0, name=leg.swimmerName, age=leg.age, team=None)
    if leg.swimmer:
        swimmer = _swimmer_brief(leg.swimmer)
    return RelayLegBrief(
        leg_number=leg.legNumber,
        swimmer=swimmer,
        split_time=leg.splitTime,
        reaction_time=leg.reactionTime,
        splits=leg.splits,
        is_guest=leg.isGuest,
        gender=leg.gender,
    )


def _relay_to_brief(rr: RelayResult) -> RelayResultBrief:
    return RelayResultBrief(
        id=rr.id,
        event=rr.event,
        team_name=rr.teamName,
        relay_letter=rr.relayLetter,
        time=rr.time,
        seed_time=rr.seedTime,
        placement=rr.placement,
        is_dq=rr.isDQ,
        is_exhibition=rr.isExhibition,
        round=rr.round,
        swim_date=rr.swimDate,
        legs=[_relay_leg_brief(leg) for leg in rr.legs],
        meet=_meet_brief(rr.meet),
    )


def _result_to_combined(r: Result) -> CombinedResultItem:
    return CombinedResultItem(
        type="individual",
        id=r.id,
        event=r.event,
        time=r.time,
        seed_time=r.seedTime,
        placement=r.placement,
        is_dq=r.isDQ,
        round=r.round,
        swim_date=r.swimDate,
        qualifier=r.qualifier,
        swimmer=_swimmer_brief(r.swimmer),
        is_guest=r.isGuest,
        meet=_meet_brief(r.meet),
    )


def _relay_to_combined(rr: RelayResult) -> CombinedResultItem:
    return CombinedResultItem(
        type="relay",
        id=rr.id,
        event=rr.event,
        time=rr.time,
        seed_time=rr.seedTime,
        placement=rr.placement,
        is_dq=rr.isDQ,
        round=rr.round,
        swim_date=rr.swimDate,
        team_name=rr.teamName,
        relay_letter=rr.relayLetter,
        is_exhibition=rr.isExhibition,
        legs=[_relay_leg_brief(leg) for leg in rr.legs],
        meet=_meet_brief(rr.meet),
    )


def _result_to_detail(r: Result) -> ResultDetail:
    """Full result with splits and reaction time."""
    return ResultDetail(
        id=r.id,
        event=r.event,
        time=r.time,
        seed_time=r.seedTime,
        placement=r.placement,
        is_dq=r.isDQ,
        dq_code=r.dqCode,
        dq_description=r.dqDescription,
        is_guest=r.isGuest,
        qualifier=r.qualifier,
        reaction_time=r.reactionTime,
        splits=r.splits,
        round=r.round,
        swim_date=r.swimDate,
        swimmer=_swimmer_brief(r.swimmer),
        meet=_meet_brief(r.meet),
    )


# ---------------------------------------------------------------------------
# POST /api/upload/preview
# ---------------------------------------------------------------------------

@app.post("/api/upload/preview", response_model=UploadPreviewResponse)
def upload_preview(file: UploadFile = File(...)):
    """Parse PDF/ZIP and return preview without inserting to DB."""
    pdf_paths = _extract_pdfs_from_upload(file)

    event_groups: list[PreviewEventGroup] = []
    total_results = 0
    all_swimmers: set[str] = set()
    meet_name = ""
    meet_dates = None
    session_label = None
    parser_format = "unknown"
    last_confidence = None

    try:
        for pdf_path in pdf_paths:
            try:
                parsed, confidence, fmt = detect_and_parse(pdf_path)
                parser_format = fmt
                last_confidence = confidence
            except Exception:
                continue
            finally:
                pdf_path.unlink(missing_ok=True)

            if not meet_name:
                meet_name = parsed.meet_name
                meet_dates = parsed.meet_dates
            if not session_label:
                session_label = parsed.session

            for ev in parsed.events:
                round_name = _time_type_to_round(ev.time_type)
                rows = []

                # Individual results
                for pr in ev.results:
                    all_swimmers.add(pr.name)
                    rows.append(PreviewResultRow(
                        event=ev.event_name,
                        name=pr.name,
                        age=pr.age,
                        team=pr.team,
                        time=pr.finals_time,
                        seed_time=pr.seed_time,
                        round=round_name,
                        placement=pr.placement,
                        is_dq=pr.is_dq,
                        is_guest=pr.is_guest,
                        qualifier=pr.qualifier,
                    ))

                # Relay results — show as team entries
                for rr in ev.relay_results:
                    for leg in rr.legs:
                        all_swimmers.add(leg.name)
                    rows.append(PreviewResultRow(
                        event=ev.event_name,
                        name=f"{rr.team_name} {rr.relay_letter or ''}".strip(),
                        age=None,
                        team=", ".join(leg.name.replace(", ", " ") for leg in rr.legs) if rr.legs else "",
                        time=rr.finals_time,
                        seed_time=rr.seed_time,
                        round=round_name,
                        placement=rr.placement,
                        is_dq=rr.is_dq,
                        is_guest=False,
                        qualifier=None,
                    ))

                total_results += len(rows)
                # Preview sample: first 10 + last 3 for spot-checking edge cases
                if len(rows) > 13:
                    sample = rows[:10] + rows[-3:]
                else:
                    sample = rows
                event_groups.append(PreviewEventGroup(
                    event=ev.event_name,
                    round=round_name,
                    result_count=len(rows),
                    results=sample,
                ))
    finally:
        for p in pdf_paths:
            p.unlink(missing_ok=True)

    if last_confidence is None:
        raise HTTPException(status_code=422, detail="No valid PDFs could be parsed")

    return UploadPreviewResponse(
        parser_format=parser_format,
        confidence_score=last_confidence.score,
        confidence_passed=last_confidence.passed,
        confidence_checks=[
            ConfidenceCheck(name=k, passed=v) for k, v in last_confidence.checks.items()
        ],
        unmatched_lines=last_confidence.unmatched_lines,
        meet_name=meet_name,
        meet_dates=meet_dates,
        session=session_label,
        events_count=len(event_groups),
        results_count=total_results,
        swimmers_count=len(all_swimmers),
        events=event_groups,
    )


# ---------------------------------------------------------------------------
# POST /api/upload
# ---------------------------------------------------------------------------

def _parse_pdf_to_temp(file_bytes: bytes, suffix: str = ".pdf") -> Path:
    """Write bytes to a temp file and return the path."""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        return Path(tmp.name)


def _extract_pdfs_from_upload(file: UploadFile) -> list[Path]:
    """Extract PDF path(s) from an uploaded file (PDF or ZIP)."""
    filename = (file.filename or "").lower()
    file_bytes = file.file.read()

    if filename.endswith(".zip"):
        tmp_zip = _parse_pdf_to_temp(file_bytes, suffix=".zip")
        pdf_paths = []
        try:
            with zipfile.ZipFile(tmp_zip) as zf:
                for name in sorted(zf.namelist()):
                    if name.lower().endswith(".pdf") and not name.startswith("__MACOSX"):
                        pdf_bytes = zf.read(name)
                        pdf_paths.append(_parse_pdf_to_temp(pdf_bytes))
        finally:
            tmp_zip.unlink(missing_ok=True)
        if not pdf_paths:
            raise HTTPException(status_code=400, detail="ZIP file contains no PDF files")
        return pdf_paths
    elif filename.endswith(".pdf"):
        return [_parse_pdf_to_temp(file_bytes)]
    else:
        raise HTTPException(status_code=400, detail="Only PDF or ZIP files are accepted")


def _process_parsed_meet(
    parsed, meet: Meet, swim_date: datetime, db: Session
) -> tuple[int, int, int, list[str], list[dict]]:
    """Process parsed results into database. Returns (results_count, swimmers_created, duplicates_skipped, errors, duplicates)."""
    errors: list[str] = []
    duplicates_list: list[dict] = []
    swimmers_created: set[str] = set()
    results_count = 0
    duplicates_skipped = 0

    for event in parsed.events:
        round_name = _time_type_to_round(event.time_type)

        for pr in event.results:
            swimmer = db.query(Swimmer).filter(
                Swimmer.name == pr.name,
                Swimmer.team == pr.team,
            ).first()

            if not swimmer:
                swimmer = Swimmer(name=pr.name, age=pr.age, team=pr.team)
                db.add(swimmer)
                db.flush()
                swimmers_created.add(pr.name)
            elif pr.age and (swimmer.age is None or pr.age > swimmer.age):
                swimmer.age = pr.age

            content_hash = _compute_result_hash(
                meet_id=meet.id, event=event.event_name, swimmer_name=pr.name,
                team=pr.team, round_name=round_name, time=pr.finals_time,
            )

            existing = db.query(Result).filter(Result.contentHash == content_hash).first()
            if existing:
                duplicates_skipped += 1
                duplicates_list.append({
                    "event": event.event_name, "name": pr.name,
                    "team": pr.team, "round": round_name, "time": pr.finals_time,
                })
                continue

            result = Result(
                swimmerId=swimmer.id,
                meetId=meet.id,
                event=event.event_name,
                time=pr.finals_time,
                seedTime=pr.seed_time,
                placement=pr.placement,
                isDQ=pr.is_dq,
                dqCode=pr.dq_code,
                dqDescription=pr.dq_description,
                isGuest=pr.is_guest,
                qualifier=pr.qualifier,
                reactionTime=pr.reaction_time,
                splits=_splits_to_json(pr.splits),
                round=round_name,
                swimDate=swim_date,
                contentHash=content_hash,
            )
            db.add(result)
            results_count += 1

    # Process relay results
    for event in parsed.events:
        round_name = _time_type_to_round(event.time_type)

        for rr in event.relay_results:
            # Compute relay content hash
            relay_hash = _compute_result_hash(
                meet_id=meet.id, event=event.event_name,
                swimmer_name=rr.team_name, team=rr.relay_letter,
                round_name=round_name, time=rr.finals_time,
            )

            existing = db.query(RelayResult).filter(RelayResult.contentHash == relay_hash).first()
            if existing:
                duplicates_skipped += 1
                duplicates_list.append({
                    "event": event.event_name, "name": rr.team_name,
                    "team": rr.relay_letter, "round": round_name, "time": rr.finals_time,
                })
                continue

            relay_result = RelayResult(
                meetId=meet.id,
                event=event.event_name,
                teamName=rr.team_name,
                relayLetter=rr.relay_letter,
                time=rr.finals_time,
                seedTime=rr.seed_time,
                placement=rr.placement,
                isDQ=rr.is_dq,
                dqCode=rr.dq_code,
                dqDescription=rr.dq_description,
                isExhibition=rr.is_exhibition,
                round=round_name,
                swimDate=swim_date,
                splits=_splits_to_json(rr.splits),
                reactionTime=rr.reaction_time,
                contentHash=relay_hash,
            )
            db.add(relay_result)
            db.flush()

            # Process relay legs — find/create swimmers
            for leg in rr.legs:
                # For relay swimmers, team is the relay team name
                swimmer = db.query(Swimmer).filter(
                    Swimmer.name == leg.name,
                    Swimmer.team == rr.team_name,
                ).first()

                if not swimmer:
                    swimmer = Swimmer(name=leg.name, age=leg.age, team=rr.team_name)
                    db.add(swimmer)
                    db.flush()
                    swimmers_created.add(leg.name)
                elif leg.age and (swimmer.age is None or leg.age > swimmer.age):
                    swimmer.age = leg.age

                relay_leg = RelayLeg(
                    relayResultId=relay_result.id,
                    legNumber=leg.leg_number,
                    swimmerId=swimmer.id,
                    swimmerName=leg.name,
                    age=leg.age,
                    gender=leg.gender,
                    isGuest=leg.is_guest,
                    reactionTime=leg.reaction_time,
                    splitTime=leg.split_time,
                    splits=_splits_to_json(leg.splits),
                )
                db.add(relay_leg)

            results_count += 1

    return results_count, len(swimmers_created), duplicates_skipped, errors, duplicates_list


@app.post("/api/upload", response_model=UploadResponse)
def upload_results(
    file: UploadFile = File(...),
    replace: bool = Query(False, description="Delete all existing results for this meet before importing"),
    db: Session = Depends(get_db),
):
    pdf_paths = _extract_pdfs_from_upload(file)

    all_errors: list[str] = []
    all_duplicates: list[dict] = []
    total_results = 0
    total_swimmers = 0
    total_duplicates = 0
    total_events = 0
    meet = None

    try:
        for pdf_path in pdf_paths:
            try:
                parsed, confidence, parser_format = detect_and_parse(pdf_path)
            except ValueError as e:
                all_errors.append(f"Unsupported format: {pdf_path.name}: {e}")
                continue
            except Exception as e:
                all_errors.append(f"Failed to parse {pdf_path.name}: {e}")
                continue
            finally:
                pdf_path.unlink(missing_ok=True)

            # Reject low-confidence parses
            if not confidence.passed:
                failed_checks = [k for k, v in confidence.checks.items() if not v]
                all_errors.append(
                    f"Parse rejected (confidence {confidence.score:.0%}): "
                    f"failed checks: {', '.join(failed_checks)}"
                )
                continue

            # Parse meet dates
            meet_start = datetime.now()
            meet_end = None
            if parsed.meet_dates:
                try:
                    parts = parsed.meet_dates.split(" to ")
                    meet_start = datetime.strptime(parts[0].strip(), "%d/%m/%Y")
                    if len(parts) > 1:
                        meet_end = datetime.strptime(parts[1].strip(), "%d/%m/%Y")
                except (ValueError, IndexError):
                    pass

            # Parse swim date from session
            swim_date = meet_start
            if parsed.session:
                day_match = re.search(r"Day\s+(\d+)", parsed.session, re.IGNORECASE)
                if day_match:
                    day_num = int(day_match.group(1))
                    swim_date = meet_start + timedelta(days=day_num - 1)

            # Find or create Meet
            if meet is None:
                meet = db.query(Meet).filter(
                    Meet.name == parsed.meet_name, Meet.startDate == meet_start
                ).first()
                if not meet:
                    meet = Meet(name=parsed.meet_name, startDate=meet_start, endDate=meet_end, parserFormat=parser_format)
                    db.add(meet)
                    db.flush()
                elif meet_end and not meet.endDate:
                    meet.endDate = meet_end

                # If replace mode, delete all existing results for this meet
                if replace:
                    # Delete relay legs first (FK constraint), then relay results, then individual results
                    relay_ids = [r.id for r in db.query(RelayResult.id).filter(RelayResult.meetId == meet.id).all()]
                    if relay_ids:
                        db.query(RelayLeg).filter(RelayLeg.relayResultId.in_(relay_ids)).delete(synchronize_session=False)
                        db.query(RelayResult).filter(RelayResult.meetId == meet.id).delete()
                    deleted = db.query(Result).filter(Result.meetId == meet.id).delete()
                    all_errors.append(f"Replaced {deleted} existing results for this meet")

            # Process results from this PDF
            rc, sc, dc, errs, dups = _process_parsed_meet(parsed, meet, swim_date, db)
            total_results += rc
            total_swimmers += sc
            total_duplicates += dc
            total_events += len(parsed.events)
            all_errors.extend(errs)
            all_duplicates.extend(dups)

        db.commit()

    finally:
        # Clean up any remaining temp files
        for p in pdf_paths:
            p.unlink(missing_ok=True)

    if meet is None:
        raise HTTPException(status_code=422, detail="No valid PDFs could be parsed")

    return UploadResponse(
        success=True,
        meet=_meet_brief(meet),
        results_count=total_results,
        swimmers_count=total_swimmers,
        events_count=total_events,
        duplicates_skipped=total_duplicates,
        duplicates=[
            DuplicateEntry(event=d["event"], name=d["name"], team=d.get("team"),
                           round=d.get("round"), time=d.get("time"))
            for d in all_duplicates
        ],
        errors=all_errors,
    )


# ---------------------------------------------------------------------------
# DELETE /api/meets/{id}
# ---------------------------------------------------------------------------

@app.delete("/api/meets/{meet_id}")
def delete_meet(meet_id: int, db: Session = Depends(get_db)):
    meet = db.query(Meet).filter(Meet.id == meet_id).first()
    if not meet:
        raise HTTPException(status_code=404, detail="Meet not found")
    # Delete relay legs first (FK), then relay results, then individual results
    relay_ids = [r.id for r in db.query(RelayResult.id).filter(RelayResult.meetId == meet_id).all()]
    if relay_ids:
        db.query(RelayLeg).filter(RelayLeg.relayResultId.in_(relay_ids)).delete(synchronize_session=False)
    relays_deleted = db.query(RelayResult).filter(RelayResult.meetId == meet_id).delete()
    results_deleted = db.query(Result).filter(Result.meetId == meet_id).delete()
    db.delete(meet)
    db.commit()
    return {"success": True, "results_deleted": results_deleted, "relays_deleted": relays_deleted}


# ---------------------------------------------------------------------------
# GET /api/meets
# ---------------------------------------------------------------------------

@app.get("/api/meets", response_model=MeetListResponse)
def list_meets(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    sort: str = Query("date", pattern="^(date|name)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    q = db.query(Meet)
    if search:
        q = q.filter(Meet.name.ilike(f"%{search}%"))

    sort_col = Meet.startDate if sort == "date" else Meet.name
    q = q.order_by(sort_col.desc() if order == "desc" else sort_col.asc())

    meets, pagination = _paginate(q, page, limit, db)

    data = []
    for m in meets:
        rc = db.query(func.count(Result.id)).filter(Result.meetId == m.id).scalar()
        sc = db.query(func.count(distinct(Result.swimmerId))).filter(Result.meetId == m.id).scalar()
        data.append(MeetListItem(
            id=m.id, name=m.name, date=m.startDate, location=m.location,
            result_count=rc, swimmer_count=sc,
        ))

    return MeetListResponse(data=data, pagination=pagination)


# ---------------------------------------------------------------------------
# GET /api/meets/{meet_id}
# ---------------------------------------------------------------------------

@app.get("/api/meets/{meet_id}", response_model=MeetDetail)
def get_meet(meet_id: int, db: Session = Depends(get_db)):
    meet = db.query(Meet).filter(Meet.id == meet_id).first()
    if not meet:
        raise HTTPException(status_code=404, detail="Meet not found")

    results = (
        db.query(Result)
        .filter(Result.meetId == meet_id)
        .options(joinedload(Result.swimmer))
        .order_by(Result.event, Result.placement.nullslast())
        .all()
    )

    # Group by event
    event_groups: dict[str, list[ResultBrief]] = defaultdict(list)
    for r in results:
        event_groups[r.event].append(_result_to_brief(r))

    events = [EventGroup(name=name, results=res) for name, res in event_groups.items()]

    return MeetDetail(
        id=meet.id, name=meet.name, date=meet.startDate, location=meet.location,
        events=events,
    )


# ---------------------------------------------------------------------------
# GET /api/swimmers
# ---------------------------------------------------------------------------

@app.get("/api/swimmers", response_model=SwimmerListResponse)
def list_swimmers(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    team: Optional[str] = None,
    sort: str = Query("name", pattern="^(name|team|age)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    q = db.query(Swimmer)
    if search:
        q = q.filter(Swimmer.name.ilike(f"%{search}%"))
    if team:
        q = q.filter(Swimmer.team.ilike(f"%{team}%"))

    sort_map = {"name": Swimmer.name, "team": Swimmer.team, "age": Swimmer.age}
    sort_col = sort_map.get(sort, Swimmer.name)
    q = q.order_by(sort_col.desc() if order == "desc" else sort_col.asc())

    swimmers, pagination = _paginate(q, page, limit, db)

    data = []
    for s in swimmers:
        rc = db.query(func.count(Result.id)).filter(Result.swimmerId == s.id).scalar()
        mc = db.query(func.count(distinct(Result.meetId))).filter(Result.swimmerId == s.id).scalar()
        latest = (
            db.query(Meet.startDate)
            .join(Result, Result.meetId == Meet.id)
            .filter(Result.swimmerId == s.id)
            .order_by(Meet.startDate.desc())
            .first()
        )
        data.append(SwimmerListItem(
            id=s.id, name=s.name, age=s.age, team=s.team,
            result_count=rc, meet_count=mc,
            latest_meet=latest[0].strftime("%Y-%m-%d") if latest else None,
        ))

    return SwimmerListResponse(data=data, pagination=pagination)


# ---------------------------------------------------------------------------
# GET /api/swimmers/{swimmer_id}
# ---------------------------------------------------------------------------

@app.get("/api/swimmers/{swimmer_id}", response_model=SwimmerDetail)
def get_swimmer(swimmer_id: int, db: Session = Depends(get_db)):
    swimmer = db.query(Swimmer).filter(Swimmer.id == swimmer_id).first()
    if not swimmer:
        raise HTTPException(status_code=404, detail="Swimmer not found")

    results = (
        db.query(Result)
        .filter(Result.swimmerId == swimmer_id)
        .options(joinedload(Result.meet))
        .order_by(Result.event)
        .all()
    )

    # Compute personal bests per event (best non-DQ time)
    best_by_event: dict[str, tuple[Result, float]] = {}
    for r in results:
        if r.isDQ or not r.time:
            continue
        secs = time_to_seconds(r.time)
        if secs is None:
            continue
        if r.event not in best_by_event or secs < best_by_event[r.event][1]:
            best_by_event[r.event] = (r, secs)

    personal_bests = []
    for event, (r, secs) in sorted(best_by_event.items()):
        personal_bests.append(PersonalBest(
            event=event,
            time=r.time,
            time_in_seconds=secs,
            meet=r.meet.name,
            date=(r.swimDate or r.meet.startDate).strftime("%Y-%m-%d"),
        ))

    # Recent results (last 20)
    recent = (
        db.query(Result)
        .filter(Result.swimmerId == swimmer_id)
        .options(joinedload(Result.meet), joinedload(Result.swimmer))
        .join(Meet)
        .order_by(Meet.startDate.desc())
        .limit(20)
        .all()
    )
    recent_items = [_result_to_list_item(r) for r in recent]

    # Stats
    total_meets = db.query(func.count(distinct(Result.meetId))).filter(Result.swimmerId == swimmer_id).scalar()
    total_results = db.query(func.count(Result.id)).filter(Result.swimmerId == swimmer_id).scalar()
    total_dqs = db.query(func.count(Result.id)).filter(Result.swimmerId == swimmer_id, Result.isDQ == True).scalar()

    first_meet = (
        db.query(Meet.startDate).join(Result).filter(Result.swimmerId == swimmer_id)
        .order_by(Meet.startDate.asc()).first()
    )
    latest_meet = (
        db.query(Meet.startDate).join(Result).filter(Result.swimmerId == swimmer_id)
        .order_by(Meet.startDate.desc()).first()
    )

    stats = {
        "total_meets": total_meets,
        "total_results": total_results,
        "total_dqs": total_dqs,
        "first_meet": first_meet[0].strftime("%Y-%m-%d") if first_meet else None,
        "latest_meet": latest_meet[0].strftime("%Y-%m-%d") if latest_meet else None,
    }

    return SwimmerDetail(
        id=swimmer.id, name=swimmer.name, age=swimmer.age, team=swimmer.team,
        personal_bests=personal_bests,
        recent_results=recent_items,
        stats=stats,
    )


# ---------------------------------------------------------------------------
# GET /api/events — distinct event names for filter dropdowns
# ---------------------------------------------------------------------------

@app.get("/api/events")
def list_events(meet_id: Optional[int] = None, db: Session = Depends(get_db)):
    q1 = db.query(distinct(Result.event))
    q2 = db.query(distinct(RelayResult.event))
    if meet_id:
        q1 = q1.filter(Result.meetId == meet_id)
        q2 = q2.filter(RelayResult.meetId == meet_id)
    individual = {row[0] for row in q1.all()}
    relay = {row[0] for row in q2.all()}
    events = sorted(individual | relay)
    return {"events": events}


# ---------------------------------------------------------------------------
# GET /api/relays
# ---------------------------------------------------------------------------

@app.get("/api/relays", response_model=RelayListResponse)
def list_relays(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    meet_id: Optional[int] = None,
    event: Optional[str] = None,
    swimmer: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(RelayResult).options(
        joinedload(RelayResult.meet),
        joinedload(RelayResult.legs).joinedload(RelayLeg.swimmer),
    )
    if meet_id:
        q = q.filter(RelayResult.meetId == meet_id)
    if event:
        q = q.filter(RelayResult.event.ilike(f"%{event}%"))
    if swimmer:
        q = q.join(RelayLeg).join(Swimmer).filter(Swimmer.name.ilike(f"%{swimmer}%"))
    q = q.order_by(RelayResult.event, RelayResult.placement.asc())

    results, pagination = _paginate(q, page, limit, db)
    data = [_relay_to_brief(rr) for rr in results]
    return RelayListResponse(data=data, pagination=pagination)


# ---------------------------------------------------------------------------
# GET /api/swimmers/{id}/relays
# ---------------------------------------------------------------------------

@app.get("/api/swimmers/{swimmer_id}/relays")
def get_swimmer_relays(swimmer_id: int, db: Session = Depends(get_db)):
    legs = db.query(RelayLeg).filter(
        RelayLeg.swimmerId == swimmer_id
    ).options(
        joinedload(RelayLeg.relay_result).joinedload(RelayResult.meet),
        joinedload(RelayLeg.relay_result).joinedload(RelayResult.legs).joinedload(RelayLeg.swimmer),
    ).all()

    relays = []
    for leg in legs:
        relays.append(_relay_to_brief(leg.relay_result))
    return {"data": relays}


# ---------------------------------------------------------------------------
# GET /api/results/all — combined individual + relay
# ---------------------------------------------------------------------------

@app.get("/api/results/all", response_model=CombinedResultsResponse)
def list_all_results(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    swimmer: Optional[str] = None,
    swimmer_id: Optional[int] = None,
    meet_id: Optional[int] = None,
    event: Optional[str] = None,
    is_dq: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    # Individual results
    q1 = db.query(Result).options(joinedload(Result.swimmer), joinedload(Result.meet))
    if swimmer:
        q1 = q1.join(Swimmer).filter(Swimmer.name.ilike(f"%{swimmer}%"))
    if swimmer_id:
        q1 = q1.filter(Result.swimmerId == swimmer_id)
    if meet_id:
        q1 = q1.filter(Result.meetId == meet_id)
    if event:
        q1 = q1.filter(Result.event.ilike(f"%{event}%"))
    if is_dq is not None:
        q1 = q1.filter(Result.isDQ == is_dq)
    individual = q1.all()

    # Relay results
    q2 = db.query(RelayResult).options(
        joinedload(RelayResult.meet),
        joinedload(RelayResult.legs).joinedload(RelayLeg.swimmer),
    )
    if meet_id:
        q2 = q2.filter(RelayResult.meetId == meet_id)
    if event:
        q2 = q2.filter(RelayResult.event.ilike(f"%{event}%"))
    if swimmer or swimmer_id:
        q2 = q2.join(RelayLeg)
        if swimmer:
            q2 = q2.join(Swimmer).filter(Swimmer.name.ilike(f"%{swimmer}%"))
        if swimmer_id:
            q2 = q2.filter(RelayLeg.swimmerId == swimmer_id)
    if is_dq is not None:
        q2 = q2.filter(RelayResult.isDQ == is_dq)
    relays = q2.all()

    # Combine and sort by event name
    combined = [_result_to_combined(r) for r in individual] + [_relay_to_combined(rr) for rr in relays]
    combined.sort(key=lambda x: (x.event, x.placement or 9999))

    # Manual pagination
    total = len(combined)
    total_pages = math.ceil(total / limit) if limit > 0 else 0
    start = (page - 1) * limit
    page_data = combined[start:start + limit]

    return CombinedResultsResponse(
        data=page_data,
        pagination=PaginationInfo(page=page, limit=limit, total=total, total_pages=total_pages),
    )


# ---------------------------------------------------------------------------
# GET /api/results
# ---------------------------------------------------------------------------

@app.get("/api/results", response_model=ResultListResponse)
def list_results(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    swimmer: Optional[str] = None,
    swimmer_id: Optional[int] = None,
    meet_id: Optional[int] = None,
    event: Optional[str] = None,
    team: Optional[str] = None,
    is_dq: Optional[bool] = None,
    sort: str = Query("time", pattern="^(time|date|placement|event)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    q = db.query(Result).options(joinedload(Result.swimmer), joinedload(Result.meet))

    if swimmer:
        q = q.join(Swimmer).filter(Swimmer.name.ilike(f"%{swimmer}%"))
    if swimmer_id:
        q = q.filter(Result.swimmerId == swimmer_id)
    if meet_id:
        q = q.filter(Result.meetId == meet_id)
    if event:
        q = q.filter(Result.event.ilike(f"%{event}%"))
    if team:
        q = q.join(Swimmer, isouter=True).filter(Swimmer.team.ilike(f"%{team}%"))
    if is_dq is not None:
        q = q.filter(Result.isDQ == is_dq)

    sort_map = {
        "time": Result.time,
        "placement": Result.placement,
        "event": Result.event,
        "date": Meet.startDate,
    }
    sort_col = sort_map.get(sort, Result.time)
    if sort == "date":
        q = q.join(Meet, isouter=True)
    q = q.order_by(sort_col.desc() if order == "desc" else sort_col.asc())

    results, pagination = _paginate(q, page, limit, db)
    data = [_result_to_list_item(r) for r in results]

    return ResultListResponse(data=data, pagination=pagination)


# ---------------------------------------------------------------------------
# GET /api/results/{id} — single result with splits
# ---------------------------------------------------------------------------

@app.get("/api/results/{result_id}", response_model=ResultDetail)
def get_result(result_id: int, db: Session = Depends(get_db)):
    r = db.query(Result).options(
        joinedload(Result.swimmer), joinedload(Result.meet)
    ).filter(Result.id == result_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Result not found")
    return _result_to_detail(r)


# ---------------------------------------------------------------------------
# GET /api/analytics/progression
# ---------------------------------------------------------------------------

@app.get("/api/analytics/progression", response_model=ProgressionResponse)
def get_progression(
    swimmer_id: int = Query(...),
    event: str = Query(...),
    db: Session = Depends(get_db),
):
    swimmer = db.query(Swimmer).filter(Swimmer.id == swimmer_id).first()
    if not swimmer:
        raise HTTPException(status_code=404, detail="Swimmer not found")

    results = (
        db.query(Result)
        .filter(Result.swimmerId == swimmer_id, Result.event == event, Result.isDQ == False)
        .options(joinedload(Result.meet))
        .join(Meet)
        .order_by(Meet.startDate.asc())
        .all()
    )

    data_points = []
    for r in results:
        if not r.time:
            continue
        secs = time_to_seconds(r.time)
        if secs is None:
            continue
        data_points.append(ProgressionDataPoint(
            date=(r.swimDate or r.meet.startDate).strftime("%Y-%m-%d"),
            time=r.time,
            time_in_seconds=secs,
            meet=r.meet.name,
            placement=r.placement,
        ))

    # Summary
    summary = {}
    if data_points:
        best = min(data_points, key=lambda dp: dp.time_in_seconds)
        summary = {
            "personal_best": best.time,
            "personal_best_date": best.date,
            "meet_count": len(data_points),
        }
        if len(data_points) > 1:
            first_time = data_points[0].time_in_seconds
            improvement = first_time - best.time_in_seconds
            summary["total_improvement"] = f"{improvement:.2f}s"
            summary["improvement_percent"] = round(improvement / first_time * 100, 2)

    return ProgressionResponse(
        swimmer=_swimmer_brief(swimmer),
        event=event,
        data_points=data_points,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0"}
