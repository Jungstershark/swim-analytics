"""Competition package resolution and relational hierarchy tests."""

from datetime import date, datetime
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.competition_packages import (
    CompetitionIdentity,
    evidence_key_for_document,
    parse_document_identity_payload,
    resolve_segment_identity,
    resolve_session_metadata,
    upsert_competition_hierarchy,
)
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
    SourceEvent,
    Swimmer,
)
from app.parsers.hytek import (
    ConfidenceReport,
    ParsedEvent,
    ParsedRelayLeg,
    ParsedRelayResult,
    parse_hytek_pdf,
    parse_hytek_text,
)
from app.source_monitoring import (
    DiscoveredDocument,
    DiscoveredEvent,
    ensure_default_sgaquatics_source,
    run_discovery_preview,
)
from app.package_import import (
    ParsedCompetitionDocument,
    _preflight_documents,
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


def test_hierarchy_import_does_not_claim_a_manifest_without_explicit_source_review():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)
    source_page = "https://example.test/imported-hierarchy/"
    discovered = DiscoveredEvent(
        title="Imported hierarchy",
        page_title="Imported hierarchy",
        url=source_page,
        readiness_status="results_available",
        pdf_count=1,
        result_pdf_count=1,
        category_counts={"overall_results": 1},
        documents=[
            DiscoveredDocument(
                url=f"{source_page}result.pdf",
                filename="result.pdf",
                category="overall_results",
            )
        ],
    )
    run_discovery_preview(db, rule.id, discover=lambda _rule: [discovered])
    event = db.query(SourceEvent).one()

    session = upsert_competition_hierarchy(
        db,
        source_key=source_page,
        competition_title="Imported hierarchy",
        parsed=_parsed("Imported hierarchy", "1/6/2026 to 1/6/2026", 1, 1),
    )

    edition = session.day.segment.competition
    assert edition.sourceEventId is None
    assert edition.sourceManifestSha256 is None
    assert edition.sourceManifestCaptureKind is None
    assert edition.sourceManifestCapturedAt is None


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


# ---------------------------------------------------------------------------
# Source-backed identity gaps in canonical packages: these sources print no
# competition identity at all, so the import preflight must fail closed instead
# of accepting an invented segment name, date range, or day/session.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]


def _canonical_result_document(manifest_rel: str, filename: str) -> ParsedCompetitionDocument:
    manifest_path = REPO_ROOT / manifest_rel
    if not manifest_path.exists():
        pytest.skip(f"Archived manifest not found: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = next(
        item
        for item in payload["files"]
        if item.get("category") == "overall_results" and item.get("filename") == filename
    )
    path = REPO_ROOT / str(record.get("filename_saved") or record["saved"])
    if not path.exists():
        pytest.skip(f"Archived source PDF not found: {path}")
    content = path.read_bytes()
    parsed, confidence = parse_hytek_pdf(path)
    return ParsedCompetitionDocument(
        filename=filename,
        source_url=str(record.get("url") or "") or None,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        parsed=parsed,
        parser_name="hytek",
        parser_version="hytek-v2",
        confidence_score=confidence.score,
        confidence_passed=confidence.passed,
        confidence_checks=dict(confidence.checks),
    )


def test_headerless_canonical_source_needs_caller_supplied_identity():
    """20th SNSC day-2 heats print no competition name/date on any page.

    The page is silent, so preflight refuses the document until the caller
    supplies the identity, then accepts that identity without rewriting it.
    """
    document = _canonical_result_document(
        "raw-data/sg-aquatics/events/20th-snsc-2025/manifest.json",
        "snsc2025-day-2-heats-results.pdf",
    )

    assert document.parsed.meet_name == ""
    assert document.parsed.meet_dates is None
    assert document.parsed.start_date is None
    assert document.confidence_passed is False

    # Without caller input the identity checks fail, so the import is refused.
    with pytest.raises(ValueError, match="Parser confidence failed"):
        _preflight_documents([document])

    identity = CompetitionIdentity(
        title="20th SNSC 2025",
        start_date=date(2025, 5, 31),
        end_date=date(2025, 6, 3),
    )
    _preflight_documents([document], identity=identity)


