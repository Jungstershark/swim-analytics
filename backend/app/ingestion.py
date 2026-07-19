"""Shared ingestion primitives for uploaded and archived swim-result files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy.orm import Session

from .models import DocumentClassification, IngestionRun, ParseJob, RawDocument, SourceReference

def classify_document(filename: str) -> str:
    """Classify a swim-meet source document from its filename.

    This is intentionally conservative: categories decide what can be imported
    now vs archived for later.
    """
    name = filename.lower()
    # Specific document-role signals must win over broad meet-title words like
    # "Championships" / "Cships" / "National Age Group Swimming".
    if "medal" in name:
        return "medal_tally"
    if "start-list" in name or "startlist" in name:
        return "start_list"
    if "finals-by-age-group" in name or "age-group-result" in name or "age-group-results" in name:
        return "age_group_results"
    if "result" in name:
        return "overall_results"
    if "cships" in name or "championship" in name or "singapore-national-age-group-swimming" in name:
        return "event_information"
    return "other_pdf"


def is_import_eligible_document(category: str) -> bool:
    """Return whether a classified document can create Result rows in slice 1.

    Domain assumption: `overall_results` are the current canonical result-file
    import target. Age-group result PDFs are alternate placement/ranking views
    of many of the same swims, so they stay archive-only until a ResultRanking /
    PlacementContext model exists. `other_pdf` remains eligible if the parser
    passes so user-uploaded result PDFs with weak filenames are not rejected
    solely by filename classification.
    """
    return category in {"overall_results", "other_pdf"}


def _pdf_storage_path(archive_root: Path, sha256: str) -> Path:
    return archive_root / "sha256" / sha256[:2] / f"{sha256}.pdf"


def source_reference_identity(
    *,
    source_type: str,
    source_label: str | None,
    source_url: str | None,
    source_page_url: str | None,
    filename: str | None,
) -> str:
    """Build a non-null stable identity for source-reference dedupe.

    PostgreSQL unique constraints treat NULLs as distinct, so nullable source
    columns cannot safely be used directly for idempotency.
    """
    payload = {
        "source_type": source_type,
        "source_label": source_label or "",
        "source_url": source_url or "",
        "source_page_url": source_page_url or "",
        "filename": filename or "",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def record_raw_document(
    db: Session,
    *,
    file_bytes: bytes,
    filename: str,
    source_type: str,
    source_label: str | None,
    archive_root: Path,
    source_url: str | None = None,
    source_page_url: str | None = None,
    content_type: str | None = "application/pdf",
) -> RawDocument:
    """Archive bytes by SHA-256 and record source/provenance metadata.

    The raw document is content-addressed; multiple uploads/source URLs can point
    to the same document without duplicating the archived PDF bytes.
    """
    sha256 = hashlib.sha256(file_bytes).hexdigest()
    storage_path = _pdf_storage_path(archive_root, sha256)
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    if not storage_path.exists():
        storage_path.write_bytes(file_bytes)

    category = classify_document(filename)
    is_valid_pdf = file_bytes.startswith(b"%PDF")

    raw_document = db.query(RawDocument).filter(RawDocument.sha256 == sha256).first()
    if raw_document is None:
        raw_document = RawDocument(
            sha256=sha256,
            byteSize=len(file_bytes),
            contentType=content_type,
            storagePath=str(storage_path),
            originalFilename=filename,
            category=category,
            isValidPdf=is_valid_pdf,
        )
        db.add(raw_document)
        db.flush()

        db.add(DocumentClassification(
            rawDocumentId=raw_document.id,
            category=category,
            confidence=100,
            classifierVersion="filename-v1",
            reason=f"classified from filename: {filename}",
            isCurrent=True,
        ))
    else:
        if not raw_document.category:
            raw_document.category = category
        if not raw_document.originalFilename:
            raw_document.originalFilename = filename

    source_identity = source_reference_identity(
        source_type=source_type,
        source_label=source_label,
        source_url=source_url,
        source_page_url=source_page_url,
        filename=filename,
    )
    existing_ref = db.query(SourceReference).filter(
        SourceReference.rawDocumentId == raw_document.id,
        SourceReference.sourceIdentity == source_identity,
    ).first()
    if existing_ref is None:
        db.add(SourceReference(
            rawDocumentId=raw_document.id,
            sourceType=source_type,
            sourceLabel=source_label,
            sourceUrl=source_url,
            sourcePageUrl=source_page_url,
            filenameSeen=filename,
            sourceIdentity=source_identity,
        ))

    return raw_document


def start_ingestion_run(
    db: Session,
    *,
    mode: str,
    input_scope: str | None,
    parser_version: str | None,
) -> IngestionRun:
    """Create an ingestion run for preview/import/rebuild auditing."""
    run = IngestionRun(
        mode=mode,
        inputScope=input_scope,
        parserVersion=parser_version,
        status="running",
    )
    db.add(run)
    db.flush()
    return run


def record_parse_job(
    db: Session,
    *,
    raw_document: RawDocument,
    parser_name: str,
    parser_version: str,
    status: str,
    confidence_score: float | None,
    confidence_passed: bool,
    events_count: int,
    individual_results_count: int,
    relay_results_count: int,
    unmatched_lines_count: int,
    error_message: str | None = None,
    parsed_artifact_path: str | None = None,
) -> ParseJob:
    """Record parser diagnostics for a raw document."""
    score_percent = None if confidence_score is None else round(confidence_score * 100)
    parse_job = ParseJob(
        rawDocumentId=raw_document.id,
        parserName=parser_name,
        parserVersion=parser_version,
        status=status,
        confidenceScore=score_percent,
        confidencePassed=confidence_passed,
        eventsCount=events_count,
        individualResultsCount=individual_results_count,
        relayResultsCount=relay_results_count,
        unmatchedLinesCount=unmatched_lines_count,
        errorMessage=error_message,
        parsedArtifactPath=parsed_artifact_path,
    )
    db.add(parse_job)
    db.flush()
    return parse_job
