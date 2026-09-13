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
from app.ingestion import record_raw_document
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