def test_segment_identity_requires_a_name_from_the_page_or_the_caller():
    """A sheet that prints no name is importable only when the caller names it."""
    parsed, _confidence = parse_hytek_text(["""
Results - Day 1 Session 1
Event 1 Men 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Example, Athlete 20 Example Club 24.00 23.50"""])

    with pytest.raises(ValueError, match="Competition name is required"):
        resolve_segment_identity(parsed)

    name, start_date, end_date, source = resolve_segment_identity(
        parsed,
        CompetitionIdentity(
            title="Example Meet", start_date=date(2026, 6, 1), end_date=date(2026, 6, 2)
        ),
    )

    assert name == "Example Meet"
    assert (start_date, end_date) == (date(2026, 6, 1), date(2026, 6, 2))
    assert source == "operator"


def test_sessionless_canonical_source_imports_without_a_session_header():
    """SAQ ETP's single report prints no `Results - Day N Session N` line.

    Day/session are optional metadata, so the document passes preflight on the
    identity it does print. Nothing invents a session header.
    """
    document = _canonical_result_document(
        "raw-data/sg-aquatics/events/saq-etp-championships-2026/manifest.json",
        "saq-etp-championships-2026-full-results.pdf",
    )

    assert document.parsed.meet_name == "SAQ Emerging Talents Championships 2026"
    assert document.parsed.day_number is None
    assert document.parsed.session_number is None

    _preflight_documents([document])


def test_caller_supplied_dates_must_match_a_page_that_prints_them():
    """A supplied *segment* range that contradicts the page fails closed.

    A package (umbrella) range is wider by nature, so the printed per-segment
    range simply wins there instead of being read as a contradiction.
    """
    document = _canonical_result_document(
        "raw-data/sg-aquatics/events/saq-etp-championships-2026/manifest.json",
        "saq-etp-championships-2026-full-results.pdf",
    )

    assert document.parsed.start_date == date(2026, 5, 31)

    with pytest.raises(ValueError, match="Competition dates conflict"):
        _preflight_documents(
            [document],
            identity=CompetitionIdentity(
                title="SAQ Emerging Talents Championships 2026",
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 2),
                scope="segment",
            ),
        )

    # The umbrella range may be wider than the printed segment range ...
    _preflight_documents(
        [document],
        identity=CompetitionIdentity(
            title="SAQ Emerging Talents Championships 2026",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 6, 30),
        ),
    )

    # ... but it still has to contain it.
    with pytest.raises(ValueError, match="falls outside the supplied package range"):
        _preflight_documents(
            [document],
            identity=CompetitionIdentity(
                title="SAQ Emerging Talents Championships 2026",
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 2),
            ),
        )

    name, start_date, end_date, source = resolve_segment_identity(
        document.parsed,
        CompetitionIdentity(
            title="SAQ Emerging Talents Championships 2026",
            start_date=date(2026, 5, 31),
            end_date=date(2026, 5, 31),
        ),
    )

    assert name == "SAQ Emerging Talents Championships 2026"
    assert (start_date, end_date) == (date(2026, 5, 31), date(2026, 5, 31))
    assert source == "printed"


