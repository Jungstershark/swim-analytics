"""Validated parser-output to relational competition import boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Sequence
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.orm import Session

from .competition_packages import resolve_session_metadata, upsert_competition_hierarchy
from .ingestion import (
    cleanup_unledgered_archives,
    pdf_storage_path,
    record_parse_job,
    record_raw_document,
    start_ingestion_run,
)
from .main import _process_parsed_meet
from .models import Meet
from .package_curation import (
    PackageCurationPolicy,
    PackageCurationReport,
    apply_package_curation,
    select_manifest_records,
)
from .parsers.base import detect_parser
from .parsers.hytek import ConfidenceReport, ParsedMeet
from .source_monitoring import canonicalize_url


@dataclass(frozen=True)
class ParsedCompetitionDocument:
    filename: str
    source_url: str | None
    content: bytes
    sha256: str
    parsed: ParsedMeet
    parser_name: str
    parser_version: str
    confidence_score: float
    confidence_passed: bool = True
    unmatched_lines_count: int = 0
    curation_policy_id: str | None = None


@dataclass(frozen=True)
class ParsedCompetitionManifest:
    source_key: str
    documents: tuple[ParsedCompetitionDocument, ...]
    curation_report: PackageCurationReport | None = None


@dataclass(frozen=True)
class CompetitionImportSummary:
    documents_imported: int
    results_inserted: int
    swimmers_created: int
    duplicates_skipped: int
    edition_id: int


ManifestParser = Callable[[Path], tuple[ParsedMeet, ConfidenceReport, str, str]]


def _default_manifest_parser(path: Path) -> tuple[ParsedMeet, ConfidenceReport, str, str]:
    detection = detect_parser(path)
    parsed, confidence = detection.parser.parse(path)
    return parsed, confidence, detection.format_name, detection.parser_version


def _resolve_manifest_path(*, package_root: Path, path_root: Path, raw_path: str) -> Path:
    allowed_root = package_root.resolve(strict=True)
    supplied = Path(raw_path)
    candidate = supplied.resolve(strict=True) if supplied.is_absolute() else (path_root / supplied).resolve(strict=True)
    if not candidate.is_relative_to(allowed_root):
        raise ValueError(f"Manifest file is outside package root: {raw_path}")
    if not candidate.is_file():
        raise ValueError(f"Manifest path is not a regular file: {raw_path}")
    return candidate


def _canonical_source_key(raw_value: object) -> str:
    source_key = canonicalize_url(str(raw_value or ""))
    parsed = urlsplit(source_key)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Competition manifest has an invalid source_page URL")
    return source_key


def _canonical_optional_source_url(raw_value: object) -> str | None:
    if raw_value in {None, ""}:
        return None
    source_url = canonicalize_url(str(raw_value))
    parsed = urlsplit(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Competition manifest has an invalid document URL")
    return source_url


def parse_competition_manifest(
    manifest_path: Path,
    *,
    package_root: Path | None = None,
    path_root: Path | None = None,
    parser: ManifestParser = _default_manifest_parser,
    curation_policy: PackageCurationPolicy | None = None,
) -> ParsedCompetitionManifest:
    """Hash-verify, parse, and optionally curate one competition manifest."""
    manifest_path = manifest_path.resolve(strict=True)
    allowed_root = (package_root or manifest_path.parent).resolve(strict=True)
    if not manifest_path.is_relative_to(allowed_root):
        raise ValueError("Competition manifest is outside package root")
    resolution_root = (path_root or allowed_root).resolve(strict=True)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_key = _canonical_source_key(payload.get("source_page"))
    records = (
        select_manifest_records(payload, curation_policy)
        if curation_policy is not None
        else tuple(
            record
            for record in payload.get("files", [])
            if record.get("category") == "overall_results"
        )
    )

    documents: list[ParsedCompetitionDocument] = []
    for record in records:
        raw_path = record.get("filename_saved") or record.get("saved")
        if not raw_path:
            raise ValueError(f"Overall-result manifest record has no saved path: {record}")
        path = _resolve_manifest_path(
            package_root=allowed_root,
            path_root=resolution_root,
            raw_path=str(raw_path),
        )
        content = path.read_bytes()
        actual_sha = hashlib.sha256(content).hexdigest()
        expected_sha = str(record.get("sha256") or "")
        if actual_sha != expected_sha:
            raise ValueError(f"SHA-256 mismatch for manifest file {path}")

        safe_name = Path(str(record.get("filename") or path.name)).name
        with TemporaryDirectory(prefix="swim-competition-parse-") as temp_dir:
            verified_path = Path(temp_dir) / safe_name
            verified_path.write_bytes(content)
            verified_path.chmod(0o400)
            parsed, confidence, parser_name, parser_version = parser(verified_path)
        documents.append(ParsedCompetitionDocument(
            filename=str(record.get("filename") or path.name),
            source_url=_canonical_optional_source_url(record.get("url")),
            content=content,
            sha256=actual_sha,
            parsed=parsed,
            parser_name=parser_name,
            parser_version=parser_version,
            confidence_score=confidence.score,
            confidence_passed=confidence.passed,
            unmatched_lines_count=len(confidence.unmatched_lines),
        ))

    curation_report = None
    parsed_documents: tuple[ParsedCompetitionDocument, ...] = tuple(documents)
    if curation_policy is not None:
        curated, curation_report = apply_package_curation(parsed_documents, curation_policy)
        parsed_documents = tuple(curated)
    return ParsedCompetitionManifest(
        source_key=source_key,
        documents=parsed_documents,
        curation_report=curation_report,
    )


def _preflight_documents(documents: Sequence[ParsedCompetitionDocument]) -> None:
    if not documents:
        raise ValueError("Competition package contains no result documents")

    session_hashes: dict[tuple[str, int, int], tuple[str, str | None]] = {}
    for document in documents:
        actual_sha = hashlib.sha256(document.content).hexdigest()
        if actual_sha != document.sha256:
            raise ValueError(f"SHA-256 mismatch for {document.filename}")
        if not document.content.startswith(b"%PDF"):
            raise ValueError(f"Not a PDF: {document.filename}")
        if document.confidence_score < 0.6 or not document.confidence_passed:
            raise ValueError(f"Parser confidence failed for {document.filename}")

        parsed = document.parsed
        if not parsed.meet_name:
            raise ValueError(f"Missing competition segment name in {document.filename}")
        if parsed.metadata_conflicts:
            raise ValueError(f"Conflicting metadata in {document.filename}")
        if parsed.day_number is None or parsed.session_number is None:
            raise ValueError(f"Missing Day N Session N metadata in {document.filename}")
        if parsed.start_date is None or parsed.end_date is None:
            # The additive compatibility layer still writes legacy Meet rows,
            # whose date is required. Unknown-date performances become possible
            # once callers write directly to the canonical performance model.
            raise ValueError(f"Missing segment date range in {document.filename}")

        resolution = resolve_session_metadata(parsed)
        if resolution.status == "conflicting":
            raise ValueError(f"Conflicting session date in {document.filename}: {'; '.join(resolution.diagnostics)}")

        session_key = (parsed.meet_name, parsed.day_number, parsed.session_number)
        previous = session_hashes.get(session_key)
        same_explicit_policy = (
            previous is not None
            and previous[1] is not None
            and previous[1] == document.curation_policy_id
        )
        if previous is not None and previous[0] != document.sha256 and not same_explicit_policy:
            raise ValueError(
                f"Multiple result documents claim {parsed.meet_name} "
                f"Day {parsed.day_number} Session {parsed.session_number}"
            )
        session_hashes[session_key] = (document.sha256, document.curation_policy_id)


def import_parsed_competition_documents(
    db: Session,
    *,
    source_key: str,
    competition_title: str,
    documents: Sequence[ParsedCompetitionDocument],
    archive_root: Path,
) -> CompetitionImportSummary:
    """Validate a complete parser output set, then atomically populate the RDB."""
    _preflight_documents(documents)
    source_key = _canonical_source_key(source_key)
    competition_title = competition_title.strip()
    if not competition_title:
        raise ValueError("Competition title is required")

    created_archive_paths: set[Path] = set()
    try:
        if db.get_bind().dialect.name == "postgresql":
            # One transaction per canonical source may promote domain rows at a
            # time. The unique indexes remain the final integrity backstop.
            db.execute(
                text("SELECT pg_advisory_xact_lock(:namespace, hashtext(:source_key))"),
                {"namespace": 19372026, "source_key": source_key},
            )
        parser_versions = sorted({document.parser_version for document in documents})
        ingestion_run = start_ingestion_run(
            db,
            mode="rebuild",
            input_scope=f"competition:{source_key}",
            parser_version=",".join(parser_versions),
        )
        results_inserted = 0
        swimmers_created = 0
        duplicates_skipped = 0
        edition_id: int | None = None

        for document in documents:
            parsed = document.parsed
            if parsed.start_date is None or parsed.end_date is None:
                raise ValueError(f"Competition dates unresolved for {document.filename}")
            segment_start = datetime.combine(parsed.start_date, time.min)
            segment_end = datetime.combine(parsed.end_date, time.min)
            meet = db.query(Meet).filter(
                Meet.name == parsed.meet_name,
                Meet.startDate == segment_start,
            ).first()
            if meet is None:
                meet = Meet(
                    name=parsed.meet_name,
                    startDate=segment_start,
                    endDate=segment_end,
                    parserFormat=document.parser_name,
                )
                db.add(meet)
                db.flush()
            elif meet.endDate is None:
                meet.endDate = segment_end
            elif meet.endDate.date() != segment_end.date():
                raise ValueError(
                    f"Legacy meet date range conflicts for {parsed.meet_name}: "
                    f"stored end {meet.endDate.date()}, received {segment_end.date()}"
                )

            competition_session = upsert_competition_hierarchy(
                db,
                source_key=source_key,
                competition_title=competition_title,
                parsed=parsed,
                legacy_meet=meet,
            )
            edition_id = competition_session.day.segment.competitionEditionId
            race_date = competition_session.day.date
            swim_datetime = datetime.combine(race_date, time.min) if race_date else None

            archive_path = pdf_storage_path(archive_root, document.sha256)
            if not archive_path.exists():
                created_archive_paths.add(archive_path)
            raw_document = record_raw_document(
                db,
                file_bytes=document.content,
                filename=document.filename,
                source_type="sg-aquatics",
                source_label=competition_title,
                source_url=document.source_url,
                source_page_url=source_key,
                archive_root=archive_root,
                content_type="application/pdf",
            )
            parse_job = record_parse_job(
                db,
                raw_document=raw_document,
                parser_name=document.parser_name,
                parser_version=document.parser_version,
                status="succeeded",
                confidence_score=document.confidence_score,
                confidence_passed=True,
                events_count=len(parsed.events),
                individual_results_count=parsed.total_results,
                relay_results_count=parsed.total_relay_results,
                unmatched_lines_count=document.unmatched_lines_count,
            )

            inserted, created, skipped, errors, _duplicates = _process_parsed_meet(
                parsed,
                meet,
                swim_datetime,
                db,
                raw_document=raw_document,
                parse_job=parse_job,
                ingestion_run=ingestion_run,
                parser_version=document.parser_version,
                competition_session=competition_session,
            )
            if errors:
                raise ValueError(f"Import validation failed for {document.filename}: {'; '.join(errors)}")
            results_inserted += inserted
            swimmers_created += created
            duplicates_skipped += skipped

        if edition_id is None:
            raise ValueError("Competition package did not resolve an edition")

        ingestion_run.status = "succeeded"
        ingestion_run.recordsInserted = results_inserted
        ingestion_run.duplicatesSkipped = duplicates_skipped
        db.commit()
        return CompetitionImportSummary(
            documents_imported=len(documents),
            results_inserted=results_inserted,
            swimmers_created=swimmers_created,
            duplicates_skipped=duplicates_skipped,
            edition_id=edition_id,
        )
    except Exception:
        db.rollback()
        cleanup_unledgered_archives(db, created_archive_paths)
        raise
