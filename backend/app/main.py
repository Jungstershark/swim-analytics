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
import os
import re
import tempfile
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import distinct, func, or_
from sqlalchemy.orm import Session, joinedload

from .browser import (
    browser_data_quality,
    browser_event,
    browser_meet,
    browser_overview,
    browser_swimmer_detail,
    list_browser_swimmers,
)
from .competition_packages import resolve_session_metadata
from .database import Base, engine, get_db
from .entity_resolution import resolve_swimmer, resolve_team
from .ingestion import (
    classify_document,
    cleanup_unledgered_archives,
    is_import_eligible_document,
    pdf_storage_path,
    record_parse_job,
    record_raw_document,
    start_ingestion_run,
)
from .models import CompetitionSession, IngestionRun, Meet, MonitorRun, ParseJob, RawDocument, RelayLeg, RelayResult, Result, SourceEvent, SourceRule, SourceSite, Swimmer
from .parsers.base import detect_and_parse
from .parsers.hytek import ConfidenceReport, ParsedMeet, parse_hytek_pdf, time_to_seconds
from .source_monitoring import (
    SourceMonitorAlreadyRunningError,
    SourceRuleDisabledError,
    SourceRuleNotFoundError,
    discover_sgaquatics_events,
    run_discovery_preview,
)
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

PARSER_VERSION = "hytek-v2"
RAW_ARCHIVE_ROOT = Path(os.getenv("SWIM_RAW_ARCHIVE_ROOT", "data/raw-documents"))
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_ZIP_PDFS = 100
MAX_ZIP_EXPANDED_BYTES = 250 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 200


@dataclass
class UploadedPdf:
    path: Path
    filename: str
    file_bytes: bytes
    content_type: str = "application/pdf"


@dataclass
class PreparedUploadPdf:
    uploaded: UploadedPdf
    parsed: ParsedMeet
    confidence: ConfidenceReport
    parser_format: str
    meet_start: datetime
    meet_end: datetime
    swim_date: datetime | None


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
    """Optional local-dev schema bootstrap.

    Production/release schema changes are Alembic-backed. Keep startup read-only
    unless explicitly requested for throwaway local/dev databases.
    """
    if os.getenv("SWIM_ANALYTICS_CREATE_ALL_ON_STARTUP", "").lower() in {"1", "true", "yes"}:
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
    """Convert parser time_type to round label.

    Domain/display assumption: these labels drive meet detail and result-table
    grouping. Do not rename/reorder them as a cosmetic cleanup without checking
    how finals/prelims/timed-finals should appear to swim users.
    """
    mapping = {
        "Prelim Time": "Prelim",
        "Finals Time": "Final",
        "Timed Final": "Timed Final",
    }
    return mapping.get(time_type, time_type or "Final")


