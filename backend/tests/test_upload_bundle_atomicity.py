from __future__ import annotations

import io
import zipfile
from datetime import date, datetime

import pytest
from fastapi import HTTPException, UploadFile

from backend.app import main
from backend.app.models import Meet, ParseJob, RawDocument, Result, Swimmer
from backend.app.parsers.hytek import ConfidenceReport, ParsedEvent, ParsedMeet, ParsedResult
from pathlib import Path

from backend.tests.test_competition_packages import _test_session


def _parsed(meet_name: str, start: date, end: date) -> ParsedMeet:
    result = ParsedResult(
        placement=1,
        is_tied=False,
        name="Example, Athlete",
        is_guest=False,
        age=20,
        team="Example Club",
        seed_time="24.00",
        finals_time="23.50",
        time_type="Finals Time",
        is_dq=False,
        dq_code=None,
        dq_description=None,
        is_ns=False,
        qualifier=None,
        reaction_time=None,
    )
    event = ParsedEvent(
        event_number="1",
        event_name="Men 50 LC Meter Freestyle",
        gender="Men",
        age_group=None,
        distance=50,
        stroke="Freestyle",
        course="LC",
        time_standard=None,
        time_type="Finals",
        results=[result],
    )
    return ParsedMeet(
        meet_name=meet_name,
        meet_dates=f"{start:%d/%m/%Y} to {end:%d/%m/%Y}",
        start_date=start,
        end_date=end,
        session="Day 1 Session 1",
        day_number=1,
        session_number=1,
        events=[event],
    )


def _confidence() -> ConfidenceReport:
    checks = {
        "meet_name": True,
        "meet_dates": True,
        "metadata_consistent": True,
        "session_metadata": True,
        "positive_day_session": True,
        "has_events": True,
        "has_results": True,
        "valid_times": True,
        "relay_leg_integrity": True,
        "relay_leg_completeness": True,
        "line_coverage": True,
    }
    return ConfidenceReport(score=1.0, checks=checks, unmatched_lines=[])


def _zip_upload() -> UploadFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("juniors-results.pdf", b"%PDF junior")
        archive.writestr("seniors-results.pdf", b"%PDF senior")
    buffer.seek(0)
    return UploadFile(filename="mixed.zip", file=buffer)


def _install_mixed_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    juniors = _parsed("56th SNAG Juniors", date(2026, 3, 13), date(2026, 3, 15))
    seniors = _parsed("56th SNAG Seniors", date(2026, 3, 17), date(2026, 3, 22))

    def fake_detect(path):
        parsed = juniors if path.read_bytes() == b"%PDF junior" else seniors
        return parsed, _confidence(), "hytek"

    monkeypatch.setattr(main, "detect_and_parse", fake_detect)


