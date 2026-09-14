"""Competition package resolution and relational hierarchy tests."""

from datetime import date, datetime
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.competition_packages import resolve_session_metadata, upsert_competition_hierarchy
from app.database import Base
from app.ingestion import record_parse_job, record_raw_document, start_ingestion_run
from app.main import (
    _compute_result_hash,
    _legacy_swim_date_compatible,
    _process_parsed_meet,
    _resolve_legacy_upload_dates,
)
from app.models import (
    CompetitionDay,
    CompetitionEdition,
    CompetitionSegment,
    CompetitionSession,
    Meet,
    IngestionRun,
    RelayResult,
    Result,
    SourceReference,
    Swimmer,
)
from app.parsers.hytek import (
    ConfidenceReport,
    ParsedEvent,
    ParsedRelayLeg,
    ParsedRelayResult,
    parse_hytek_text,
)
from app.package_import import (
    ParsedCompetitionDocument,
    import_parsed_competition_documents,
    parse_competition_manifest,
)


def _test_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)()


def _parsed(segment: str, date_range: str, day: int, session: int):
    page = f"""HY-TEK's MEET MANAGER 8.0 Page 1
{segment} - {date_range}
Results - Day {day} Session {session}
Event 1 Men 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Example, Athlete 20 Example Club 24.00 23.50"""
    return parse_hytek_text([page])[0]


def _pre_exhibition_case(db: Session, tmp_path: Path) -> dict:
    meet = Meet(
        name="Singapore Short Course Invitational 2026",
        startDate=datetime(2026, 6, 1),
    )
    swimmer = Swimmer(name="Lim, Glen", age=17, team="Example Club")
    db.add_all([meet, swimmer])
    db.flush()
    parsed = parse_hytek_text(["""Singapore Short Course Invitational 2026 - 1/6/2026 to 2/6/2026
Results - Day 2 Session 3
Event 24 Men 200 SC Meter Freestyle
Name Age Team Seed Time Finals Time
--- Lim, Glen 17 Example Club 1:50.00 X1:47.30"""])[0]
    session = upsert_competition_hierarchy(
        db,
        source_key="https://example.test/ssci-2026/",
        competition_title="Singapore Short Course Invitational 2026",
        parsed=parsed,
        legacy_meet=meet,
    )
    raw = record_raw_document(
        db,
        file_bytes=b"%PDF-1.4\nssci exhibition source\n%%EOF",
        filename="ssci-day-2-session-3.pdf",
        source_type="fixture",
        source_label="fixture",
        archive_root=tmp_path / "archive",
    )
    old_ingestion_run = start_ingestion_run(
        db,
        mode="rebuild",
        input_scope="competition:https://example.test/ssci-2026/:old",
        parser_version="hytek-v1",
    )
    old_parse_job = record_parse_job(
        db,
        raw_document=raw,
        parser_name="hytek",
        parser_version="hytek-v1",
        status="succeeded",
        confidence_score=1.0,
        confidence_passed=True,
        events_count=1,
        individual_results_count=1,
        relay_results_count=0,
        unmatched_lines_count=0,
    )
    reimport_ingestion_run = start_ingestion_run(
        db,
        mode="rebuild",
        input_scope="competition:https://example.test/ssci-2026/:reimport",
        parser_version="hytek-v2",
    )
    reimport_parse_job = record_parse_job(
        db,
        raw_document=raw,
        parser_name="hytek",
        parser_version="hytek-v2",
        status="succeeded",
        confidence_score=1.0,
        confidence_passed=True,
        events_count=1,
        individual_results_count=1,
        relay_results_count=0,
        unmatched_lines_count=0,
    )
    event = parsed.events[0]
    source = event.results[0]
    swim_date = datetime(2026, 6, 2)

    def content_hash(*, is_exhibition: bool) -> str:
        return _compute_result_hash(
            meet.id,
            event.event_name,
            source.name,
            source.team,
            "Timed Final",
            source.finals_time,
            source.age,
            session_id=session.id,
            swim_date=swim_date,
            source_event_number=event.event_number,
            status="finished",
            is_exhibition=is_exhibition,
        )

    return {
        "meet": meet,
        "swimmer": swimmer,
        "parsed": parsed,
        "session": session,
        "raw": raw,
        "old_ingestion_run": old_ingestion_run,
        "old_parse_job": old_parse_job,
        "reimport_ingestion_run": reimport_ingestion_run,
        "reimport_parse_job": reimport_parse_job,
        "event": event,
        "source": source,
        "swim_date": swim_date,
        "pre_exhibition_hash": content_hash(is_exhibition=False),
        "canonical_hash": content_hash(is_exhibition=True),
    }