def _compute_legacy_result_hash(
    meet_id: int, event: str, swimmer_name: str, team: str | None,
    round_name: str | None, time: str | None,
) -> str:
    """Return the pre-v2 hash so exact legacy rows can be matched safely."""
    raw = f"{meet_id}|{event}|{swimmer_name}|{team or ''}|{round_name or ''}|{time or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _compute_result_hash(
    meet_id: int, event: str, swimmer_name: str, team: str | None,
    round_name: str | None, time: str | None, age: int | None = None,
    *, session_id: int | None = None, swim_date: datetime | None = None,
    source_event_number: str | None = None, status: str = "unknown",
) -> str:
    """Session-aware SHA-256 identity for one source performance."""
    date_key = swim_date.date().isoformat() if swim_date is not None else ""
    raw = (
        f"v4|{meet_id}|{session_id or ''}|{date_key}|{source_event_number or ''}|"
        f"{event}|{swimmer_name}|{team or ''}|{age if age is not None else ''}|"
        f"{round_name or ''}|{time or ''}|{status}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _resolve_legacy_upload_dates(parsed) -> tuple[datetime, datetime, datetime | None]:
    """Map typed parser dates into the legacy Meet/Result compatibility layer."""
    if parsed.start_date is None or parsed.end_date is None:
        raise ValueError("A valid segment date range is required")
    if parsed.metadata_conflicts:
        raise ValueError("Competition metadata is conflicting")

    meet_start = datetime.combine(parsed.start_date, datetime.min.time())
    meet_end = datetime.combine(parsed.end_date, datetime.min.time())
    resolution = resolve_session_metadata(parsed)
    if resolution.status == "conflicting":
        raise ValueError("; ".join(resolution.diagnostics))

    if resolution.race_date is not None:
        swim_date = datetime.combine(resolution.race_date, datetime.min.time())
    elif parsed.start_date == parsed.end_date:
        swim_date = meet_start
    else:
        swim_date = None
    return meet_start, meet_end, swim_date


def _swimmer_brief(s: Swimmer) -> SwimmerBrief:
    return SwimmerBrief(id=s.id, name=s.name, age=s.age, team=s.team)


def _meet_brief(m: Meet) -> MeetBrief:
    return MeetBrief(id=m.id, name=m.name, date=m.startDate, end_date=m.endDate, location=m.location)


def _result_to_list_item(r: Result) -> ResultListItem:
    """Slim result for list views — no splits or reaction_time."""
    return ResultListItem(
        id=r.id,
        event=r.event,
        time=r.time,
        seed_time=r.seedTime,
        placement=r.placement,
        is_dq=r.isDQ,
        status=r.resultStatus,
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
        status=r.resultStatus,
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
        status=rr.resultStatus,
        is_exhibition=rr.isExhibition,
        round=rr.round,
        swim_date=rr.swimDate,
        leg_parse_status=rr.legParseStatus,
        leg_parse_warning=rr.legParseWarning,
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
        status=r.resultStatus,
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
        status=rr.resultStatus,
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
        status=r.resultStatus,
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
    """Parse PDF/ZIP and return preview without inserting to DB or archival tables."""
    uploaded_pdfs = _extract_pdfs_from_upload(file)

    event_groups: list[PreviewEventGroup] = []
    total_results = 0
    all_swimmers: set[str] = set()
    try:
        prepared, _skipped = _prepare_upload_bundle(uploaded_pdfs)
        for item in prepared:
            parsed = item.parsed

            for ev in parsed.events:
                rows_by_round: dict[str, list[PreviewResultRow]] = {}

                # Individual results
                for pr in ev.results:
                    all_swimmers.add(pr.name)
                    row_round = _time_type_to_round(pr.time_type)
                    rows_by_round.setdefault(row_round, []).append(PreviewResultRow(
                        event=ev.event_name,
                        name=pr.name,
                        age=pr.age,
                        team=pr.team,
                        time=pr.finals_time,
                        seed_time=pr.seed_time,
                        round=row_round,
                        placement=pr.placement,
                        is_dq=pr.is_dq,
                        status=_effective_result_status(pr),
                        is_guest=pr.is_guest,
                        qualifier=pr.qualifier,
                    ))

                # Relay results — show as team entries
                for rr in ev.relay_results:
                    for leg in rr.legs:
                        all_swimmers.add(leg.name)
                    row_round = _time_type_to_round(rr.time_type)
                    rows_by_round.setdefault(row_round, []).append(PreviewResultRow(
                        event=ev.event_name,
                        name=f"{rr.team_name} {rr.relay_letter or ''}".strip(),
                        age=None,
                        team=", ".join(leg.name.replace(", ", " ") for leg in rr.legs) if rr.legs else "",
                        time=rr.finals_time,
                        seed_time=rr.seed_time,
                        round=row_round,
                        placement=rr.placement,
                        is_dq=rr.is_dq,
                        status=_effective_result_status(rr),
                        is_guest=False,
                        qualifier=None,
                    ))

                for row_round, rows in rows_by_round.items():
                    total_results += len(rows)
                    # Preview sample: first 10 + last 3 for spot-checking edge cases
                    sample = rows[:10] + rows[-3:] if len(rows) > 13 else rows
                    event_groups.append(PreviewEventGroup(
                        event=ev.event_name,
                        round=row_round,
                        result_count=len(rows),
                        results=sample,
                    ))
    finally:
        for p in uploaded_pdfs:
            p.path.unlink(missing_ok=True)

    first = prepared[0]
    aggregate_checks = {
        name: all(item.confidence.checks.get(name, False) for item in prepared)
        for name in set().union(*(item.confidence.checks for item in prepared))
    }
    unmatched_lines = [
        line
        for item in prepared
        for line in item.confidence.unmatched_lines
    ]

    return UploadPreviewResponse(
        parser_format=first.parser_format,
        confidence_score=min(item.confidence.score for item in prepared),
        confidence_passed=all(item.confidence.passed for item in prepared),
        confidence_checks=[
            ConfidenceCheck(name=k, passed=v) for k, v in sorted(aggregate_checks.items())
        ],
        unmatched_lines=unmatched_lines,
        meet_name=first.parsed.meet_name,
        meet_dates=first.parsed.meet_dates,
        session=first.parsed.session if len(prepared) == 1 else f"{len(prepared)} sessions",
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


def _extract_pdfs_from_upload(file: UploadFile) -> list[UploadedPdf]:
    """Extract PDF(s) from an uploaded file (PDF or ZIP), preserving source metadata."""
    original_filename = file.filename or "upload"
    filename = original_filename.lower()
    file_bytes = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Upload exceeds the 50 MiB limit")

    if filename.endswith(".zip"):
        tmp_zip = _parse_pdf_to_temp(file_bytes, suffix=".zip")
        pdfs: list[UploadedPdf] = []
        try:
            with zipfile.ZipFile(tmp_zip) as zf:
                pdf_infos = [
                    info
                    for info in zf.infolist()
                    if not info.filename.startswith("__MACOSX")
                    and Path(info.filename).name.lower().endswith(".pdf")
                ]
                if len(pdf_infos) > MAX_ZIP_PDFS:
                    raise HTTPException(status_code=413, detail="ZIP contains more than 100 PDFs")
                if sum(info.file_size for info in pdf_infos) > MAX_ZIP_EXPANDED_BYTES:
                    raise HTTPException(status_code=413, detail="ZIP expands beyond the 250 MiB limit")
                for info in sorted(pdf_infos, key=lambda item: item.filename):
                    if info.file_size and (
                        info.compress_size == 0
                        or info.file_size / info.compress_size > MAX_ZIP_COMPRESSION_RATIO
                    ):
                        raise HTTPException(
                            status_code=413,
                            detail=f"ZIP member has an unsafe compression ratio: {info.filename}",
                        )
                    safe_name = Path(info.filename).name
                    pdf_bytes = zf.read(info)
                    if len(pdf_bytes) != info.file_size:
                        raise HTTPException(status_code=400, detail=f"ZIP member size mismatch: {info.filename}")
                    if not pdf_bytes.startswith(b"%PDF"):
                        raise HTTPException(status_code=422, detail=f"ZIP member is not a PDF: {info.filename}")
                    pdfs.append(UploadedPdf(
                        path=_parse_pdf_to_temp(pdf_bytes),
                        filename=safe_name,
                        file_bytes=pdf_bytes,
                    ))
        except Exception:
            for uploaded_pdf in pdfs:
                uploaded_pdf.path.unlink(missing_ok=True)
            raise
        finally:
            tmp_zip.unlink(missing_ok=True)
        if not pdfs:
            raise HTTPException(status_code=400, detail="ZIP file contains no PDF files")
        return pdfs
    elif filename.endswith(".pdf"):
        if not file_bytes.startswith(b"%PDF"):
            raise HTTPException(status_code=422, detail="Uploaded file is not a PDF")
        return [UploadedPdf(
            path=_parse_pdf_to_temp(file_bytes),
            filename=original_filename,
            file_bytes=file_bytes,
            content_type=file.content_type or "application/pdf",
        )]
    else:
        raise HTTPException(status_code=400, detail="Only PDF or ZIP files are accepted")


def _prepare_upload_bundle(
    uploaded_pdfs: list[UploadedPdf],
) -> tuple[list[PreparedUploadPdf], list[str]]:
    """Parse and validate the entire upload before any database/archive mutation."""
    prepared: list[PreparedUploadPdf] = []
    skipped: list[str] = []
    failures: list[str] = []

    for uploaded in uploaded_pdfs:
        category = classify_document(uploaded.filename)
        if not is_import_eligible_document(category):
            skipped.append(f"{uploaded.filename}: archived only ({category})")
            continue
        try:
            parsed, confidence, parser_format = detect_and_parse(uploaded.path)
        except Exception as exc:
            failures.append(f"{uploaded.filename}: parse failed ({exc})")
            continue
        if not confidence.passed:
            failed_checks = ", ".join(
                name for name, passed in confidence.checks.items() if not passed
            )
            failures.append(
                f"{uploaded.filename}: confidence checks failed ({failed_checks})"
            )
            continue
        resolution = resolve_session_metadata(parsed)
        if resolution.status == "conflicting":
            failures.append(
                f"{uploaded.filename}: session metadata conflicts "
                f"({' ; '.join(resolution.diagnostics)})"
            )
            continue
        try:
            meet_start, meet_end, swim_date = _resolve_legacy_upload_dates(parsed)
        except ValueError as exc:
            failures.append(f"{uploaded.filename}: date resolution failed ({exc})")
            continue
        prepared.append(
            PreparedUploadPdf(
                uploaded=uploaded,
                parsed=parsed,
                confidence=confidence,
                parser_format=parser_format,
                meet_start=meet_start,
                meet_end=meet_end,
                swim_date=swim_date,
            )
        )

    if failures:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "The complete upload bundle failed preflight; nothing was imported",
                "errors": failures,
            },
        )
    if not prepared:
        raise HTTPException(status_code=422, detail="No import-eligible result PDFs were found")

    identities = {
        (
            item.parsed.meet_name.strip().casefold(),
            item.meet_start,
            item.meet_end,
        )
        for item in prepared
    }
    if len(identities) != 1:
        labels = sorted(
            f"{item.parsed.meet_name} ({item.meet_start.date()} to "
            f"{item.meet_end.date() if item.meet_end else 'unknown'})"
            for item in prepared
        )
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Upload contains multiple competition segments; import them separately",
                "segments": labels,
            },
        )
    return prepared, skipped