def test_preview_tolerates_missing_dates_but_import_refuses_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Preview must report "dates required" instead of failing the whole request.

    A source that prints no dates and has no caller-supplied range still cannot
    be imported - only the preview is allowed to describe the gap.
    """
    dateless = _parsed("56th SNAG Juniors", date(2026, 3, 13), date(2026, 3, 15))
    dateless.start_date = None
    dateless.end_date = None
    dateless.meet_dates = None

    monkeypatch.setattr(
        main, "detect_and_parse", lambda path: (dateless, _confidence(), "hytek")
    )

    document = tmp_path / "dateless.pdf"
    document.write_bytes(b"%PDF junior")
    uploaded = main.UploadedPdf(
        path=document, filename="dateless.pdf", file_bytes=b"%PDF junior"
    )

    prepared, _skipped = main._prepare_upload_bundle([uploaded], None, preview=True)
    assert len(prepared) == 1
    assert prepared[0].meet_start is None
    assert prepared[0].meet_end is None

    with pytest.raises(main.HTTPException) as error:
        main._prepare_upload_bundle([uploaded], None)
    assert error.value.status_code == 422


def _install_same_segment_parser(monkeypatch: pytest.MonkeyPatch, *, reject_reparse: bool = False):
    day_one = _parsed("56th SNAG Seniors", date(2026, 3, 17), date(2026, 3, 22))
    day_two = _parsed("56th SNAG Seniors", date(2026, 3, 17), date(2026, 3, 22))
    day_two.session = "Day 2 Session 2"
    day_two.day_number = 2
    day_two.session_number = 2
    calls: dict[bytes, int] = {}

    def fake_detect(path):
        content = path.read_bytes()
        calls[content] = calls.get(content, 0) + 1
        if reject_reparse and calls[content] > 1:
            raise ValueError("prepared input was parsed again")
        parsed = day_one if content == b"%PDF junior" else day_two
        return parsed, _confidence(), "hytek"

    monkeypatch.setattr(main, "detect_and_parse", fake_detect)
    return calls


def test_upload_preview_exposes_individual_exhibition_provenance(monkeypatch):
    parsed = _parsed("Exhibition Meet", date(2026, 6, 1), date(2026, 6, 1))
    parsed.events[0].results[0].is_exhibition = True

    def fake_detect(_path):
        return parsed, _confidence(), "hytek"

    monkeypatch.setattr(main, "detect_and_parse", fake_detect)
    upload = UploadFile(filename="results.pdf", file=io.BytesIO(b"%PDF fixture"))

    response = main.upload_preview(upload)

    assert response.events[0].results[0].is_exhibition is True


def test_preview_and_confirm_reject_the_same_mixed_segment_bundle(monkeypatch):
    _install_mixed_parser(monkeypatch)
    with pytest.raises(HTTPException) as preview_error:
        main.upload_preview(_zip_upload())
    assert preview_error.value.status_code == 422
    assert "multiple competition segments" in str(preview_error.value.detail).lower()

    db = _test_session()
    with pytest.raises(HTTPException) as confirm_error:
        main.upload_results(_zip_upload(), replace=False, db=db)
    assert confirm_error.value.status_code == 422
    assert "multiple competition segments" in str(confirm_error.value.detail).lower()
    assert db.query(Meet).count() == 0
    assert db.query(Result).count() == 0


def test_replace_does_not_delete_existing_results_when_bundle_preflight_fails(monkeypatch):
    _install_mixed_parser(monkeypatch)
    db = _test_session()
    meet = Meet(name="56th SNAG Juniors", startDate=datetime(2026, 3, 13))
    swimmer = Swimmer(name="Existing, Athlete", age=20, team="Example Club")
    db.add_all([meet, swimmer])
    db.flush()
    existing = Result(
        swimmerId=swimmer.id,
        meetId=meet.id,
        event="Men 50 LC Meter Freestyle",
        time="23.00",
        round="Final",
        contentHash="existing-result",
    )
    db.add(existing)
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        main.upload_results(_zip_upload(), replace=True, db=db)

    assert exc_info.value.status_code == 422
    assert db.query(Result).count() == 1
    assert db.query(Result).one().contentHash == "existing-result"


def test_confirm_uses_each_prepared_parse_exactly_once(monkeypatch, tmp_path):
    calls = _install_same_segment_parser(monkeypatch, reject_reparse=True)
    monkeypatch.setattr(main, "RAW_ARCHIVE_ROOT", tmp_path / "archive")
    db = _test_session()

    response = main.upload_results(_zip_upload(), replace=False, db=db)

    assert response.success
    assert calls == {b"%PDF junior": 1, b"%PDF senior": 1}
    assert db.query(RawDocument).count() == 2
    assert db.query(ParseJob).count() == 2


def test_later_mutation_failure_rolls_back_replacement_and_archives(monkeypatch, tmp_path):
    _install_same_segment_parser(monkeypatch)
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(main, "RAW_ARCHIVE_ROOT", archive_root)
    db = _test_session()
    meet = Meet(
        name="56th SNAG Seniors",
        startDate=datetime(2026, 3, 17),
        endDate=datetime(2026, 3, 22),
    )
    swimmer = Swimmer(name="Existing, Athlete", age=20, team="Example Club")
    db.add_all([meet, swimmer])
    db.flush()
    db.add(Result(
        swimmerId=swimmer.id,
        meetId=meet.id,
        event="Men 50 LC Meter Freestyle",
        time="23.00",
        round="Final",
        contentHash="existing-result",
    ))
    db.commit()

    original_process = main._process_parsed_meet
    call_count = 0

    def fail_second_document(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("deterministic second-document failure")
        return original_process(*args, **kwargs)

    monkeypatch.setattr(main, "_process_parsed_meet", fail_second_document)

    with pytest.raises(RuntimeError, match="second-document failure"):
        main.upload_results(_zip_upload(), replace=True, db=db)

    assert db.query(Result).count() == 1
    assert db.query(Result).one().contentHash == "existing-result"
    assert db.query(RawDocument).count() == 0
    assert db.query(ParseJob).count() == 0
    assert list(archive_root.rglob("*.pdf")) == []