def _source_identity_result(
    case: dict,
    *,
    is_exhibition: bool = False,
    content_hash: str | None = None,
    sourced: bool = True,
) -> Result:
    source = case["source"]
    return Result(
        swimmerId=case["swimmer"].id,
        meetId=case["meet"].id,
        event=case["event"].event_name,
        time=source.finals_time,
        seedTime=source.seed_time,
        placement=source.placement,
        isDQ=source.is_dq,
        resultStatus="finished",
        dqCode=source.dq_code,
        dqDescription=source.dq_description,
        isGuest=source.is_guest,
        isExhibition=is_exhibition,
        qualifier=source.qualifier,
        reactionTime=source.reaction_time,
        splits=None,
        round="Timed Final",
        swimDate=case["swim_date"],
        contentHash=content_hash or case["pre_exhibition_hash"],
        rawSwimmerName=source.name,
        rawTeamName=source.team,
        sourceDocumentSha256=case["raw"].sha256 if sourced else None,
        parseJobId=case["old_parse_job"].id if sourced else None,
        ingestionRunId=case["old_ingestion_run"].id if sourced else None,
        parserVersion="hytek-v1" if sourced else None,
        sourceEventNumber=case["event"].event_number,
        sessionId=case["session"].id,
    )


def _reimport_exhibition_case(db: Session, case: dict):
    return _process_parsed_meet(
        case["parsed"],
        case["meet"],
        case["swim_date"],
        db,
        raw_document=case["raw"],
        parse_job=case["reimport_parse_job"],
        ingestion_run=case["reimport_ingestion_run"],
        parser_version="hytek-v2",
        competition_session=case["session"],
    )


def test_resolve_session_date_from_verified_segment_range_and_day():
    parsed = _parsed("56th SNAG Seniors", "17/3/2026 to 22/3/2026", 6, 12)

    resolved = resolve_session_metadata(parsed)

    assert resolved.race_date == date(2026, 3, 22)
    assert resolved.status == "derived"
    assert resolved.diagnostics == ()


def test_upsert_hierarchy_keeps_juniors_and_seniors_day_one_separate():
    db = _test_session()
    juniors_meet = Meet(name="56th SNAG Juniors", startDate=datetime(2026, 3, 13))
    seniors_meet = Meet(name="56th SNAG Seniors", startDate=datetime(2026, 3, 17))
    db.add_all([juniors_meet, seniors_meet])
    db.flush()

    juniors = upsert_competition_hierarchy(
        db,
        source_key="https://example.test/56th-snag-2026/",
        competition_title="56th SNAG 2026",
        parsed=_parsed("56th SNAG Juniors", "13/3/2026 to 15/3/2026", 1, 1),
        legacy_meet=juniors_meet,
    )
    seniors = upsert_competition_hierarchy(
        db,
        source_key="https://example.test/56th-snag-2026/",
        competition_title="56th SNAG 2026",
        parsed=_parsed("56th SNAG Seniors", "17/3/2026 to 22/3/2026", 1, 1),
        legacy_meet=seniors_meet,
    )
    db.flush()

    assert db.query(CompetitionEdition).count() == 1
    assert db.query(CompetitionSegment).count() == 2
    assert db.query(CompetitionDay).count() == 2
    assert db.query(CompetitionSession).count() == 2
    assert juniors.id != seniors.id
    assert juniors.day.date == date(2026, 3, 13)
    assert seniors.day.date == date(2026, 3, 17)
    assert juniors.sessionNumber == seniors.sessionNumber == 1

    again = upsert_competition_hierarchy(
        db,
        source_key="https://example.test/56th-snag-2026/",
        competition_title="56th SNAG 2026",
        parsed=_parsed("56th SNAG Seniors", "17/3/2026 to 22/3/2026", 1, 1),
        legacy_meet=seniors_meet,
    )
    db.flush()

    assert again.id == seniors.id
    assert db.query(CompetitionSession).count() == 2


def test_existing_session_resolution_is_refreshed_when_evidence_resolves():
    db = _test_session()
    parsed = _parsed("56th SNAG Seniors", "17/3/2026 to 22/3/2026", 1, 1)
    session = upsert_competition_hierarchy(
        db,
        source_key="https://example.test/56th-snag-2026/",
        competition_title="56th SNAG 2026",
        parsed=parsed,
    )
    session.resolutionStatus = "unknown"
    session.label = None
    db.flush()

    refreshed = upsert_competition_hierarchy(
        db,
        source_key="https://example.test/56th-snag-2026/",
        competition_title="56th SNAG 2026",
        parsed=parsed,
    )

    assert refreshed.id == session.id
    assert refreshed.resolutionStatus == "derived"
    assert refreshed.label == "Day 1 Session 1"


def test_out_of_range_day_is_preserved_as_unknown_not_fabricated():
    parsed = _parsed("Short Segment", "17/3/2026 to 22/3/2026", 7, 13)

    resolved = resolve_session_metadata(parsed)

    assert resolved.race_date is None
    assert resolved.status == "conflicting"
    assert "outside segment range" in resolved.diagnostics[0]


def test_legacy_upload_never_fabricates_missing_or_ambiguous_swim_date():
    malformed = parse_hytek_text(["Broken Meet - 31/2/2026\nResults"])[0]
    with pytest.raises(ValueError, match="valid segment date range"):
        _resolve_legacy_upload_dates(malformed)

    multi_day = parse_hytek_text([
        "Multi Day Meet - 1/6/2026 to 2/6/2026\nResults"
    ])[0]
    start, end, swim_date = _resolve_legacy_upload_dates(multi_day)
    assert start == datetime(2026, 6, 1)
    assert end == datetime(2026, 6, 2)
    assert swim_date is None

    single_day = parse_hytek_text(["Single Day Meet - 1/6/2026\nResults"])[0]
    _start, _end, swim_date = _resolve_legacy_upload_dates(single_day)
    assert swim_date == datetime(2026, 6, 1)