def _legacy_swim_date_compatible(existing: datetime | None, resolved: datetime | None) -> bool:
    if existing is None or resolved is None:
        return existing is None and resolved is None
    return existing.date() == resolved.date()


def _effective_result_status(value) -> str:
    declared = getattr(value, "resultStatus", None) or getattr(value, "status", None)
    if declared and declared != "unknown":
        return declared
    if getattr(value, "isDQ", False) or getattr(value, "is_dq", False):
        return "dq"
    if getattr(value, "time", None) or getattr(value, "finals_time", None):
        return "finished"
    return "unknown"


def _legacy_individual_evidence_matches(existing: Result, parsed_result, swim_date: datetime | None) -> bool:
    return (
        existing.swimmer.age == parsed_result.age
        and existing.seedTime == parsed_result.seed_time
        and existing.placement == parsed_result.placement
        and existing.isDQ == parsed_result.is_dq
        and _effective_result_status(existing) == _effective_result_status(parsed_result)
        and existing.dqCode == parsed_result.dq_code
        and existing.dqDescription == parsed_result.dq_description
        and existing.isGuest == parsed_result.is_guest
        and existing.qualifier == parsed_result.qualifier
        and existing.reactionTime == parsed_result.reaction_time
        and existing.splits == _splits_to_json(parsed_result.splits)
        and _legacy_swim_date_compatible(existing.swimDate, swim_date)
    )