def test_sessionless_document_imports_and_stores_a_derived_session(tmp_path: Path):
    """A sheet with no Day N Session N line must import, not just pass preflight.

    Regression guard for the gap between validation and writing: the sheet's
    NULL numbering has to survive the insert (nothing is invented to satisfy a
    NOT NULL column) and be recorded as derived, not as a printed header.
    """
    db = _test_session()
    parsed, confidence = parse_hytek_text(["""SAQ Emerging Talents Championships 2026 - 31/5/2026
Results
Event 1 Mixed 10 Year Olds 50 SC Meter Butterfly
Name Age Team Seed Time Finals Time
1 Example, Athlete 10 Example Club 34.42 34.02"""])
    assert parsed.day_number is None
    assert parsed.session_number is None

    content = b"%PDF-1.4\nsessionless\n%%EOF"
    document = ParsedCompetitionDocument(
        filename="sessionless.pdf",
        source_url="https://example.test/sessionless.pdf",
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        parsed=parsed,
        parser_name="hytek",
        parser_version="hytek-v3",
        confidence_score=confidence.score,
        confidence_passed=confidence.passed,
        confidence_checks=dict(confidence.checks),
    )

    summary = import_parsed_competition_documents(
        db,
        source_key="https://example.test/saq-etp",
        competition_title="SAQ Emerging Talents Championships 2026",
        documents=[document],
        archive_root=tmp_path / "archive",
    )

    assert summary.results_inserted == 1
    sessions = db.query(CompetitionSession).all()
    assert len(sessions) == 1
    # Nothing is invented: the numbers stay NULL and the sheet is identified by
    # its own content hash.
    assert sessions[0].sessionNumber is None
    assert sessions[0].sourceDocumentSha == document.sha256
    assert sessions[0].resolutionStatus == "derived"
    assert sessions[0].day.dayNumber is None
    assert sessions[0].day.resolutionStatus == "derived"
    assert db.query(Result).count() == 1

    # Re-importing the same sheet must find the same session and day again.
    import_parsed_competition_documents(
        db,
        source_key="https://example.test/saq-etp",
        competition_title="SAQ Emerging Talents Championships 2026",
        documents=[document],
        archive_root=tmp_path / "archive",
    )
    assert db.query(CompetitionSession).count() == 1
    assert db.query(CompetitionDay).count() == 1


def test_identity_supplied_import_still_requires_the_other_critical_checks(tmp_path: Path):
    """Caller identity must not paper over a missing or failed critical check."""
    db = _test_session()
    parsed, confidence = parse_hytek_text(["""Headerless Meet - 1/6/2026
Results - Day 1 Session 1
Event 1 Men 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Example, Athlete 20 Example Club 24.00 23.50"""])
    content = b"%PDF-1.4\nno-checks\n%%EOF"

    def build(checks: dict[str, bool], *, passed: bool = True) -> ParsedCompetitionDocument:
        return ParsedCompetitionDocument(
            filename="no-checks.pdf",
            source_url="https://example.test/no-checks.pdf",
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            parsed=parsed,
            parser_name="hytek",
            parser_version="hytek-v3",
            confidence_score=1.0,
            confidence_passed=passed,
            confidence_checks=checks,
        )

    identity = CompetitionIdentity(
        title="Headerless Meet", start_date=date(2026, 6, 1), end_date=date(2026, 6, 1)
    )

    # No named report and the parser did not pass: the import is refused.
    with pytest.raises(ValueError, match="Parser confidence failed"):
        _preflight_documents([build({}, passed=False)], identity=identity)

    # A non-identity critical check that fails still blocks, even with identity.
    with pytest.raises(ValueError, match="Parser confidence failed"):
        _preflight_documents(
            [build({**dict(confidence.checks), "relay_leg_integrity": False})],
            identity=identity,
        )

    _preflight_documents([build(dict(confidence.checks))], identity=identity)


def test_document_identity_payload_is_validated():
    identity = parse_document_identity_payload({
        "documents": [
            {
                "filename": "day-2-heats.pdf",
                "segment_name": "20th SNSC 2025",
                "start_date": "2025-05-31",
                "end_date": "2025-06-03",
            }
        ]
    })

    assert set(identity) == {"day-2-heats.pdf"}
    entry = identity["day-2-heats.pdf"]
    assert entry.title == "20th SNSC 2025"
    assert entry.scope == "segment"
    assert (entry.start_date, entry.end_date) == (date(2025, 5, 31), date(2025, 6, 3))

    for payload in (
        {},
        {"documents": []},
        {"documents": [{"segment_name": "No filename"}]},
        {"documents": [{"filename": "a.pdf"}]},
        {"documents": [{"filename": "a.pdf", "segment_name": "X", "start_date": "nope"}]},
        {"documents": [{"filename": "a.pdf", "segment_name": "X"}] * 2},
    ):
        with pytest.raises(ValueError):
            parse_document_identity_payload(payload)