def test_legacy_attachment_requires_exact_date_evidence_missingness():
    resolved = datetime(2026, 6, 1)

    assert _legacy_swim_date_compatible(resolved, resolved)
    assert _legacy_swim_date_compatible(None, None)
    assert not _legacy_swim_date_compatible(None, resolved)
    assert not _legacy_swim_date_compatible(resolved, None)


def test_process_results_links_and_dedupes_within_session_not_across_sessions():
    db = _test_session()
    meet = Meet(name="56th SNAG Seniors", startDate=datetime(2026, 3, 17))
    db.add(meet)
    db.flush()

    session_one_parsed = _parsed(
        "56th SNAG Seniors", "17/3/2026 to 22/3/2026", 1, 1
    )
    session_two_parsed = _parsed(
        "56th SNAG Seniors", "17/3/2026 to 22/3/2026", 1, 2
    )
    session_one = upsert_competition_hierarchy(
        db,
        source_key="https://example.test/56th-snag-2026/",
        competition_title="56th SNAG 2026",
        parsed=session_one_parsed,
        legacy_meet=meet,
    )
    session_two = upsert_competition_hierarchy(
        db,
        source_key="https://example.test/56th-snag-2026/",
        competition_title="56th SNAG 2026",
        parsed=session_two_parsed,
        legacy_meet=meet,
    )

    first = _process_parsed_meet(
        session_one_parsed,
        meet,
        datetime(2026, 3, 17),
        db,
        competition_session=session_one,
    )
    repeated = _process_parsed_meet(
        session_one_parsed,
        meet,
        datetime(2026, 3, 17),
        db,
        competition_session=session_one,
    )
    second_session = _process_parsed_meet(
        session_two_parsed,
        meet,
        datetime(2026, 3, 17),
        db,
        competition_session=session_two,
    )
    db.flush()

    assert first[0] == 1
    assert repeated[0] == 0
    assert repeated[2] == 1
    assert second_session[0] == 1
    assert db.query(Result).count() == 2
    assert {row.sessionId for row in db.query(Result).all()} == {
        session_one.id,
        session_two.id,
    }


def test_sourced_legacy_result_is_attached_to_session_instead_of_duplicated(tmp_path: Path):
    db = _test_session()
    meet = Meet(name="56th SNAG Seniors", startDate=datetime(2026, 3, 17))
    swimmer = Swimmer(name="Example, Athlete", age=20, team="Example Club")
    db.add_all([meet, swimmer])
    db.flush()
    parsed = _parsed("56th SNAG Seniors", "17/3/2026 to 22/3/2026", 1, 1)
    session = upsert_competition_hierarchy(
        db,
        source_key="https://example.test/56th-snag-2026/",
        competition_title="56th SNAG 2026",
        parsed=parsed,
        legacy_meet=meet,
    )
    raw = record_raw_document(
        db,
        file_bytes=b"%PDF-1.4\nlegacy\n%%EOF",
        filename="legacy.pdf",
        source_type="fixture",
        source_label="fixture",
        archive_root=tmp_path / "archive",
    )
    legacy = Result(
        swimmerId=swimmer.id,
        meetId=meet.id,
        event="Men 50 LC Meter Freestyle",
        time="23.50",
        seedTime="24.00",
        placement=1,
        round="Timed Final",
        swimDate=datetime(2026, 3, 17),
        contentHash="legacy-hash",
        rawSwimmerName="Example, Athlete",
        rawTeamName="Example Club",
        sourceDocumentSha256=raw.sha256,
        sourceEventNumber="1",
    )
    db.add(legacy)
    db.flush()

    processed = _process_parsed_meet(
        parsed,
        meet,
        datetime(2026, 3, 17),
        db,
        raw_document=raw,
        competition_session=session,
    )
    db.flush()

    assert processed[0] == 0
    assert processed[2] == 1
    assert db.query(Result).count() == 1
    assert legacy.sessionId == session.id
    assert legacy.contentHash != "legacy-hash"