def _individual_evidence_matches(
    existing: Result,
    parsed_result,
    *,
    event_name: str,
    round_name: str,
    swim_date: datetime | None,
    source_event_number: str,
    session_id: int | None,
) -> bool:
    """Require an identity-hash hit to agree with all persisted race evidence."""
    return (
        existing.event == event_name
        and existing.time == parsed_result.finals_time
        and existing.round == round_name
        and existing.rawSwimmerName == parsed_result.name
        and existing.rawTeamName == parsed_result.team
        and existing.sourceEventNumber == source_event_number
        and existing.sessionId == session_id
        and _legacy_individual_evidence_matches(existing, parsed_result, swim_date)
    )


def _legacy_relay_evidence_matches(existing: RelayResult, parsed_relay, swim_date: datetime | None) -> bool:
    stored_legs = sorted(
        (
            leg.legNumber,
            leg.swimmerName,
            leg.age,
            leg.gender,
            leg.isGuest,
            leg.reactionTime,
            leg.splitTime,
            leg.splits,
        )
        for leg in existing.legs
    )
    parsed_legs = sorted(
        (
            leg.leg_number,
            leg.name,
            leg.age,
            leg.gender,
            leg.is_guest,
            leg.reaction_time,
            leg.split_time,
            _splits_to_json(leg.splits),
        )
        for leg in parsed_relay.legs
    )
    return (
        existing.seedTime == parsed_relay.seed_time
        and existing.placement == parsed_relay.placement
        and existing.isDQ == parsed_relay.is_dq
        and _effective_result_status(existing) == _effective_result_status(parsed_relay)
        and existing.dqCode == parsed_relay.dq_code
        and existing.dqDescription == parsed_relay.dq_description
        and existing.isExhibition == parsed_relay.is_exhibition
        and existing.reactionTime == parsed_relay.reaction_time
        and existing.splits == _splits_to_json(parsed_relay.splits)
        and existing.legParseStatus == parsed_relay.leg_parse_status
        and existing.legParseWarning == parsed_relay.leg_parse_warning
        and _legacy_swim_date_compatible(existing.swimDate, swim_date)
        and stored_legs == parsed_legs
    )


def _relay_evidence_matches(
    existing: RelayResult,
    parsed_relay,
    *,
    event_name: str,
    round_name: str,
    swim_date: datetime | None,
    source_event_number: str,
    session_id: int | None,
) -> bool:
    """Require a relay identity-hash hit to agree with all race evidence."""
    return (
        existing.event == event_name
        and existing.time == parsed_relay.finals_time
        and existing.round == round_name
        and existing.rawTeamName == parsed_relay.team_name
        and existing.relayLetter == parsed_relay.relay_letter
        and existing.sourceEventNumber == source_event_number
        and existing.sessionId == session_id
        and _legacy_relay_evidence_matches(existing, parsed_relay, swim_date)
    )


