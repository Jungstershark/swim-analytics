"""Validated parser-output to relational competition import boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Mapping, Sequence
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.orm import Session

from .competition_packages import (
    CompetitionIdentity,
    _document_index,
    evidence_key_for_document,
    overlap_key_for_document,
    performance_signatures,
    resolve_segment_identity,
    resolve_session_metadata,
    upsert_competition_hierarchy,
)
from .ingestion import (
    cleanup_unledgered_archives,
    pdf_storage_path,
    record_parse_job,
    record_raw_document,
    start_ingestion_run,
)
from .main import _process_parsed_meet
from .models import (
    CompetitionDay,
    CompetitionEdition,
    CompetitionSegment,
    CompetitionSession,
    Meet,
    RelayResult,
    Result,
)
from .package_curation import (
    PackageCurationPolicy,
    PackageCurationReport,
    apply_package_curation,
    select_manifest_records,
)
from .parsers.base import detect_parser
from .parsers.hytek import CRITICAL_CHECKS, IDENTITY_CHECKS, ConfidenceReport, ParsedMeet
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
    # Set when the curation policy explicitly declares this document as one half
    # of an authorised overlapping pair; only such a pair may share evidence.
    shared_evidence_group: str | None = None
    # Named checks from the parser report. Kept so the import boundary can tell
    # which checks describe page-printed identity (which the caller may supply)
    # from the checks that must always hold.
    confidence_checks: dict[str, bool] = field(default_factory=dict)


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
    # Sessions (and their rows) removed because the document that owned them is
    # no longer part of the package.
    sessions_removed: int = 0


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
            confidence_checks=dict(confidence.checks),
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


def _identity_for_document(
    document: ParsedCompetitionDocument,
    identity: CompetitionIdentity | None,
    document_identity: Mapping[str, CompetitionIdentity] | None,
) -> CompetitionIdentity | None:
    """Return the identity that applies to one document.

    A per-document entry (keyed by filename or content hash) wins; the package
    identity is only the fallback, and documents whose pages print their own
    identity need no entry at all.
    """
    if not document_identity:
        return identity
    return (
        document_identity.get(document.filename)
        or document_identity.get(document.sha256)
        or identity
    )


def _preflight_documents(
    documents: Sequence[ParsedCompetitionDocument],
    *,
    identity: CompetitionIdentity | None = None,
    document_identity: Mapping[str, CompetitionIdentity] | None = None,
) -> None:
    if not documents:
        raise ValueError("Competition package contains no result documents")

    evidence_hashes: dict[str, tuple[str, str | None]] = {}
    performances: dict[tuple, tuple[str, str]] = {}
    for document in documents:
        actual_sha = hashlib.sha256(document.content).hexdigest()
        if actual_sha != document.sha256:
            raise ValueError(f"SHA-256 mismatch for {document.filename}")
        if not document.content.startswith(b"%PDF"):
            raise ValueError(f"Not a PDF: {document.filename}")

        resolved_identity = _identity_for_document(document, identity, document_identity)
        # Critical checks block an import. Checks that only describe identity
        # printed on the page are satisfied by whichever identity applies to this
        # document; when no identity is available they stay required. A document
        # with no named report at all falls back to the parser's own verdict,
        # which is itself computed from the critical set.
        required = (
            CRITICAL_CHECKS - IDENTITY_CHECKS
            if resolved_identity is not None
            else CRITICAL_CHECKS
        )
        if document.confidence_checks:
            failing = {
                name
                for name in required
                if not document.confidence_checks.get(name, False)
            }
            if document.confidence_score < 0.6 or failing:
                raise ValueError(f"Parser confidence failed for {document.filename}")
        elif document.confidence_score < 0.6 or not document.confidence_passed:
            # No named report: the parser's own verdict is all there is, and it is
            # itself computed from the critical set.
            raise ValueError(f"Parser confidence failed for {document.filename}")

        parsed = document.parsed
        if parsed.metadata_conflicts:
            raise ValueError(f"Conflicting metadata in {document.filename}")
        if not parsed.meet_name.strip() and not (
            resolved_identity and resolved_identity.title.strip()
        ):
            raise ValueError(f"Missing competition segment name in {document.filename}")
        # Segment name and date range come from the page when it prints them and
        # from the caller otherwise; a contradiction fails closed here.
        segment_name, start_date, end_date, _ = resolve_segment_identity(
            parsed, resolved_identity
        )
        if start_date is None or end_date is None:
            # The additive compatibility layer still writes legacy Meet rows,
            # whose date is required. Unknown-date performances become possible
            # once callers write directly to the canonical performance model.
            raise ValueError(f"Missing segment date range in {document.filename}")

        resolution = resolve_session_metadata(parsed, identity=resolved_identity)
        if resolution.status == "conflicting":
            raise ValueError(f"Conflicting session date in {document.filename}: {'; '.join(resolution.diagnostics)}")

        # Day/session headers are optional metadata, so a sheet is identified by
        # the evidence it contributes: segment, events, rounds and row counts.
        # A heats/finals pair differs in round, so the two do not collide, while
        # two distinct documents carrying identical evidence are a genuine
        # conflict. Only a pair the curation policy explicitly declares as
        # overlapping may share evidence - a shared package id is not permission.
        overlap_key = overlap_key_for_document(parsed, segment_name)
        previous = evidence_hashes.get(overlap_key)
        same_declared_pair = (
            previous is not None
            and previous[1] is not None
            and previous[1] == document.shared_evidence_group
        )
        if (
            previous is not None
            and previous[0] != document.sha256
            and not same_declared_pair
        ):
            raise ValueError(
                f"Multiple result documents claim {segment_name} "
                f"({len(parsed.events)} events) and the curation policy does not "
                "declare them as an overlapping pair"
            )
        evidence_hashes[overlap_key] = (
            document.sha256,
            document.shared_evidence_group,
        )

        # A shape hash cannot see two sheets that overlap on one race and
        # disagree about it. Each performance is therefore compared by identity:
        # reprints agree, a conflict fails closed.
        for identity_key, signature in performance_signatures(
            parsed, segment_name
        ).items():
            previous_performance = performances.get(identity_key)
            if previous_performance is None:
                performances[identity_key] = (document.sha256, signature)
                continue
            if previous_performance[0] == document.sha256:
                continue
            if previous_performance[1] != signature:
                _, event_number, event_name, time_type = identity_key[0]
                _, kind, who, team = identity_key
                raise ValueError(
                    f"Conflicting {time_type} for {event_name} "
                    f"({kind} {who} / {team}) in {segment_name}: two documents "
                    "carry different values for the same performance"
                )


def _reconcile_dropped_documents(
    db: Session, source_key: str, expected_shas: set[str]
) -> int:
    """Withdraw documents that are no longer part of the package.

    A rebuild imports exactly the curated document set, so a session still
    claiming a document outside that set owns stale rows. When nothing else feeds
    the session its rows are removed with it; a session still fed by a live
    document cannot be attributed row by row, so that case fails closed rather
    than guessing which rows to drop.
    """
    sessions = (
        db.query(CompetitionSession)
        .join(CompetitionDay, CompetitionSession.competitionDayId == CompetitionDay.id)
        .join(
            CompetitionSegment,
            CompetitionDay.competitionSegmentId == CompetitionSegment.id,
        )
        .join(
            CompetitionEdition,
            CompetitionSegment.competitionEditionId == CompetitionEdition.id,
        )
        .filter(CompetitionEdition.sourceKey == source_key)
        .all()
    )
    removed = 0
    for session in sessions:
        index = _document_index(session)
        if not index:
            continue
        stale = [entry for entry in index if entry["sha"] not in expected_shas]
        if not stale:
            continue
        live = [entry for entry in index if entry["sha"] in expected_shas]
        if live:
            raise ValueError(
                f"Session {session.id} is still fed by documents in the package but "
                f"also claims {len(stale)} document(s) that are no longer in it; "
                "rebuild this competition from scratch"
            )
        db.query(Result).filter(Result.sessionId == session.id).delete(
            synchronize_session=False
        )
        db.query(RelayResult).filter(RelayResult.sessionId == session.id).delete(
            synchronize_session=False
        )
        day = session.day
        db.delete(session)
        db.flush()
        # A day exists to hold its sessions; once the last one is gone so is it.
        if (
            db.query(CompetitionSession)
            .filter(CompetitionSession.competitionDayId == day.id)
            .count()
            == 0
        ):
            db.delete(day)
            db.flush()
        removed += 1
    return removed


def import_parsed_competition_documents(
    db: Session,
    *,
    source_key: str,
    competition_title: str,
    documents: Sequence[ParsedCompetitionDocument],
    archive_root: Path,
    start_date: date | None = None,
    end_date: date | None = None,
    identity_source: str = "operator",
    document_identity: Mapping[str, CompetitionIdentity] | None = None,
) -> CompetitionImportSummary:
    """Validate a complete parser output set, then atomically populate the RDB.

    ``competition_title`` and the date range are caller-supplied identity: the
    parser only ever provides placeholders. Values printed on a sheet win over
    the caller's; a contradiction fails closed rather than guessing.
    ``document_identity`` supplies identity for named documents only, which is
    how a package whose pages are silent gets its segment name and dates.
    """
    source_key = _canonical_source_key(source_key)
    title = competition_title.strip()
    if not title:
        raise ValueError("Competition title is required")
    identity = CompetitionIdentity(
        title=title,
        start_date=start_date,
        end_date=end_date,
        source=identity_source,
    )
    _preflight_documents(
        documents, identity=identity, document_identity=document_identity
    )

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
            resolved_identity = _identity_for_document(
                document, identity, document_identity
            )
            segment_name, segment_start_date, segment_end_date, _ = resolve_segment_identity(
                parsed, resolved_identity
            )
            if segment_start_date is None or segment_end_date is None:
                raise ValueError(f"Competition dates unresolved for {document.filename}")
            segment_start = datetime.combine(segment_start_date, time.min)
            segment_end = datetime.combine(segment_end_date, time.min)
            meet = db.query(Meet).filter(
                Meet.name == segment_name,
                Meet.startDate == segment_start,
            ).first()
            if meet is None:
                meet = Meet(
                    name=segment_name,
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
                    f"Legacy meet date range conflicts for {segment_name}: "
                    f"stored end {meet.endDate.date()}, received {segment_end.date()}"
                )

            competition_session = upsert_competition_hierarchy(
                db,
                source_key=source_key,
                competition_title=title,
                parsed=parsed,
                legacy_meet=meet,
                identity=resolved_identity,
                source_document_sha=document.sha256,
                evidence_key=evidence_key_for_document(parsed, segment_name),
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

        # A curated package is the authority on what its sessions contain: a
        # document dropped from it must not leave rows behind.
        sessions_removed = _reconcile_dropped_documents(
            db, source_key, {document.sha256 for document in documents}
        )

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
            sessions_removed=sessions_removed,
        )
    except Exception:
        db.rollback()
        cleanup_unledgered_archives(db, created_archive_paths)
        raise
