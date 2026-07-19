"""Tests for shared ingestion primitives."""

from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.ingestion import (
    classify_document,
    is_import_eligible_document,
    record_parse_job,
    record_raw_document,
    start_ingestion_run,
)
from app.main import _process_parsed_meet
from app.models import IngestionRun, Meet, ParseJob, RawDocument, Result, SourceReference
from app.parsers.hytek import parse_hytek_text


def _test_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)()


def test_classify_sg_aquatics_pdf_filenames():
    assert classify_document("56th-snag-seniors-2026-results-day-1-session-1.pdf") == "overall_results"
    assert classify_document("56th-snag-juniors-2026-day-2-session-3-full-results.pdf") == "overall_results"
    assert classify_document("56th-snag-seniors-2026-start-list-day-1-session-1.pdf") == "start_list"
    assert classify_document("56th-snag-seniors-2026-results-day-1-finals-by-age-group.pdf") == "age_group_results"
    assert classify_document("56th-SNAG-Seniors-2026-Medal-tally-with-singaporean-swimmers-only.pdf") == "medal_tally"
    assert classify_document("56th-Singapore-National-Age-Group-Swimming-Cships-2026-5th-January-2026.pdf") == "event_information"
    assert classify_document("National-Championships-2026-results-day-1-session-1.pdf") == "overall_results"
    assert classify_document("Singapore-National-Age-Group-Swimming-2026-results-day-1-session-1.pdf") == "overall_results"
    assert classify_document("56th-Singapore-National-Age-Group-Swimming-Cships-2026-results-day-1-session-1.pdf") == "overall_results"


def test_import_eligibility_allows_results_and_generic_pdfs_only():
    assert is_import_eligible_document("overall_results") is True
    assert is_import_eligible_document("other_pdf") is True
    assert is_import_eligible_document("age_group_results") is False
    assert is_import_eligible_document("start_list") is False
    assert is_import_eligible_document("medal_tally") is False
    assert is_import_eligible_document("event_information") is False


def test_record_raw_document_archives_by_sha256_and_dedupes_source_references(tmp_path: Path):
    db = _test_session()
    pdf_bytes = b"%PDF-1.4\nminimal test pdf bytes\n%%EOF"

    first = record_raw_document(
        db,
        file_bytes=pdf_bytes,
        filename="result.pdf",
        source_type="user_upload",
        source_label="coach upload",
        archive_root=tmp_path,
    )
    second = record_raw_document(
        db,
        file_bytes=pdf_bytes,
        filename="result.pdf",
        source_type="user_upload",
        source_label="coach upload",
        archive_root=tmp_path,
    )
    third = record_raw_document(
        db,
        file_bytes=pdf_bytes,
        filename="result.pdf",
        source_type="sg-aquatics",
        source_label="56th SNAG 2026 page",
        archive_root=tmp_path,
        source_url="https://example.test/result.pdf",
        source_page_url="https://example.test/event",
    )

    db.flush()

    assert first.id == second.id == third.id
    assert db.query(RawDocument).count() == 1
    assert db.query(SourceReference).count() == 2
    assert first.sha256
    assert first.storagePath == str(tmp_path / "sha256" / first.sha256[:2] / f"{first.sha256}.pdf")
    assert Path(first.storagePath).read_bytes() == pdf_bytes


def test_record_parse_job_and_ingestion_run_capture_counts(tmp_path: Path):
    db = _test_session()
    raw_document = record_raw_document(
        db,
        file_bytes=b"%PDF-1.4\nminimal test pdf bytes\n%%EOF",
        filename="result.pdf",
        source_type="user_upload",
        source_label="coach upload",
        archive_root=tmp_path,
    )
    ingestion_run = start_ingestion_run(
        db,
        mode="preview",
        input_scope="upload:result.pdf",
        parser_version="hytek-v1",
    )
    parse_job = record_parse_job(
        db,
        raw_document=raw_document,
        parser_name="hytek",
        parser_version="hytek-v1",
        status="succeeded",
        confidence_score=1.0,
        confidence_passed=True,
        events_count=19,
        individual_results_count=863,
        relay_results_count=0,
        unmatched_lines_count=2,
    )
    db.flush()

    assert db.query(IngestionRun).count() == 1
    assert ingestion_run.mode == "preview"
    assert ingestion_run.status == "running"
    assert db.query(ParseJob).count() == 1
    assert parse_job.rawDocumentId == raw_document.id
    assert parse_job.parserName == "hytek"
    assert parse_job.confidenceScore == 100
    assert parse_job.eventsCount == 19
    assert parse_job.individualResultsCount == 863
    assert parse_job.unmatchedLinesCount == 2


def test_process_parsed_meet_writes_result_provenance(tmp_path: Path):
    db = _test_session()
    raw_document = record_raw_document(
        db,
        file_bytes=b"%PDF-1.4\nminimal test pdf bytes\n%%EOF",
        filename="56th-snag-seniors-2026-results-day-1-session-1.pdf",
        source_type="user_upload",
        source_label="coach upload",
        archive_root=tmp_path,
    )
    ingestion_run = start_ingestion_run(
        db,
        mode="append",
        input_scope="upload:56th-snag-seniors-2026-results-day-1-session-1.pdf",
        parser_version="hytek-v1",
    )
    parse_job = record_parse_job(
        db,
        raw_document=raw_document,
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
    meet = Meet(name="56th SNAG Seniors", startDate=datetime(2026, 3, 17), parserFormat="hytek")
    db.add(meet)
    db.flush()

    parsed, _confidence = parse_hytek_text([
        """Red Dot Aquatics HY-TEK's MEET MANAGER 8.0 - 9:37 AM 18/3/2026 Page 1
56th SNAG Seniors - 17/3/2026 to 22/3/2026
Results - Day 1 Session 1
Event 101 Boys 13-14 200 LC Meter IM
2:47.17 13-14 MTS MTS
Name Age Team Seed Time Prelim Time
Preliminaries
1 WU, Dylan Jiaxu 14 Pacific Swimming Club 2:19.50 2:18.62 qMTS"""
    ])

    results_count, *_ = _process_parsed_meet(
        parsed,
        meet,
        datetime(2026, 3, 17),
        db,
        raw_document=raw_document,
        parse_job=parse_job,
        ingestion_run=ingestion_run,
        parser_version="hytek-v1",
    )
    db.flush()

    assert results_count == 1
    result = db.query(Result).one()
    assert result.sourceDocumentSha256 == raw_document.sha256
    assert result.parseJobId == parse_job.id
    assert result.ingestionRunId == ingestion_run.id
    assert result.parserVersion == "hytek-v1"
    assert result.sourceEventNumber == "101"