def _process_parsed_meet(
    parsed,
    meet: Meet,
    swim_date: datetime | None,
    db: Session,
    *,
    raw_document: RawDocument | None = None,
    parse_job: ParseJob | None = None,
    ingestion_run: IngestionRun | None = None,
    parser_version: str | None = None,
    competition_session: CompetitionSession | None = None,
) -> tuple[int, int, int, list[str], list[dict]]:
    """Process parsed results into database. Returns (results_count, swimmers_created, duplicates_skipped, errors, duplicates)."""
    errors: list[str] = []
    duplicates_list: list[dict] = []
    swimmers_created: set[int] = set()
    results_count = 0
    duplicates_skipped = 0

    for event in parsed.events:
        for pr in event.results:
            round_name = _time_type_to_round(pr.time_type)
            content_hash = _compute_result_hash(
                meet_id=meet.id, event=event.event_name, swimmer_name=pr.name,
                team=pr.team, round_name=round_name, time=pr.finals_time,
                age=pr.age,
                session_id=competition_session.id if competition_session else None,
                swim_date=swim_date,
                source_event_number=event.event_number,
                status=_effective_result_status(pr),
            )

            if competition_session is not None and raw_document is not None:
                sourced_legacy = db.query(Result).filter(
                    Result.meetId == meet.id,
                    Result.sessionId.is_(None),
                    Result.sourceDocumentSha256 == raw_document.sha256,
                    Result.sourceEventNumber == event.event_number,
                    Result.event == event.event_name,
                    Result.rawSwimmerName == pr.name,
                    Result.rawTeamName == pr.team,
                    Result.round == round_name,
                    Result.time == pr.finals_time,
                ).all()
                if len(sourced_legacy) > 1:
                    raise ValueError(
                        "Multiple legacy results matched one sourced session performance"
                    )
                if sourced_legacy:
                    legacy_result = sourced_legacy[0]
                    if not _legacy_individual_evidence_matches(
                        legacy_result, pr, swim_date
                    ):
                        raise ValueError(
                            "Legacy sourced result evidence conflicts with parsed source"
                        )
                    legacy_result.sessionId = competition_session.id
                    legacy_result.swimDate = swim_date
                    legacy_result.contentHash = content_hash
                    legacy_result.resultStatus = _effective_result_status(pr)
                    duplicates_skipped += 1
                    duplicates_list.append({
                        "event": event.event_name, "name": pr.name,
                        "team": pr.team, "round": round_name, "time": pr.finals_time,
                    })
                    continue

            # Check exact source identity before resolving the swimmer. This keeps
            # re-imports idempotent even when age/team evidence is too incomplete
            # to safely attach the row to an existing person.
            existing = db.query(Result).filter(Result.contentHash == content_hash).first()
            if existing is None and competition_session is None:
                # v1 hashes omitted age. Accept a legacy hash only when the linked
                # swimmer carries exactly the same age evidence, including NULL;
                # otherwise an age-conflicting row must continue to resolution.
                legacy_hash = _compute_legacy_result_hash(
                    meet_id=meet.id,
                    event=event.event_name,
                    swimmer_name=pr.name,
                    team=pr.team,
                    round_name=round_name,
                    time=pr.finals_time,
                )
                age_match = (
                    Swimmer.age.is_(None)
                    if pr.age is None
                    else Swimmer.age == pr.age
                )
                existing = (
                    db.query(Result)
                    .join(Swimmer, Result.swimmerId == Swimmer.id)
                    .filter(Result.contentHash == legacy_hash, age_match)
                    .first()
                )
            if existing:
                if not _individual_evidence_matches(
                    existing,
                    pr,
                    event_name=event.event_name,
                    round_name=round_name,
                    swim_date=swim_date,
                    source_event_number=event.event_number,
                    session_id=competition_session.id if competition_session else None,
                ):
                    raise ValueError(
                        "Matching result content hash has conflicting evidence"
                    )
                duplicates_skipped += 1
                duplicates_list.append({
                    "event": event.event_name, "name": pr.name,
                    "team": pr.team, "round": round_name, "time": pr.finals_time,
                })
                continue

            swimmer, created = resolve_swimmer(db, pr.name, pr.age, pr.team)
            if created:
                swimmers_created.add(swimmer.id)

            # Identity resolution intentionally treats validated team spelling
            # variants as one swimmer. Dedup must use the same semantics or a
            # corrected team label can duplicate an otherwise identical swim.
            existing = db.query(Result).filter(
                Result.swimmerId == swimmer.id,
                Result.meetId == meet.id,
                Result.event == event.event_name,
                Result.round == round_name,
                Result.swimDate == swim_date,
                Result.time == pr.finals_time,
                Result.resultStatus == _effective_result_status(pr),
                Result.sourceEventNumber == event.event_number,
                (
                    Result.sessionId == competition_session.id
                    if competition_session
                    else Result.sessionId.is_(None)
                ),
            ).first()
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
                resultStatus=_effective_result_status(pr),
                dqCode=pr.dq_code,
                dqDescription=pr.dq_description,
                isGuest=pr.is_guest,
                qualifier=pr.qualifier,
                reactionTime=pr.reaction_time,
                splits=_splits_to_json(pr.splits),
                round=round_name,
                swimDate=swim_date,
                contentHash=content_hash,
                rawSwimmerName=pr.name,
                rawTeamName=pr.team,
                sourceDocumentSha256=raw_document.sha256 if raw_document else None,
                parseJobId=parse_job.id if parse_job else None,
                ingestionRunId=ingestion_run.id if ingestion_run else None,
                parserVersion=parser_version,
                sourceEventNumber=event.event_number,
                sessionId=competition_session.id if competition_session else None,
            )
            db.add(result)
            results_count += 1

    # Process relay results
    for event in parsed.events:
        for rr in event.relay_results:
            round_name = _time_type_to_round(rr.time_type)
            team_canonical = resolve_team(db, rr.team_name)

            # Compute relay content hash (kept on raw team name so re-imports stay
            # idempotent with previously imported data).
            relay_hash = _compute_result_hash(
                meet_id=meet.id, event=event.event_name,
                swimmer_name=rr.team_name, team=rr.relay_letter,
                round_name=round_name, time=rr.finals_time,
                session_id=competition_session.id if competition_session else None,
                swim_date=swim_date,
                source_event_number=event.event_number,
                status=_effective_result_status(rr),
            )

            if competition_session is not None and raw_document is not None:
                sourced_legacy = db.query(RelayResult).filter(
                    RelayResult.meetId == meet.id,
                    RelayResult.sessionId.is_(None),
                    RelayResult.sourceDocumentSha256 == raw_document.sha256,
                    RelayResult.sourceEventNumber == event.event_number,
                    RelayResult.event == event.event_name,
                    RelayResult.rawTeamName == rr.team_name,
                    RelayResult.relayLetter == rr.relay_letter,
                    RelayResult.round == round_name,
                    RelayResult.time == rr.finals_time,
                ).all()
                if len(sourced_legacy) > 1:
                    raise ValueError(
                        "Multiple legacy relay results matched one sourced session performance"
                    )
                if sourced_legacy:
                    legacy_relay = sourced_legacy[0]
                    if not _legacy_relay_evidence_matches(
                        legacy_relay, rr, swim_date
                    ):
                        raise ValueError(
                            "Legacy sourced relay evidence conflicts with parsed source"
                        )
                    legacy_relay.sessionId = competition_session.id
                    legacy_relay.swimDate = swim_date
                    legacy_relay.contentHash = relay_hash
                    legacy_relay.resultStatus = _effective_result_status(rr)
                    legacy_relay.legParseStatus = rr.leg_parse_status
                    legacy_relay.legParseWarning = rr.leg_parse_warning
                    duplicates_skipped += 1
                    duplicates_list.append({
                        "event": event.event_name, "name": rr.team_name,
                        "team": rr.relay_letter, "round": round_name, "time": rr.finals_time,
                    })
                    continue

            existing = db.query(RelayResult).filter(RelayResult.contentHash == relay_hash).first()
            if existing is None:
                query = db.query(RelayResult).filter(
                    RelayResult.meetId == meet.id,
                    RelayResult.event == event.event_name,
                    RelayResult.teamName == team_canonical,
                    RelayResult.relayLetter == rr.relay_letter,
                    RelayResult.round == round_name,
                    RelayResult.swimDate == swim_date,
                    RelayResult.time == rr.finals_time,
                    RelayResult.resultStatus == _effective_result_status(rr),
                    RelayResult.sourceEventNumber == event.event_number,
                )
                query = query.filter(
                    RelayResult.sessionId == competition_session.id
                    if competition_session
                    else RelayResult.sessionId.is_(None)
                )
                existing = query.first()
            if existing:
                if not _relay_evidence_matches(
                    existing,
                    rr,
                    event_name=event.event_name,
                    round_name=round_name,
                    swim_date=swim_date,
                    source_event_number=event.event_number,
                    session_id=competition_session.id if competition_session else None,
                ):
                    raise ValueError(
                        "Matching relay content hash has conflicting evidence"
                    )
                duplicates_skipped += 1
                duplicates_list.append({
                    "event": event.event_name, "name": rr.team_name,
                    "team": rr.relay_letter, "round": round_name, "time": rr.finals_time,
                })
                continue

            relay_result = RelayResult(
                meetId=meet.id,
                event=event.event_name,
                teamName=team_canonical,
                relayLetter=rr.relay_letter,
                time=rr.finals_time,
                seedTime=rr.seed_time,
                placement=rr.placement,
                isDQ=rr.is_dq,
                resultStatus=_effective_result_status(rr),
                dqCode=rr.dq_code,
                dqDescription=rr.dq_description,
                isExhibition=rr.is_exhibition,
                round=round_name,
                swimDate=swim_date,
                splits=_splits_to_json(rr.splits),
                reactionTime=rr.reaction_time,
                legParseStatus=rr.leg_parse_status,
                legParseWarning=rr.leg_parse_warning,
                contentHash=relay_hash,
                rawTeamName=rr.team_name,
                sourceDocumentSha256=raw_document.sha256 if raw_document else None,
                parseJobId=parse_job.id if parse_job else None,
                ingestionRunId=ingestion_run.id if ingestion_run else None,
                parserVersion=parser_version,
                sourceEventNumber=event.event_number,
                sessionId=competition_session.id if competition_session else None,
            )
            db.add(relay_result)
            db.flush()

            # Process relay legs — find/create swimmers
            for leg in rr.legs:
                # For relay swimmers, team is the (canonicalized) relay team name
                swimmer, created = resolve_swimmer(db, leg.name, leg.age, rr.team_name)
                if created:
                    swimmers_created.add(swimmer.id)

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
    uploaded_pdfs = _extract_pdfs_from_upload(file)
    try:
        prepared, preflight_warnings = _prepare_upload_bundle(uploaded_pdfs)
    except Exception:
        for uploaded_pdf in uploaded_pdfs:
            uploaded_pdf.path.unlink(missing_ok=True)
        raise
    prepared_by_path = {item.uploaded.path: item for item in prepared}
    ingestion_run = start_ingestion_run(
        db,
        mode="replace" if replace else "append",
        input_scope=f"upload:{file.filename or 'upload'}",
        parser_version=PARSER_VERSION,
    )

    all_errors: list[str] = list(preflight_warnings)
    all_duplicates: list[dict] = []
    total_results = 0
    total_swimmers = 0
    total_duplicates = 0
    total_events = 0
    meet = None
    meet_identity: tuple[str, datetime, datetime] | None = None
    created_archive_paths: set[Path] = set()

    try:
        for uploaded_pdf in uploaded_pdfs:
            archive_path = pdf_storage_path(
                RAW_ARCHIVE_ROOT,
                hashlib.sha256(uploaded_pdf.file_bytes).hexdigest(),
            )
            if not archive_path.exists():
                created_archive_paths.add(archive_path)
            raw_document = record_raw_document(
                db,
                file_bytes=uploaded_pdf.file_bytes,
                filename=uploaded_pdf.filename,
                source_type="user_upload",
                source_label=file.filename or uploaded_pdf.filename,
                archive_root=RAW_ARCHIVE_ROOT,
                content_type=uploaded_pdf.content_type,
            )
            item = prepared_by_path.get(uploaded_pdf.path)
            if item is None:
                category = classify_document(uploaded_pdf.filename)
                reason = f"Skipped {uploaded_pdf.filename}: document type '{category}' is archived but not importable as swim results yet"
                record_parse_job(
                    db,
                    raw_document=raw_document,
                    parser_name="hytek",
                    parser_version=PARSER_VERSION,
                    status="rejected",
                    confidence_score=None,
                    confidence_passed=False,
                    events_count=0,
                    individual_results_count=0,
                    relay_results_count=0,
                    unmatched_lines_count=0,
                    error_message=reason,
                )
                continue
            parsed = item.parsed
            confidence = item.confidence
            parser_format = item.parser_format

            parse_job = record_parse_job(
                db,
                raw_document=raw_document,
                parser_name=parser_format,
                parser_version=PARSER_VERSION,
                status="succeeded" if confidence.passed else "rejected",
                confidence_score=confidence.score,
                confidence_passed=confidence.passed,
                events_count=len(parsed.events),
                individual_results_count=parsed.total_results,
                relay_results_count=parsed.total_relay_results,
                unmatched_lines_count=len(confidence.unmatched_lines),
            )

            meet_start = item.meet_start
            meet_end = item.meet_end
            swim_date = item.swim_date

            parsed_identity = (parsed.meet_name, meet_start, meet_end)
            if meet_identity is not None and parsed_identity != meet_identity:
                db.rollback()
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "A single upload may contain only one competition segment; "
                        f"found both '{meet_identity[0]}' and '{parsed.meet_name}'"
                    ),
                )

            # Find or create Meet
            if meet is None:
                meet_identity = parsed_identity
                meet = db.query(Meet).filter(
                    Meet.name == parsed.meet_name, Meet.startDate == meet_start
                ).first()
                if not meet:
                    meet = Meet(name=parsed.meet_name, startDate=meet_start, endDate=meet_end, parserFormat=parser_format)
                    db.add(meet)
                    db.flush()
                elif meet_end and not meet.endDate:
                    meet.endDate = meet_end
                elif meet.endDate and meet.endDate.date() != meet_end.date():
                    raise ValueError(
                        f"Stored meet end date {meet.endDate.date()} conflicts with "
                        f"uploaded end date {meet_end.date()}"
                    )

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
            rc, sc, dc, errs, dups = _process_parsed_meet(
                parsed,
                meet,
                swim_date,
                db,
                raw_document=raw_document,
                parse_job=parse_job,
                ingestion_run=ingestion_run,
                parser_version=PARSER_VERSION,
            )
            if errs:
                raise ValueError(
                    f"Import validation failed for {uploaded_pdf.filename}: "
                    f"{'; '.join(errs)}"
                )
            total_results += rc
            total_swimmers += sc
            total_duplicates += dc
            total_events += len(parsed.events)
            all_duplicates.extend(dups)

        ingestion_run.status = "succeeded" if meet is not None else "failed"
        ingestion_run.recordsInserted = total_results
        ingestion_run.duplicatesSkipped = total_duplicates
        ingestion_run.validationErrors = "; ".join(all_errors) if all_errors else None
        db.commit()
    except Exception:
        db.rollback()
        cleanup_unledgered_archives(db, created_archive_paths)
        raise
    finally:
        # Clean up any remaining temp files
        for p in uploaded_pdfs:
            p.path.unlink(missing_ok=True)

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
# Browser read-model APIs — Slice 3 longitudinal browser foundation
# ---------------------------------------------------------------------------