def test_document_identity_supplies_identity_for_a_silent_page():
    """The rebuild path can name a document the page does not name itself."""
    document = _canonical_result_document(
        "raw-data/sg-aquatics/events/20th-snsc-2025/manifest.json",
        "snsc2025-day-2-heats-results.pdf",
    )
    per_document = {
        document.filename: CompetitionIdentity(
            title="20th SNSC 2025",
            start_date=date(2025, 5, 31),
            end_date=date(2025, 6, 3),
            scope="segment",
        )
    }

    with pytest.raises(ValueError, match="Parser confidence failed"):
        _preflight_documents([document])

    _preflight_documents([document], document_identity=per_document)

    # A caller-supplied segment name that contradicts the page fails closed.
    saq = _canonical_result_document(
        "raw-data/sg-aquatics/events/saq-etp-championships-2026/manifest.json",
        "saq-etp-championships-2026-full-results.pdf",
    )
    with pytest.raises(ValueError, match="Segment name conflict"):
        _preflight_documents(
            [saq],
            document_identity={
                saq.filename: CompetitionIdentity(
                    title="Some Other Meet",
                    start_date=date(2026, 5, 31),
                    end_date=date(2026, 5, 31),
                    scope="segment",
                )
            },
        )


def test_evidence_key_separates_rounds_and_normalises_names():
    heats, _ = parse_hytek_text(["""Example Meet - 1/6/2026 to 2/6/2026
Results - Day 1 Session 1
Event 1 Men 50 LC Meter Freestyle
Name Age Team Seed Time Prelim Time
1 Example, Athlete 20 Example Club 24.00 23.50"""])
    finals, _ = parse_hytek_text(["""Example Meet - 1/6/2026 to 2/6/2026
Results - Day 1 Session 2
Event 1 Men 50 LC Meter Freestyle
Name Age Team Prelim Time Finals Time
1 Example, Athlete 20 Example Club 23.50 23.40"""])

    heats_key = evidence_key_for_document(heats, "Example Meet")
    finals_key = evidence_key_for_document(finals, "Example Meet")

    # Heats and finals of the same day carry the same events in different rounds.
    assert heats_key != finals_key
    # Wording differences (case, spacing) are normalised away.
    assert heats_key == evidence_key_for_document(heats, "  example   meet ")