def test_canonical_reimport_upgrades_sourced_session_bound_pre_exhibition_result(
    tmp_path: Path,
):
    db = _test_session()
    case = _pre_exhibition_case(db, tmp_path)
    existing = _source_identity_result(case)
    db.add(existing)
    db.flush()
    existing_id = existing.id
    assert existing.isExhibition is False
    assert existing.contentHash == case["pre_exhibition_hash"]
    assert existing.contentHash != case["canonical_hash"]

    processed = _reimport_exhibition_case(db, case)
    db.flush()

    source = case["source"]
    event = case["event"]
    assert processed == (
        0,
        0,
        1,
        [],
        [{
            "event": event.event_name,
            "name": source.name,
            "team": source.team,
            "round": "Timed Final",
            "time": source.finals_time,
        }],
    )
    assert db.query(Result).count() == 1
    upgraded = db.query(Result).one()
    assert upgraded.id == existing_id
    assert upgraded.isExhibition is True
    assert upgraded.contentHash == case["canonical_hash"]
    assert (
        upgraded.swimmerId,
        upgraded.meetId,
        upgraded.sessionId,
        upgraded.sourceDocumentSha256,
        upgraded.sourceEventNumber,
        upgraded.event,
        upgraded.rawSwimmerName,
        upgraded.rawTeamName,
        upgraded.round,
        upgraded.swimDate,
        upgraded.time,
        upgraded.seedTime,
        upgraded.placement,
        upgraded.isDQ,
        upgraded.resultStatus,
        upgraded.dqCode,
        upgraded.dqDescription,
        upgraded.isGuest,
        upgraded.qualifier,
        upgraded.reactionTime,
        upgraded.splits,
        upgraded.parseJobId,
        upgraded.ingestionRunId,
        upgraded.parserVersion,
    ) == (
        case["swimmer"].id,
        case["meet"].id,
        case["session"].id,
        case["raw"].sha256,
        event.event_number,
        event.event_name,
        source.name,
        source.team,
        "Timed Final",
        case["swim_date"],
        source.finals_time,
        source.seed_time,
        source.placement,
        source.is_dq,
        "finished",
        source.dq_code,
        source.dq_description,
        source.is_guest,
        source.qualifier,
        source.reaction_time,
        None,
        case["old_parse_job"].id,
        case["old_ingestion_run"].id,
        "hytek-v1",
    )


def test_canonical_reimport_leaves_existing_sourced_exhibition_result_unchanged(
    tmp_path: Path,
):
    db = _test_session()
    case = _pre_exhibition_case(db, tmp_path)
    existing = _source_identity_result(
        case,
        is_exhibition=True,
        content_hash=case["canonical_hash"],
    )
    db.add(existing)
    db.flush()
    existing_id = existing.id
    original_provenance = (
        existing.sourceDocumentSha256,
        existing.parseJobId,
        existing.ingestionRunId,
        existing.parserVersion,
        existing.sessionId,
    )

    processed = _reimport_exhibition_case(db, case)
    db.flush()

    assert processed[0] == 0
    assert processed[2] == 1
    assert db.query(Result).count() == 1
    unchanged = db.get(Result, existing_id)
    assert unchanged.isExhibition is True
    assert unchanged.contentHash == case["canonical_hash"]
    assert (
        unchanged.sourceDocumentSha256,
        unchanged.parseJobId,
        unchanged.ingestionRunId,
        unchanged.parserVersion,
        unchanged.sessionId,
    ) == original_provenance


def test_canonical_reimport_does_not_rebind_sessionless_exhibition_variant(
    tmp_path: Path,
):
    db = _test_session()
    case = _pre_exhibition_case(db, tmp_path)
    existing = _source_identity_result(
        case,
        is_exhibition=True,
        content_hash=case["canonical_hash"],
    )
    existing.sessionId = None
    db.add(existing)
    db.flush()
    existing_id = existing.id
    original_provenance = (
        existing.sourceDocumentSha256,
        existing.parseJobId,
        existing.ingestionRunId,
        existing.parserVersion,
    )

    with pytest.raises(
        ValueError,
        match="Matching result content hash has conflicting evidence",
    ):
        _reimport_exhibition_case(db, case)

    assert db.query(Result).count() == 1
    unchanged = db.get(Result, existing_id)
    assert unchanged.isExhibition is True
    assert unchanged.contentHash == case["canonical_hash"]
    assert unchanged.sessionId is None
    assert (
        unchanged.sourceDocumentSha256,
        unchanged.parseJobId,
        unchanged.ingestionRunId,
        unchanged.parserVersion,
    ) == original_provenance


def test_pre_exhibition_upgrade_rejects_parse_job_for_different_raw_document(
    tmp_path: Path,
):
    db = _test_session()
    case = _pre_exhibition_case(db, tmp_path)
    other_raw = record_raw_document(
        db,
        file_bytes=b"%PDF-1.4\na different source\n%%EOF",
        filename="different-source.pdf",
        source_type="fixture",
        source_label="fixture",
        archive_root=tmp_path / "archive",
    )
    other_parse_job = record_parse_job(
        db,
        raw_document=other_raw,
        parser_name="hytek",
        parser_version="hytek-v1",
        status="succeeded",
        confidence_score=1.0,
        confidence_passed=True,
        events_count=1,
        individual_results_count=1,
        relay_results_count=0,
        unmatched_lines_count=0,
    )
    existing = _source_identity_result(case)
    existing.parseJobId = other_parse_job.id
    db.add(existing)
    db.flush()
    existing_id = existing.id

    with pytest.raises(
        ValueError,
        match="Current sourced result evidence conflicts with parsed source",
    ):
        _reimport_exhibition_case(db, case)

    assert db.query(Result).count() == 1
    unchanged = db.get(Result, existing_id)
    assert unchanged.isExhibition is False
    assert unchanged.contentHash == case["pre_exhibition_hash"]
    assert unchanged.parseJobId == other_parse_job.id
    assert unchanged.sourceDocumentSha256 == case["raw"].sha256