@app.get("/api/browser/overview")
def get_browser_overview(db: Session = Depends(get_db)):
    return browser_overview(db)


@app.get("/api/browser/swimmers")
def get_browser_swimmers(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    q: Optional[str] = None,
    team: Optional[str] = None,
    min_results: Optional[int] = Query(None, ge=0),
    has_warnings: Optional[bool] = None,
    sort: str = Query("name", pattern="^(name|team|result_count|latest_meet)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    return list_browser_swimmers(
        db,
        page=page,
        limit=limit,
        q=q,
        team=team,
        min_results=min_results,
        has_warnings=has_warnings,
        sort=sort,
        order=order,
    )


@app.get("/api/browser/swimmers/{swimmer_id}")
def get_browser_swimmer(swimmer_id: int, db: Session = Depends(get_db)):
    payload = browser_swimmer_detail(db, swimmer_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Swimmer not found")
    return payload


@app.get("/api/browser/meets/{meet_id}")
def get_browser_meet(meet_id: int, db: Session = Depends(get_db)):
    payload = browser_meet(db, meet_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Meet not found")
    return payload


@app.get("/api/browser/events")
def get_browser_event(
    meet_id: int = Query(..., ge=1),
    event_key: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    round: Optional[str] = None,
    row_type: str = Query("all", pattern="^(all|individual|relay)$"),
    order: str = Query("place", pattern="^(place|time|name)$"),
    db: Session = Depends(get_db),
):
    payload = browser_event(
        db,
        meet_id=meet_id,
        event_key=event_key,
        page=page,
        limit=limit,
        round_name=round,
        row_type=row_type,
        order=order,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Meet not found")
    return payload


@app.get("/api/browser/data-quality")
def get_browser_data_quality(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return browser_data_quality(db, page=page, limit=limit)


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

    # Compute personal bests per event from explicitly finished results only.
    best_by_event: dict[str, tuple[Result, float]] = {}
    for r in results:
        if r.isDQ or r.resultStatus != "finished" or not r.time:
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
# Admin source monitoring
# ---------------------------------------------------------------------------

def _load_json_value(value: str | None):
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _policy_labels(rule: SourceRule) -> list[str]:
    preview_categories = _load_json_value(rule.categoriesToPreview) or []
    import_categories = _load_json_value(rule.categoriesAllowedForImport) or []
    archive_categories = _load_json_value(rule.categoriesToArchive) or []
    return [
        "Schedule: Not configured",
        "Cadence: Manual only",
        "Active window: Manual preview only",
        "Stale window: Manual preview only",
        f"Automatic import: Disabled / {rule.autoImportPolicy}",
        f"Preview catalog categories: {', '.join(preview_categories)}",
        f"Future manual-import candidate categories: {', '.join(import_categories)}",
        f"Document-link categories tracked: {', '.join(archive_categories)}",
    ]


def _source_rule_to_admin(rule: SourceRule, db: Session | None = None) -> dict:
    last_run = None
    if db is not None and rule.id is not None:
        latest = (
            db.query(MonitorRun)
            .filter(MonitorRun.sourceRuleId == rule.id)
            .order_by(MonitorRun.startedAt.desc())
            .first()
        )
        if latest is not None:
            last_run = _monitor_run_to_admin(latest)
    return {
        "id": rule.id,
        "name": rule.name,
        "indexUrl": rule.indexUrl,
        "enabled": rule.enabled,
        "adapterType": rule.source_site.adapterType if rule.source_site else None,
        "scheduleLabel": "Not configured",
        "lastTriggerLabel": (last_run or {}).get("triggerType", "Manual"),
        "autoImportPolicy": rule.autoImportPolicy,
        "autoImportLabel": f"Disabled / {rule.autoImportPolicy}",
        "policyLabels": _policy_labels(rule),
        "lastRun": last_run,
        "lastStatus": (last_run or {}).get("status"),
        "lastFinishedAt": (last_run or {}).get("finishedAt"),
        "eventsDiscovered": (last_run or {}).get("eventsDiscovered", 0),
        "eventsWithResults": (last_run or {}).get("eventsWithResults", 0),
        "actionRequiredCount": (last_run or {}).get("actionRequiredCount", 0),
        "cadencePolicy": _load_json_value(rule.cadencePolicy),
        "activeWindowPolicy": _load_json_value(rule.activeWindowPolicy),
        "staleWindowPolicy": _load_json_value(rule.staleWindowPolicy),
        "categoriesToArchive": _load_json_value(rule.categoriesToArchive) or [],
        "categoriesToPreview": _load_json_value(rule.categoriesToPreview) or [],
        "categoriesAllowedForImport": _load_json_value(rule.categoriesAllowedForImport) or [],
    }


def _source_event_to_admin(event: SourceEvent) -> dict:
    return {
        "id": event.id,
        "sourceRuleId": event.sourceRuleId,
        "title": event.title,
        "pageTitle": event.pageTitle,
        "url": event.url,
        "sourceYear": event.sourceYear,
        "readinessStatus": event.readinessStatus,
        "isCurrentlyListed": event.isCurrentlyListed,
        "pdfCount": event.pdfCount,
        "resultPdfCount": event.resultPdfCount,
        "categoryCounts": _load_json_value(event.categoryCountsJson) or {},
        "documentCount": len(event.documents),
        "firstSeenAt": event.firstSeenAt,
        "lastSeenInIndexAt": event.lastSeenInIndexAt,
        "lastCheckedAt": event.lastCheckedAt,
        "lastChangedAt": event.lastChangedAt,
    }


def _monitor_run_to_admin(run: MonitorRun) -> dict:
    return {
        "id": run.id,
        "sourceRuleId": run.sourceRuleId,
        "triggerType": run.triggerType,
        "triggeredBy": run.triggeredBy,
        "adapterVersion": run.adapterVersion,
        "status": run.status,
        "startedAt": run.startedAt,
        "finishedAt": run.finishedAt,
        "eventsDiscovered": run.eventsDiscovered,
        "eventsWithResults": run.eventsWithResults,
        "addedEvents": run.addedEvents,
        "updatedEvents": run.updatedEvents,
        "unchangedEvents": run.unchangedEvents,
        "absentFromIndexEvents": run.absentFromIndexEvents,
        "addedDocuments": run.addedDocuments,
        "updatedDocuments": run.updatedDocuments,
        "unchangedDocuments": run.unchangedDocuments,
        "actionRequiredCount": run.actionRequiredCount,
        "errorMessage": run.errorMessage,
        "summary": _load_json_value(run.summaryJson) or {},
    }


@app.get("/api/admin/sources")
def admin_list_sources(db: Session = Depends(get_db)):
    sites = db.query(SourceSite).options(joinedload(SourceSite.rules)).order_by(SourceSite.name).all()
    return {
        "data": [
            {
                "id": site.id,
                "name": site.name,
                "baseUrl": site.baseUrl,
                "adapterType": site.adapterType,
                "isEnabled": site.isEnabled,
                "rules": [_source_rule_to_admin(rule, db=db) for rule in site.rules],
            }
            for site in sites
        ]
    }


@app.get("/api/admin/source-events")
def admin_list_source_events(db: Session = Depends(get_db)):
    events = (
        db.query(SourceEvent)
        .options(joinedload(SourceEvent.documents))
        .order_by(SourceEvent.isCurrentlyListed.desc(), SourceEvent.sourceYear.desc(), SourceEvent.title)
        .all()
    )
    return {"data": [_source_event_to_admin(event) for event in events]}


@app.get("/api/admin/monitor-runs")
def admin_list_monitor_runs(db: Session = Depends(get_db)):
    runs = db.query(MonitorRun).order_by(MonitorRun.startedAt.desc()).limit(50).all()
    return {"data": [_monitor_run_to_admin(run) for run in runs]}


@app.post("/api/admin/source-rules/{rule_id}/run-discovery-preview")
def admin_run_discovery_preview(rule_id: int, db: Session = Depends(get_db)):
    try:
        run = run_discovery_preview(db, rule_id, discover=discover_sgaquatics_events)
    except SourceRuleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SourceRuleDisabledError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SourceMonitorAlreadyRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"data": _monitor_run_to_admin(run)}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0"}