def test_import_script_exposes_document_identity_input(tmp_path: Path):
    """The rebuild CLI takes identity for documents whose pages print none."""
    import importlib.util

    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "import_archived_sgaquatics_event.py"
    )
    spec = importlib.util.spec_from_file_location(
        "import_archived_sgaquatics_event", script
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module._load_document_identity(None) is None

    identity_path = tmp_path / "identity.json"
    identity_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "filename": "day-2-heats.pdf",
                        "segment_name": "20th SNSC 2025",
                        "start_date": "2025-05-31",
                        "end_date": "2025-06-03",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    identity = module._load_document_identity(identity_path)
    assert identity["day-2-heats.pdf"].title == "20th SNSC 2025"
    assert identity["day-2-heats.pdf"].scope == "segment"


def _numbered_document(
    filename: str, parsed, sha: str | None = None
) -> ParsedCompetitionDocument:
    content = f"%PDF-1.4\n{filename}\n%%EOF".encode()
    return ParsedCompetitionDocument(
        filename=filename,
        source_url=f"https://example.test/{filename}",
        content=content,
        sha256=sha or hashlib.sha256(content).hexdigest(),
        parsed=parsed,
        parser_name="hytek",
        parser_version="hytek-v3",
        confidence_score=1.0,
        confidence_passed=True,
        confidence_checks={},
    )


_HEADERLESS_ONE = """SAQ Emerging Talents Championships 2026 - 31/5/2026
Results
Event 1 Mixed 10 Year Olds 50 SC Meter Butterfly
Name Age Team Seed Time Finals Time
1 Example, Athlete 10 Example Club 34.42 34.02"""

_HEADERLESS_TWO = """SAQ Emerging Talents Championships 2026 - 31/5/2026
Results
Event 1 Mixed 10 Year Olds 50 SC Meter Butterfly
Name Age Team Seed Time Finals Time
1 Example, Athlete 10 Example Club 34.42 34.02
Event 2 Girls 11 Year Olds 50 SC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Another, Swimmer 11 Example Club 33.00 32.50"""


def test_two_sessionless_documents_stay_two_sessions_in_either_order(tmp_path: Path):
    """Two sheets that print no numbering are two sessions, not one shared row.

    The session of an unnumbered sheet is its document identity, so import order
    must not change what gets stored.
    """
    one = _numbered_document("day-one.pdf", parse_hytek_text([_HEADERLESS_ONE])[0])
    two = _numbered_document("day-two.pdf", parse_hytek_text([_HEADERLESS_TWO])[0])

    for order in ((one, two), (two, one)):
        db = _test_session()
        import_parsed_competition_documents(
            db,
            source_key="https://example.test/saq-etp",
            competition_title="SAQ Emerging Talents Championships 2026",
            documents=list(order),
            archive_root=tmp_path / "archive",
        )

        sessions = db.query(CompetitionSession).all()
        assert len(sessions) == 2
        assert {session.sourceDocumentSha for session in sessions} == {
            one.sha256,
            two.sha256,
        }
        assert all(session.sessionNumber is None for session in sessions)
        assert db.query(CompetitionDay).count() == 1


def test_dropped_document_is_withdrawn_on_rebuild(tmp_path: Path):
    """A document removed from the package must not leave stale rows behind."""
    db = _test_session()
    one = _numbered_document("day-one.pdf", parse_hytek_text([_HEADERLESS_ONE])[0])
    two = _numbered_document("day-two.pdf", parse_hytek_text([_HEADERLESS_TWO])[0])

    import_parsed_competition_documents(
        db,
        source_key="https://example.test/saq-etp",
        competition_title="SAQ Emerging Talents Championships 2026",
        documents=[one, two],
        archive_root=tmp_path / "archive",
    )
    assert db.query(CompetitionSession).count() == 2
    assert db.query(Result).count() == 3

    summary = import_parsed_competition_documents(
        db,
        source_key="https://example.test/saq-etp",
        competition_title="SAQ Emerging Talents Championships 2026",
        documents=[one],
        archive_root=tmp_path / "archive",
    )

    assert summary.sessions_removed == 1
    sessions = db.query(CompetitionSession).all()
    assert len(sessions) == 1
    assert sessions[0].sourceDocumentSha == one.sha256
    assert db.query(Result).count() == 1


def test_partial_or_nonpositive_numbering_is_rejected(tmp_path: Path):
    """Day/session are both-or-neither, and positive when present."""
    import dataclasses

    db = _test_session()
    parsed = _parsed("Example Meet", "1/6/2026 to 2/6/2026", 1, 1)

    for day_number, session_number in ((1, None), (None, 1), (0, 1), (1, 0)):
        mutated = dataclasses.replace(
            parsed, day_number=day_number, session_number=session_number
        )
        with pytest.raises(
            ValueError, match="Partial Day/Session metadata|must be positive"
        ):
            upsert_competition_hierarchy(
                db,
                source_key="https://example.test/partial",
                competition_title="Example Meet",
                parsed=mutated,
                source_document_sha="c" * 64,
                evidence_key="d" * 64,
            )
        db.rollback()


def test_upgraded_numbered_session_acquires_document_identity(tmp_path: Path):
    """A row created before the identity columns existed must acquire them.

    Otherwise every rebuild keeps depending on printed numbering instead of the
    persisted document identity.
    """
    db = _test_session()
    document = _numbered_document(
        "numbered.pdf", _parsed("Example Meet", "1/6/2026 to 2/6/2026", 1, 1)
    )
    import_parsed_competition_documents(
        db,
        source_key="https://example.test/upgraded",
        competition_title="Example Meet",
        documents=[document],
        archive_root=tmp_path / "archive",
    )

    session = db.query(CompetitionSession).one()
    session.sourceDocumentSha = None
    session.sourceEvidenceKey = None
    db.commit()

    import_parsed_competition_documents(
        db,
        source_key="https://example.test/upgraded",
        competition_title="Example Meet",
        documents=[document],
        archive_root=tmp_path / "archive",
    )

    session = db.query(CompetitionSession).one()
    assert session.sourceDocumentSha == document.sha256
    assert session.sourceEvidenceKey is not None
    assert db.query(CompetitionSession).count() == 1
    assert db.query(CompetitionDay).count() == 1


def test_changed_evidence_for_the_same_document_is_rejected(tmp_path: Path):
    """A document whose parse output changes must not be silently rewritten."""
    db = _test_session()
    original = _numbered_document(
        "changed.pdf", _parsed("Example Meet", "1/6/2026 to 2/6/2026", 1, 1)
    )
    import_parsed_competition_documents(
        db,
        source_key="https://example.test/changed",
        competition_title="Example Meet",
        documents=[original],
        archive_root=tmp_path / "archive",
    )

    changed_parse, _confidence = parse_hytek_text(["""HY-TEK's MEET MANAGER 8.0 Page 1
Example Meet - 1/6/2026 to 2/6/2026
Results - Day 1 Session 1
Event 1 Men 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Different, Athlete 21 Other Club 25.00 24.90"""])
    changed = _numbered_document("changed.pdf", changed_parse, sha=original.sha256)

    with pytest.raises(ValueError, match="different evidence"):
        import_parsed_competition_documents(
            db,
            source_key="https://example.test/changed",
            competition_title="Example Meet",
            documents=[changed],
            archive_root=tmp_path / "archive",
        )


def test_changed_parse_of_a_second_document_feeding_a_printed_session_is_rejected(
    tmp_path: Path,
):
    """A printed session fed by two curated sheets tracks each sheet's parse.

    The row only stores the first document's sha, so provenance for the rest has
    to be recorded per document - otherwise a changed parse of the second sheet
    would slip past the change check.
    """
    db = _test_session()
    first_parsed, _ = parse_hytek_text(["""HY-TEK's MEET MANAGER 8.0 Page 1
Example Meet - 1/6/2026 to 2/6/2026
Results - Day 1 Session 1
Event 1 Men 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Keep, One 20 Club 24.00 23.00"""])
    second_parsed, _ = parse_hytek_text(["""HY-TEK's MEET MANAGER 8.0 Page 1
Example Meet - 1/6/2026 to 2/6/2026
Results - Day 1 Session 1
Event 2 Women 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Keep, Two 20 Club 25.00 24.00"""])
    first = _numbered_document("session-sheet-one.pdf", first_parsed)
    second = _numbered_document("session-sheet-two.pdf", second_parsed)

    import_parsed_competition_documents(
        db,
        source_key="https://example.test/shared-session",
        competition_title="Example Meet",
        documents=[first, second],
        archive_root=tmp_path / "archive",
    )

    session = db.query(CompetitionSession).one()
    assert session.sessionNumber == 1
    index = json.loads(session.sourceDocuments)
    assert {entry["sha"] for entry in index} == {first.sha256, second.sha256}

    # A changed parse of the *second* sheet must not slip past the check.
    changed_parsed, _ = parse_hytek_text(["""HY-TEK's MEET MANAGER 8.0 Page 1
Example Meet - 1/6/2026 to 2/6/2026
Results - Day 1 Session 1
Event 2 Women 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Keep, Two 20 Club 25.00 23.80"""])
    changed = _numbered_document(
        "session-sheet-two.pdf", changed_parsed, sha=second.sha256
    )

    with pytest.raises(ValueError, match="different evidence"):
        import_parsed_competition_documents(
            db,
            source_key="https://example.test/shared-session",
            competition_title="Example Meet",
            documents=[first, changed],
            archive_root=tmp_path / "archive",
        )


def test_overlapping_documents_must_agree_within_a_session():
    """Sheets may share a race; a same-session disagreement fails closed.

    A prelim result legitimately reprints on a later session's sheet (different
    day/session), so only documents claiming the same session must agree.
    """
    single, _ = parse_hytek_text(["""HY-TEK's MEET MANAGER 8.0 Page 1
Example Meet - 1/6/2026 to 2/6/2026
Results - Day 1 Session 1
Event 1 Men 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Keep, One 20 Club 24.00 23.00"""])
    # Same session, extra event so the document shape differs, same values.
    agreeing, _ = parse_hytek_text(["""HY-TEK's MEET MANAGER 8.0 Page 1
Example Meet - 1/6/2026 to 2/6/2026
Results - Day 1 Session 1
Event 1 Men 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Keep, One 20 Club 24.00 23.00
Event 2 Women 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Keep, Two 20 Club 25.00 24.00"""])
    # Same session and shape as `agreeing`, but a different time for the shared race.
    disagreeing, _ = parse_hytek_text(["""HY-TEK's MEET MANAGER 8.0 Page 1
Example Meet - 1/6/2026 to 2/6/2026
Results - Day 1 Session 1
Event 1 Men 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Keep, One 20 Club 24.00 22.50
Event 2 Women 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Keep, Two 20 Club 25.00 24.00"""])
    # A later session reprinting the same prelim result is not a conflict.
    reprinted, _ = parse_hytek_text(["""HY-TEK's MEET MANAGER 8.0 Page 1
Example Meet - 1/6/2026 to 2/6/2026
Results - Day 2 Session 4
Event 1 Men 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Keep, One 20 Club 24.00 22.90
Event 2 Women 50 LC Meter Freestyle
Name Age Team Seed Time Finals Time
1 Keep, Two 20 Club 25.00 24.00"""])

    doc_single = _numbered_document("sheet-single.pdf", single)

    _preflight_documents([doc_single, _numbered_document("sheet-agree.pdf", agreeing)])
    _preflight_documents([doc_single, _numbered_document("sheet-later.pdf", reprinted)])

    with pytest.raises(ValueError, match="different values for the same performance"):
        _preflight_documents(
            [doc_single, _numbered_document("sheet-disagree.pdf", disagreeing)]
        )


def test_rebuild_cli_forwards_document_identity(tmp_path: Path, monkeypatch):
    """`main()` must hand --identity to the importer, not merely parse it."""
    import importlib.util
    import sys
    from types import SimpleNamespace

    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "import_archived_sgaquatics_event.py"
    )
    spec = importlib.util.spec_from_file_location(
        "import_archived_sgaquatics_event_main", script
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    captured: dict = {}

    class _FakeSession:
        def close(self) -> None:
            pass

        def rollback(self) -> None:
            pass

    monkeypatch.setattr(module, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(module, "load_manifest_curation_policy", lambda *a, **k: object())
    monkeypatch.setattr(
        module,
        "parse_competition_manifest",
        lambda *a, **k: SimpleNamespace(source_key="pkg", documents=("doc",)),
    )

    def fake_import(db, **kwargs):
        from app.package_import import CompetitionImportSummary

        captured.update(kwargs)
        return CompetitionImportSummary(
            documents_imported=1,
            results_inserted=0,
            swimmers_created=0,
            duplicates_skipped=0,
            edition_id=7,
        )

    monkeypatch.setattr(module, "import_parsed_competition_documents", fake_import)

    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    identity_path = tmp_path / "identity.json"
    identity_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "filename": "day-2-heats.pdf",
                        "segment_name": "20th SNSC 2025",
                        "start_date": "2025-05-31",
                        "end_date": "2025-06-03",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "import_archived_sgaquatics_event.py",
            str(manifest),
            "--title",
            "20th SNSC 2025",
            "--identity",
            str(identity_path),
        ],
    )
    module.main()

    assert captured["document_identity"]["day-2-heats.pdf"].title == "20th SNSC 2025"
    assert captured["document_identity"]["day-2-heats.pdf"].scope == "segment"
    assert captured["competition_title"] == "20th SNSC 2025"