def test_pre_exhibition_upgrade_rejects_parse_job_parser_version_mismatch(
    tmp_path: Path,
):
    db = _test_session()
    case = _pre_exhibition_case(db, tmp_path)
    existing = _source_identity_result(case)
    existing.parserVersion = "hytek-v0"
    db.add(existing)
    db.flush()
    existing_id = existing.id

    with pytest.raises(
        ValueError,
        match="Current sourced result evidence conflicts with parsed source",
    ):
        _reimport_exhibition_case(db, case)

    assert db.query(Result).count() == 1
    unchanged = db.get(Result, existing_id)
    assert unchanged.isExhibition is False
    assert unchanged.contentHash == case["pre_exhibition_hash"]
    assert unchanged.parseJobId == case["old_parse_job"].id
    assert unchanged.parserVersion == "hytek-v0"


@pytest.mark.parametrize(
    ("status", "confidence_passed"),
    [("failed", True), ("succeeded", False)],
)
def test_pre_exhibition_upgrade_requires_successful_confidence_passed_parse_job(
    tmp_path: Path,
    status: str,
    confidence_passed: bool,
):
    db = _test_session()
    case = _pre_exhibition_case(db, tmp_path)
    existing = _source_identity_result(case)
    case["old_parse_job"].status = status
    case["old_parse_job"].confidencePassed = confidence_passed
    db.add(existing)
    db.flush()
    existing_id = existing.id

    with pytest.raises(
        ValueError,
        match="Current sourced result evidence conflicts with parsed source",
    ):
        _reimport_exhibition_case(db, case)

    assert db.query(Result).count() == 1
    unchanged = db.get(Result, existing_id)
    assert unchanged.isExhibition is False
    assert unchanged.contentHash == case["pre_exhibition_hash"]
    assert unchanged.parseJobId == case["old_parse_job"].id


def test_pre_exhibition_upgrade_rejects_inconsistent_ingestion_run_provenance(
    tmp_path: Path,
):
    db = _test_session()
    case = _pre_exhibition_case(db, tmp_path)
    existing = _source_identity_result(case)
    existing.ingestionRunId = case["reimport_ingestion_run"].id
    db.add(existing)
    db.flush()
    existing_id = existing.id

    with pytest.raises(
        ValueError,
        match="Current sourced result evidence conflicts with parsed source",
    ):
        _reimport_exhibition_case(db, case)

    assert db.query(Result).count() == 1
    unchanged = db.get(Result, existing_id)
    assert unchanged.isExhibition is False
    assert unchanged.contentHash == case["pre_exhibition_hash"]
    assert unchanged.ingestionRunId == case["reimport_ingestion_run"].id


def test_pre_exhibition_upgrade_rejects_conflicting_result_evidence(tmp_path: Path):
    db = _test_session()
    case = _pre_exhibition_case(db, tmp_path)
    existing = _source_identity_result(case)
    existing.seedTime = "conflicting-seed-time"
    db.add(existing)
    db.flush()

    with pytest.raises(
        ValueError,
        match="Current sourced result evidence conflicts with parsed source",
    ):
        _reimport_exhibition_case(db, case)

    assert db.query(Result).count() == 1
    assert existing.isExhibition is False
    assert existing.contentHash == case["pre_exhibition_hash"]
    assert existing.seedTime == "conflicting-seed-time"


def test_pre_exhibition_upgrade_rejects_ambiguous_source_identity(tmp_path: Path):
    db = _test_session()
    case = _pre_exhibition_case(db, tmp_path)
    first = _source_identity_result(case)
    second = _source_identity_result(case, content_hash="second-source-identity-hash")
    db.add_all([first, second])
    db.flush()

    with pytest.raises(
        ValueError,
        match="Multiple source-identity results matched one sourced session performance",
    ):
        _reimport_exhibition_case(db, case)

    assert db.query(Result).count() == 2
    assert first.isExhibition is False
    assert second.isExhibition is False
    assert first.contentHash == case["pre_exhibition_hash"]
    assert second.contentHash == "second-source-identity-hash"


def test_pre_exhibition_upgrade_rejects_current_and_legacy_source_ambiguity(
    tmp_path: Path,
):
    db = _test_session()
    case = _pre_exhibition_case(db, tmp_path)
    current = _source_identity_result(case)
    legacy = _source_identity_result(case, content_hash="legacy-source-identity-hash")
    legacy.sessionId = None
    db.add_all([current, legacy])
    db.flush()

    with pytest.raises(ValueError, match="Multiple .* results matched one sourced"):
        _reimport_exhibition_case(db, case)

    assert db.query(Result).count() == 2
    assert current.isExhibition is False
    assert legacy.isExhibition is False
    assert current.contentHash == case["pre_exhibition_hash"]
    assert legacy.contentHash == "legacy-source-identity-hash"
    assert current.sessionId == case["session"].id
    assert legacy.sessionId is None


def test_pre_exhibition_upgrade_rejects_wrong_session_source_identity(
    tmp_path: Path,
):
    db = _test_session()
    case = _pre_exhibition_case(db, tmp_path)
    wrong_session = upsert_competition_hierarchy(
        db,
        source_key="https://example.test/ssci-2026/",
        competition_title="Singapore Short Course Invitational 2026",
        parsed=_parsed(
            "Singapore Short Course Invitational 2026",
            "1/6/2026 to 2/6/2026",
            1,
            1,
        ),
        legacy_meet=case["meet"],
    )
    misplaced = _source_identity_result(case)
    misplaced.sessionId = wrong_session.id
    db.add(misplaced)
    db.flush()

    with pytest.raises(
        ValueError,
        match="Sourced result session conflicts with parsed source",
    ):
        _reimport_exhibition_case(db, case)

    assert db.query(Result).count() == 1
    assert misplaced.sessionId == wrong_session.id
    assert misplaced.isExhibition is False
    assert misplaced.contentHash == case["pre_exhibition_hash"]


def test_pre_exhibition_upgrade_rejects_legacy_source_evidence_conflict(
    tmp_path: Path,
):
    db = _test_session()
    case = _pre_exhibition_case(db, tmp_path)
    legacy = _source_identity_result(case)
    legacy.sessionId = None
    db.add(legacy)
    db.flush()

    with pytest.raises(
        ValueError,
        match="Legacy sourced result evidence conflicts with parsed source",
    ):
        _reimport_exhibition_case(db, case)

    assert db.query(Result).count() == 1
    assert legacy.sessionId is None
    assert legacy.isExhibition is False
    assert legacy.contentHash == case["pre_exhibition_hash"]


def test_canonical_reimport_never_downgrades_sourced_exhibition_result(
    tmp_path: Path,
):
    db = _test_session()
    case = _pre_exhibition_case(db, tmp_path)
    existing = _source_identity_result(
        case,
        is_exhibition=True,
        content_hash=case["canonical_hash"],
    )
    db.add(existing)
    db.flush()
    case["source"].is_exhibition = False

    with pytest.raises(
        ValueError,
        match="Current sourced result evidence conflicts with parsed source",
    ):
        _reimport_exhibition_case(db, case)

    assert db.query(Result).count() == 1
    assert existing.isExhibition is True
    assert existing.contentHash == case["canonical_hash"]


def test_pre_exhibition_upgrade_does_not_reconcile_unsourced_result(tmp_path: Path):
    db = _test_session()
    case = _pre_exhibition_case(db, tmp_path)
    unsourced = _source_identity_result(case, sourced=False)
    db.add(unsourced)
    db.flush()
    unsourced_id = unsourced.id

    processed = _reimport_exhibition_case(db, case)
    db.flush()

    assert processed[0] == 1
    assert processed[2] == 0
    assert db.query(Result).count() == 2
    unchanged = db.get(Result, unsourced_id)
    assert unchanged.isExhibition is False
    assert unchanged.contentHash == case["pre_exhibition_hash"]
    imported = db.query(Result).filter(Result.id != unsourced_id).one()
    assert imported.isExhibition is True
    assert imported.contentHash == case["canonical_hash"]
    assert imported.sourceDocumentSha256 == case["raw"].sha256


@pytest.mark.parametrize("missing_provenance", ["parseJobId", "ingestionRunId", "parserVersion"])
def test_pre_exhibition_upgrade_rejects_incomplete_provenance(
    tmp_path: Path,
    missing_provenance: str,
):
    db = _test_session()
    case = _pre_exhibition_case(db, tmp_path)
    incomplete = _source_identity_result(case)
    setattr(incomplete, missing_provenance, None)
    db.add(incomplete)
    db.flush()

    with pytest.raises(
        ValueError,
        match="Current sourced result evidence conflicts with parsed source",
    ):
        _reimport_exhibition_case(db, case)

    assert db.query(Result).count() == 1
    assert incomplete.isExhibition is False
    assert incomplete.contentHash == case["pre_exhibition_hash"]
    assert getattr(incomplete, missing_provenance) is None


def test_sourced_legacy_result_conflict_fails_instead_of_rebinding(tmp_path: Path):
    db = _test_session()
    meet = Meet(name="56th SNAG Seniors", startDate=datetime(2026, 3, 17))
    swimmer = Swimmer(name="Example, Athlete", age=19, team="Example Club")
    db.add_all([meet, swimmer])
    db.flush()
    parsed = _parsed("56th SNAG Seniors", "17/3/2026 to 22/3/2026", 1, 1)
    session = upsert_competition_hierarchy(
        db,
        source_key="https://example.test/56th-snag-2026/",
        competition_title="56th SNAG 2026",
        parsed=parsed,
        legacy_meet=meet,
    )
    raw = record_raw_document(
        db,
        file_bytes=b"%PDF-1.4\nlegacy conflict\n%%EOF",
        filename="legacy.pdf",
        source_type="fixture",
        source_label="fixture",
        archive_root=tmp_path / "archive",
    )
    legacy = Result(
        swimmerId=swimmer.id,
        meetId=meet.id,
        event="Men 50 LC Meter Freestyle",
        time="23.50",
        seedTime="stale",
        placement=99,
        round="Timed Final",
        swimDate=datetime(2026, 3, 17),
        contentHash="legacy-conflict",
        rawSwimmerName="Example, Athlete",
        rawTeamName="Example Club",
        sourceDocumentSha256=raw.sha256,
        sourceEventNumber="1",
    )
    db.add(legacy)
    db.flush()

    with pytest.raises(ValueError, match="Legacy sourced result evidence conflicts"):
        _process_parsed_meet(
            parsed,
            meet,
            datetime(2026, 3, 17),
            db,
            raw_document=raw,
            competition_session=session,
        )

    assert db.query(Result).count() == 1
    assert legacy.sessionId is None
    assert legacy.contentHash == "legacy-conflict"


def test_parser_output_populates_rebuildable_competition_database(tmp_path: Path):
    db = _test_session()
    juniors = _parsed("56th SNAG Juniors", "13/3/2026 to 15/3/2026", 1, 1)
    seniors = _parsed("56th SNAG Seniors", "17/3/2026 to 22/3/2026", 1, 1)
    seniors.events[0].results[0].is_exhibition = True
    juniors.events.append(ParsedEvent(
        event_number="201",
        event_name="Girls 13-14 4x50 LC Meter Freestyle Relay",
        gender="Girls",
        age_group="13-14",
        distance=200,
        stroke="Freestyle Relay",
        course="LC",
        time_standard=None,
        time_type="Finals Time",
        is_relay=True,
        relay_results=[ParsedRelayResult(
            team_name="Test Aquatics",
            relay_letter="A",
            placement=1,
            seed_time="2:00.00",
            finals_time="1:58.00",
            time_type="Finals Time",
            is_dq=False,
            legs=[
                ParsedRelayLeg(leg_number=1, name="Example, Athlete", is_guest=False, age=14),
                ParsedRelayLeg(leg_number=2, name="LEG, Two", is_guest=False, age=14),
            ],
        )],
    ))

    documents = []
    for filename, parsed in (
        ("juniors-day-1-session-1.pdf", juniors),
        ("seniors-day-1-session-1.pdf", seniors),
    ):
        content = f"%PDF-1.4\n{filename}\n%%EOF".encode()
        documents.append(ParsedCompetitionDocument(
            filename=filename,
            source_url=f"https://example.test/{filename}",
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            parsed=parsed,
            parser_name="hytek",
            parser_version="hytek-v2",
            confidence_score=1.0,
        ))

    first = import_parsed_competition_documents(
        db,
        source_key="HTTPS://EXAMPLE.TEST/56th-snag-2026/#results",
        competition_title="56th SNAG 2026",
        documents=documents,
        archive_root=tmp_path / "archive",
    )
    second = import_parsed_competition_documents(
        db,
        source_key="https://example.test/56th-snag-2026",
        competition_title="56th SNAG 2026",
        documents=documents,
        archive_root=tmp_path / "archive",
    )

    assert first.results_inserted == 3
    assert first.swimmers_created == 3
    assert first.duplicates_skipped == 0
    assert second.results_inserted == 0
    assert second.duplicates_skipped == 3
    assert db.query(CompetitionEdition).count() == 1
    assert db.query(CompetitionSegment).count() == 2
    assert db.query(CompetitionSession).count() == 2
    assert db.query(Meet).count() == 2
    assert db.query(Result).count() == 2
    assert db.query(Result).filter(Result.isExhibition.is_(True)).count() == 1
    assert db.query(Swimmer).count() == 3
    assert all(result.sessionId is not None for result in db.query(Result).all())
    assert {run.inputScope for run in db.query(IngestionRun).all()} == {
        "competition:https://example.test/56th-snag-2026"
    }
    assert {ref.sourcePageUrl for ref in db.query(SourceReference).all()} == {
        "https://example.test/56th-snag-2026"
    }


def test_process_preserves_row_level_round_and_result_status():
    db = _test_session()
    meet = Meet(name="Round Meet", startDate=datetime(2026, 6, 1))
    db.add(meet)
    db.flush()
    parsed, confidence = parse_hytek_text(["""Round Meet - 1/6/2026
Results - Day 1 Session 1
Event 1 Men 50 LC Meter Freestyle
Name Age Team Seed Time Prelim Time
1 Example, Athlete 20 Example Club 24.00 23.50
Event 1 Men 50 LC Meter Freestyle A - Final
Name Age Team Prelim Time Finals Time
--- Example, Athlete 20 Example Club 23.50 DQ
SW 4.4 Starting before the starting signal
Event 2 Men 100 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Example, Athlete 20 Example Club 52.00 51.00"""])
    assert confidence.passed

    inserted, _created, _skipped, errors, _duplicates = _process_parsed_meet(
        parsed,
        meet,
        datetime(2026, 6, 1),
        db,
    )

    assert errors == []
    assert inserted == 3
    rows = db.query(Result).order_by(Result.id).all()
    assert [(row.round, row.resultStatus) for row in rows] == [
        ("Prelim", "finished"),
        ("Final", "dq"),
        ("Timed Final", "finished"),
    ]


def test_result_identity_distinguishes_official_no_swim_statuses():
    shared = {
        "meet_id": 1,
        "event": "Men 200 LC Meter Freestyle",
        "swimmer_name": "Example, Athlete",
        "team": "Example Club",
        "round_name": "Prelim",
        "time": None,
        "age": 20,
        "session_id": 1,
        "swim_date": datetime(2026, 6, 1),
        "source_event_number": "1",
    }

    assert _compute_result_hash(**shared, status="ns") != _compute_result_hash(**shared, status="dns")


def test_matching_relay_content_hash_rejects_changed_source_evidence():
    db = _test_session()
    meet = Meet(name="Relay Evidence", startDate=datetime(2026, 6, 1))
    db.add(meet)
    db.flush()
    parsed = parse_hytek_text(["""Relay Evidence - 1/6/2026
Results - Day 1 Session 1
Event 10 Men 200 LC Meter Freestyle Relay
Team Relay Seed Time Finals Time
1 Example Club A 1:42.00 1:41.00"""])[0]

    _process_parsed_meet(parsed, meet, datetime(2026, 6, 1), db)
    parsed.events[0].relay_results[0].seed_time = "1:40.00"

    with pytest.raises(ValueError, match="Matching relay content hash has conflicting evidence"):
        _process_parsed_meet(parsed, meet, datetime(2026, 6, 1), db)

    assert db.query(RelayResult).one().seedTime == "1:42.00"


def test_manifest_loader_hash_verifies_and_parses_only_overall_results(tmp_path: Path):
    result_path = tmp_path / "result.pdf"
    result_bytes = b"%PDF-1.4\nresult\n%%EOF"
    result_path.write_bytes(result_bytes)
    ignored_path = tmp_path / "programme.pdf"
    ignored_path.write_bytes(b"%PDF-1.4\nprogramme\n%%EOF")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "source_page": "HTTPS://EXAMPLE.TEST/competition/?b=2&a=1#results",
        "files": [
            {
                "filename": result_path.name,
                "filename_saved": str(result_path),
                "url": "https://example.test/result.pdf",
                "category": "overall_results",
                "sha256": hashlib.sha256(result_bytes).hexdigest(),
            },
            {
                "filename": ignored_path.name,
                "filename_saved": str(ignored_path),
                "url": "https://example.test/programme.pdf",
                "category": "event_information",
                "sha256": hashlib.sha256(ignored_path.read_bytes()).hexdigest(),
            },
        ],
    }))
    parsed = _parsed("Example Segment", "1/6/2026", 1, 1)
    parsed_paths: list[Path] = []
    parsed_bytes: list[bytes] = []

    def fake_parser(path: Path):
        result_path.write_bytes(b"%PDF-1.4\nchanged after verification\n%%EOF")
        parsed_paths.append(path)
        parsed_bytes.append(path.read_bytes())
        confidence = ConfidenceReport(score=1.0, checks={"fixture": True})
        return parsed, confidence, "hytek", "hytek-v2"

    package = parse_competition_manifest(
        manifest_path,
        package_root=tmp_path,
        path_root=tmp_path,
        parser=fake_parser,
    )

    assert package.source_key == "https://example.test/competition?a=1&b=2"
    assert len(package.documents) == 1
    assert package.documents[0].sha256 == hashlib.sha256(result_bytes).hexdigest()
    assert parsed_bytes == [result_bytes]
    assert parsed_paths[0] != result_path
    assert parsed_paths[0].parent != tmp_path


def test_manifest_rejects_absolute_relative_and_symlink_escapes(tmp_path: Path):
    package_root = tmp_path / "package"
    package_root.mkdir()
    outside = tmp_path / "outside.pdf"
    content = b"%PDF-1.4\noutside\n%%EOF"
    outside.write_bytes(content)

    def write_manifest(saved: str) -> Path:
        path = package_root / "manifest.json"
        path.write_text(json.dumps({
            "source_page": "https://example.test/competition",
            "files": [{
                "filename": "outside.pdf",
                "saved": saved,
                "category": "overall_results",
                "sha256": hashlib.sha256(content).hexdigest(),
            }],
        }))
        return path

    for escaped in (str(outside), "../outside.pdf"):
        with pytest.raises(ValueError, match="outside package root"):
            parse_competition_manifest(
                write_manifest(escaped),
                package_root=package_root,
                path_root=package_root,
            )

    symlink = package_root / "linked.pdf"
    symlink.symlink_to(outside)
    with pytest.raises(ValueError, match="outside package root"):
        parse_competition_manifest(
            write_manifest("linked.pdf"),
            package_root=package_root,
            path_root=package_root,
        )


def test_content_hash_has_database_uniqueness_backstop():
    db = _test_session()
    meet = Meet(name="Uniqueness", startDate=datetime(2026, 1, 1))
    swimmer = Swimmer(name="Unique, Athlete", age=20, team="Example")
    db.add_all([meet, swimmer])
    db.flush()
    db.add(Result(swimmerId=swimmer.id, meetId=meet.id, event="50 Free", contentHash="same"))
    db.commit()
    db.add(Result(swimmerId=swimmer.id, meetId=meet.id, event="100 Free", contentHash="same"))
    with pytest.raises(IntegrityError):
        db.commit()
