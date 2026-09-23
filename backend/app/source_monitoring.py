"""Source monitoring service primitives.

This module owns platform-visible source discovery state. It deliberately does
not import swimming domain rows (`Meet`, `Swimmer`, `Result`, etc.). The SG
Aquatics adapter discovers event pages/documents; later archive/hash/import
slices can consume this source catalog.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Collection
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    CompetitionDay,
    CompetitionEdition,
    CompetitionSegment,
    CompetitionSession,
    MonitorRun,
    RawDocument,
    RelayResult,
    Result,
    SourceEvent,
    SourceEventDocument,
    SourceReference,
    SourceRule,
    SourceSite,
)

SGA_BASE_URL = "https://www.sgaquatics.org.sg"
SGA_INDEX_URL = "https://www.sgaquatics.org.sg/swimming/events/event-results/"
ADAPTER_VERSION = "sgaquatics-events-v1"
READINESS_STATUSES = {
    "pending_no_documents",
    "documents_available_no_results",
    "results_available",
    "no_documents_found",
}


class SourceRuleNotFoundError(ValueError):
    pass


class SourceRuleDisabledError(RuntimeError):
    pass


class SourceMonitorAlreadyRunningError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiscoveredDocument:
    url: str
    filename: str
    category: str


@dataclass(frozen=True)
class DiscoveredEvent:
    title: str
    url: str
    readiness_status: str
    page_title: str | None = None
    pdf_count: int = 0
    result_pdf_count: int = 0
    category_counts: dict[str, int] = field(default_factory=dict)
    documents: list[DiscoveredDocument] = field(default_factory=list)
    source_year: str | None = None
    source_date_label: str | None = None
    status_reason: str | None = None


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def source_event_manifest_sha256(event: DiscoveredEvent) -> str:
    """Hash the discovered page and its current official-link manifest.

    This is intentionally metadata-only: a catalogue check compares the event
    page's semantic fields and canonical document links without downloading PDFs.
    A document-byte replacement at an unchanged URL stays outside this cheap
    check and needs an explicit document-hash workflow.
    """
    payload = {
        "version": 1,
        "title": event.title,
        "page_title": event.page_title,
        "url": event.url,
        "readiness_status": event.readiness_status,
        "source_year": event.source_year,
        "source_date_label": event.source_date_label,
        "status_reason": event.status_reason,
        "pdf_count": event.pdf_count,
        "result_pdf_count": event.result_pdf_count,
        "category_counts": event.category_counts,
        "documents": sorted(
            (
                {"url": document.url, "filename": document.filename, "category": document.category}
                for document in event.documents
            ),
            key=lambda document: (document["url"], document["filename"], document["category"]),
        ),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _edition_source_page_urls(db: Session, edition: CompetitionEdition) -> set[str]:
    """Return source-page evidence attached to documents in one edition."""
    session_ids = [
        session_id
        for (session_id,) in db.query(CompetitionSession.id)
        .join(CompetitionDay, CompetitionDay.id == CompetitionSession.competitionDayId)
        .join(CompetitionSegment, CompetitionSegment.id == CompetitionDay.competitionSegmentId)
        .filter(CompetitionSegment.competitionEditionId == edition.id)
        .all()
    ]
    if not session_ids:
        return set()
    document_hashes = {
        value
        for (value,) in db.query(CompetitionSession.sourceDocumentSha)
        .filter(CompetitionSession.id.in_(session_ids), CompetitionSession.sourceDocumentSha.isnot(None))
        .all()
    }
    document_hashes.update(
        value
        for (value,) in db.query(Result.sourceDocumentSha256)
        .filter(Result.sessionId.in_(session_ids), Result.sourceDocumentSha256.isnot(None))
        .distinct()
        .all()
    )
    document_hashes.update(
        value
        for (value,) in db.query(RelayResult.sourceDocumentSha256)
        .filter(RelayResult.sessionId.in_(session_ids), RelayResult.sourceDocumentSha256.isnot(None))
        .distinct()
        .all()
    )
    if not document_hashes:
        return set()
    rows = (
        db.query(SourceReference.sourcePageUrl)
        .join(RawDocument, RawDocument.id == SourceReference.rawDocumentId)
        .filter(RawDocument.sha256.in_(document_hashes))
        .all()
    )
    return {canonicalize_url(page_url) for (page_url,) in rows if page_url}


def backfill_source_event_links(db: Session) -> dict[str, int]:
    """Link historical pages only when URL and imported-document evidence agree.

    A historical association does *not* establish page freshness: no import
    snapshot is populated. The next source-bound re-import is the only action
    that can make an edition current against a known live manifest.
    """
    editions = db.query(CompetitionEdition).filter(CompetitionEdition.sourceEventId.is_(None)).all()
    by_url: dict[str, list[CompetitionEdition]] = {}
    for edition in editions:
        by_url.setdefault(canonicalize_url(edition.sourceKey), []).append(edition)

    summary = {
        "linked": 0,
        "skipped_ambiguous": 0,
        "skipped_no_exact_match": 0,
        "skipped_missing_source_evidence": 0,
    }
    events = (
        db.query(SourceEvent)
        .join(SourceRule, SourceRule.id == SourceEvent.sourceRuleId)
        .join(SourceSite, SourceSite.id == SourceRule.sourceSiteId)
        .filter(SourceSite.adapterType == "sgaquatics_events")
        .all()
    )
    events_by_url: dict[str, list[SourceEvent]] = {}
    for event in events:
        events_by_url.setdefault(canonicalize_url(event.url), []).append(event)
    for canonical_event_url, matching_events in events_by_url.items():
        candidates = by_url.get(canonical_event_url, [])
        if len(matching_events) != 1:
            if candidates:
                summary["skipped_ambiguous"] += 1
            continue
        event = matching_events[0]
        if event.competitionEditions:
            continue
        if len(candidates) != 1:
            summary["skipped_ambiguous" if candidates else "skipped_no_exact_match"] += 1
            continue
        edition = candidates[0]
        if canonical_event_url not in _edition_source_page_urls(db, edition):
            summary["skipped_missing_source_evidence"] += 1
            continue
        edition.sourceEventId = event.id
        # Do not copy the current source manifest here. Legacy imports predate
        # monitoring, so their source state at import time is unknowable.
        by_url[canonical_event_url].remove(edition)
        summary["linked"] += 1
    db.flush()
    return summary


def acknowledge_imported_source_manifest(
    db: Session,
    edition: CompetitionEdition,
    *,
    source_key: str,
    source_event_id: int,
    expected_manifest_sha256: str,
    imported_document_urls: Collection[str],
    is_curated_subset: bool = False,
    captured_at: datetime | None = None,
) -> None:
    """Record a current manifest only for an explicitly source-bound import.

    The caller must carry the reviewed event ID and fingerprint into the import
    transaction. The imported result-document set must still be the event's
    current allowed result-document set; otherwise the complete import rolls
    back rather than silently making stale archives look current.
    """
    event = db.get(SourceEvent, source_event_id)
    if event is None:
        raise ValueError(f"Source event {source_event_id} does not exist")
    canonical_source_key = canonicalize_url(source_key)
    if canonicalize_url(event.url) != canonical_source_key:
        raise ValueError("Source event URL does not match the competition source key")
    if event.manifestSha256 != expected_manifest_sha256:
        raise ValueError("Source page changed; refresh and review before importing")
    try:
        configured_categories = json.loads(event.source_rule.categoriesAllowedForImport or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError("Source rule has invalid import-category policy") from exc
    if not isinstance(configured_categories, list) or not all(
        isinstance(category, str) for category in configured_categories
    ):
        raise ValueError("Source rule has invalid import-category policy")
    allowed_categories = set(configured_categories)
    current_document_urls = {
        canonicalize_url(document.url, base_url=event.url)
        for document in event.documents
        if document.isCurrentlyListed and document.category in allowed_categories
    }
    imported_urls = {canonicalize_url(url, base_url=canonical_source_key) for url in imported_document_urls}
    if not imported_urls or not imported_urls.issubset(current_document_urls):
        raise ValueError("Imported documents do not match the reviewed current source page")
    if imported_urls != current_document_urls and not is_curated_subset:
        raise ValueError("A partial source import requires an approved curation policy")
    if edition.sourceEventId is not None and edition.sourceEventId != event.id:
        raise ValueError(
            f"Competition edition {edition.id} is already linked to source event {edition.sourceEventId}"
        )
    edition.sourceEventId = event.id
    edition.sourceManifestSha256 = event.manifestSha256
    edition.sourceManifestCaptureKind = "imported"
    edition.sourceManifestCapturedAt = captured_at or datetime.now(timezone.utc)
    db.flush()


def canonicalize_url(url: str, *, base_url: str | None = None, strip_trailing_slash: bool = True) -> str:
    """Normalize source identity URLs at the service boundary.

    Adapters may return absolute/relative URLs with fragments, escaped paths, or
    trailing-slash variants. Source-monitoring identity should be canonical so
    one event/document does not become multiple rows because the source HTML or a
    future adapter changed representation.
    """
    joined = urljoin(base_url or "", url.strip())
    parts = urlsplit(joined)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = quote(unquote(parts.path), safe="/:@")
    if strip_trailing_slash and len(path) > 1:
        path = path.rstrip("/")
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)), doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def default_source_policy() -> dict[str, str | list[str]]:
    return {
        "cadence": "manual_only_v0",
        "schedule": "not_configured",
        "active_window": "manual_only_v0",
        "stale_window": "manual_only_v0",
        "categories_to_archive": [
            "event_information",
            "start_list",
            "overall_results",
            "age_group_results",
            "medal_tally",
            "other_pdf",
        ],
        "categories_to_preview": ["overall_results", "other_pdf"],
        "categories_allowed_for_import": ["overall_results", "other_pdf"],
        "auto_import_policy": "preview_only",
    }


def _extract_year(text: str) -> str | None:
    match = re.search(r"\b(20\d{2})\b", text)
    return match.group(1) if match else None


def ensure_default_sgaquatics_source(db: Session) -> tuple[SourceSite, SourceRule]:
    """Create or return the default visible SG Aquatics source rule.

    Idempotency matters because app startup/manual setup/manual API calls may all
    ask for the same default rule. The DB uniqueness constraints are the final
    guardrail; this helper also avoids duplicates in normal execution.
    """
    site = (
        db.query(SourceSite)
        .filter(SourceSite.adapterType == "sgaquatics_events", SourceSite.baseUrl == SGA_BASE_URL)
        .one_or_none()
    )
    if site is None:
        site = SourceSite(
            name="SG Aquatics",
            baseUrl=SGA_BASE_URL,
            adapterType="sgaquatics_events",
            isEnabled=True,
        )
        db.add(site)
        db.flush()

    policy = default_source_policy()
    rule = (
        db.query(SourceRule)
        .filter(SourceRule.sourceSiteId == site.id, SourceRule.indexUrl == SGA_INDEX_URL)
        .one_or_none()
    )
    if rule is None:
        rule = SourceRule(
            sourceSiteId=site.id,
            name="SG Aquatics Swimming Events",
            indexUrl=SGA_INDEX_URL,
            enabled=True,
            cadencePolicy=canonical_json({"schedule": policy["schedule"], "cadence": policy["cadence"]}),
            activeWindowPolicy=canonical_json({"mode": policy["active_window"]}),
            staleWindowPolicy=canonical_json({"mode": policy["stale_window"]}),
            categoriesToArchive=canonical_json(policy["categories_to_archive"]),
            categoriesToPreview=canonical_json(policy["categories_to_preview"]),
            categoriesAllowedForImport=canonical_json(policy["categories_allowed_for_import"]),
            autoImportPolicy=str(policy["auto_import_policy"]),
        )
        db.add(rule)
        db.flush()

    db.commit()
    return site, rule


def _rule_snapshot(rule: SourceRule) -> dict[str, str | int | bool | None]:
    return {
        "id": rule.id,
        "name": rule.name,
        "indexUrl": rule.indexUrl,
        "enabled": rule.enabled,
        "cadencePolicy": rule.cadencePolicy,
        "activeWindowPolicy": rule.activeWindowPolicy,
        "staleWindowPolicy": rule.staleWindowPolicy,
        "categoriesToArchive": rule.categoriesToArchive,
        "categoriesToPreview": rule.categoriesToPreview,
        "categoriesAllowedForImport": rule.categoriesAllowedForImport,
        "autoImportPolicy": rule.autoImportPolicy,
    }


def _summary_for_run(run: MonitorRun, errors: list[str] | None = None) -> str:
    return canonical_json({
        "events": {
            "discovered": run.eventsDiscovered,
            "with_results": run.eventsWithResults,
            "added": run.addedEvents,
            "updated": run.updatedEvents,
            "unchanged": run.unchangedEvents,
            "absent_from_index": run.absentFromIndexEvents,
        },
        "documents": {
            "added": run.addedDocuments,
            "updated": run.updatedDocuments,
            "unchanged": run.unchangedDocuments,
        },
        "action_required_count": run.actionRequiredCount,
        "errors": errors or [],
    })


def _normalized_discoveries(rule: SourceRule, discovered: list[DiscoveredEvent]) -> list[DiscoveredEvent]:
    """Canonicalize and de-duplicate adapter output before DB mutation."""
    normalized_by_url: dict[str, DiscoveredEvent] = {}
    for event in discovered:
        if event.readiness_status not in READINESS_STATUSES:
            raise ValueError(f"Unknown readiness status: {event.readiness_status}")
        event_url = canonicalize_url(event.url, base_url=rule.indexUrl)
        document_by_key: dict[str, DiscoveredDocument] = {}
        for document in event.documents:
            doc_url = canonicalize_url(document.url, base_url=event_url)
            normalized_document = DiscoveredDocument(
                url=doc_url,
                filename=document.filename,
                category=document.category,
            )
            existing_document = document_by_key.get(doc_url)
            if existing_document is not None and existing_document != normalized_document:
                raise ValueError(
                    "Conflicting metadata for canonical source document URL: "
                    f"{doc_url}"
                )
            document_by_key[doc_url] = normalized_document

        existing = normalized_by_url.get(event_url)
        if existing is None:
            normalized_by_url[event_url] = DiscoveredEvent(
                title=event.title,
                page_title=event.page_title,
                url=event_url,
                readiness_status=event.readiness_status,
                pdf_count=len(document_by_key),
                result_pdf_count=sum(1 for doc in document_by_key.values() if doc.category == "overall_results"),
                category_counts=_category_counts(document_by_key.values()),
                documents=list(document_by_key.values()),
                source_year=event.source_year,
                source_date_label=event.source_date_label,
                status_reason=event.status_reason,
            )
            continue

        merged_docs = {
            doc.url: doc
            for doc in existing.documents
        }
        merged_docs.update(document_by_key)
        readiness = "results_available" if (
            existing.readiness_status == "results_available" or event.readiness_status == "results_available"
        ) else existing.readiness_status
        normalized_by_url[event_url] = DiscoveredEvent(
            title=existing.title,
            page_title=existing.page_title or event.page_title,
            url=event_url,
            readiness_status=readiness,
            pdf_count=len(merged_docs),
            result_pdf_count=sum(1 for doc in merged_docs.values() if doc.category == "overall_results"),
            category_counts=_category_counts(merged_docs.values()),
            documents=list(merged_docs.values()),
            source_year=existing.source_year or event.source_year,
            source_date_label=existing.source_date_label or event.source_date_label,
            status_reason=existing.status_reason or event.status_reason,
        )
    return list(normalized_by_url.values())


def _category_counts(documents) -> dict[str, int]:
    counts: dict[str, int] = {}
    for document in documents:
        counts[document.category] = counts.get(document.category, 0) + 1
    return counts


def _create_running_monitor_run(db: Session, rule: SourceRule, triggered_by: str | None) -> MonitorRun:
    run = MonitorRun(
        sourceRuleId=rule.id,
        triggerType="manual_api",
        triggeredBy=triggered_by,
        adapterVersion=ADAPTER_VERSION,
        indexUrlSnapshot=rule.indexUrl,
        ruleConfigSnapshotJson=canonical_json(_rule_snapshot(rule)),
        status="running",
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise SourceMonitorAlreadyRunningError(f"SourceRule {rule.id} already has a running MonitorRun") from exc
    db.refresh(run)
    return run


def _mark_monitor_run_failed(db: Session, run_id: int, error: Exception) -> MonitorRun:
    db.rollback()
    run = db.get(MonitorRun, run_id)
    if run is None:
        raise error
    run.status = "failed"
    run.finishedAt = datetime.now(timezone.utc)
    run.errorMessage = str(error)
    run.summaryJson = _summary_for_run(run, errors=[str(error)])
    db.commit()
    db.refresh(run)
    return run


def run_discovery_preview(
    db: Session,
    source_rule_id: int,
    *,
    discover: Callable[[SourceRule], list[DiscoveredEvent]],
    triggered_by: str | None = None,
) -> MonitorRun:
    """Run a manual discovery preview and persist source catalog state only.

    This does not download/hash PDFs and does not touch swimming domain tables.
    The running-run guard is DB-backed via a partial unique index on running
    MonitorRun rows. Source catalog mutations are all-or-nothing per run: failed
    runs retain the MonitorRun failure record but roll back source-event/document
    mutations from that attempt.
    """
    rule = db.get(SourceRule, source_rule_id)
    if rule is None:
        raise SourceRuleNotFoundError(f"SourceRule not found: {source_rule_id}")
    if not rule.enabled:
        raise SourceRuleDisabledError(f"SourceRule {source_rule_id} is disabled")

    run = _create_running_monitor_run(db, rule, triggered_by)

    try:
        discovered = _normalized_discoveries(rule, discover(rule))
        discovered_by_url = {event.url: event for event in discovered}
        existing_events = {
            canonicalize_url(event.url, base_url=rule.indexUrl): event
            for event in db.query(SourceEvent).filter(SourceEvent.sourceRuleId == rule.id).all()
        }
        now = datetime.now(timezone.utc)
        run = db.get(MonitorRun, run.id)
        assert run is not None

        for existing_url, event in existing_events.items():
            if existing_url not in discovered_by_url and event.isCurrentlyListed:
                event.isCurrentlyListed = False
                event.lastCheckedAt = now
                event.lastChangedAt = now
                run.absentFromIndexEvents += 1

        for discovered_event in discovered:
            event = existing_events.get(discovered_event.url)
            category_counts_json = canonical_json(discovered_event.category_counts)
            discovered_manifest_sha256 = source_event_manifest_sha256(discovered_event)
            if event is None:
                event = SourceEvent(
                    sourceRuleId=rule.id,
                    title=discovered_event.title,
                    pageTitle=discovered_event.page_title,
                    url=discovered_event.url,
                    sourceYear=discovered_event.source_year or _extract_year(discovered_event.title),
                    sourceDateLabel=discovered_event.source_date_label,
                    readinessStatus=discovered_event.readiness_status,
                    statusReason=discovered_event.status_reason,
                    isCurrentlyListed=True,
                    pdfCount=discovered_event.pdf_count,
                    resultPdfCount=discovered_event.result_pdf_count,
                    categoryCountsJson=category_counts_json,
                    manifestSha256=discovered_manifest_sha256,
                    lastSeenInIndexAt=now,
                    lastCheckedAt=now,
                    lastChangedAt=now,
                )
                db.add(event)
                db.flush()
                run.addedEvents += 1
            else:
                changed = event.manifestSha256 != discovered_manifest_sha256 or not event.isCurrentlyListed
                event.title = discovered_event.title
                event.pageTitle = discovered_event.page_title
                event.sourceYear = discovered_event.source_year or event.sourceYear or _extract_year(discovered_event.title)
                event.sourceDateLabel = discovered_event.source_date_label
                event.readinessStatus = discovered_event.readiness_status
                event.statusReason = discovered_event.status_reason
                event.isCurrentlyListed = True
                event.pdfCount = discovered_event.pdf_count
                event.resultPdfCount = discovered_event.result_pdf_count
                event.categoryCountsJson = category_counts_json
                event.lastSeenInIndexAt = now
                event.lastCheckedAt = now
                if changed:
                    event.lastChangedAt = now
                    run.updatedEvents += 1
                else:
                    run.unchangedEvents += 1

            existing_docs = {
                canonicalize_url(doc.url, base_url=discovered_event.url): doc
                for doc in db.query(SourceEventDocument).filter(SourceEventDocument.sourceEventId == event.id).all()
            }
            discovered_doc_keys = set()
            for document in discovered_event.documents:
                key = document.url
                discovered_doc_keys.add(key)
                existing_doc = existing_docs.get(key)
                if existing_doc is None:
                    db.add(SourceEventDocument(
                        sourceEventId=event.id,
                        url=document.url,
                        filename=document.filename,
                        category=document.category,
                        firstSeenAt=now,
                        lastSeenAt=now,
                        lastCheckedAt=now,
                        isCurrentlyListed=True,
                    ))
                    run.addedDocuments += 1
                else:
                    metadata_changed = existing_doc.filename != document.filename or existing_doc.category != document.category
                    if not existing_doc.isCurrentlyListed or metadata_changed:
                        run.updatedDocuments += 1
                    else:
                        run.unchangedDocuments += 1
                    existing_doc.url = document.url
                    existing_doc.filename = document.filename
                    existing_doc.category = document.category
                    existing_doc.lastSeenAt = now
                    existing_doc.lastCheckedAt = now
                    existing_doc.isCurrentlyListed = True

            for key, existing_doc in existing_docs.items():
                if key not in discovered_doc_keys and existing_doc.isCurrentlyListed:
                    existing_doc.isCurrentlyListed = False
                    existing_doc.lastCheckedAt = now
                    run.updatedDocuments += 1

            event.manifestSha256 = discovered_manifest_sha256

        run.eventsDiscovered = len(discovered)
        run.eventsWithResults = sum(1 for event in discovered if event.readiness_status == "results_available")
        run.actionRequiredCount = sum(1 for event in discovered if event.result_pdf_count > 0)
        run.status = "succeeded"
        run.finishedAt = datetime.now(timezone.utc)
        run.summaryJson = _summary_for_run(run)
        db.commit()
        db.refresh(run)
        return run
    except Exception as exc:
        return _mark_monitor_run_failed(db, run.id, exc)


def discover_sgaquatics_events(rule: SourceRule) -> list[DiscoveredEvent]:
    """Live SG Aquatics adapter using the checked-in discovery script.

    The adapter remains source-specific, while `run_discovery_preview` stays
    reusable platform logic. This call is read-only: it fetches HTML/PDF links but
    does not download/archive PDFs and therefore cannot detect same-filename
    content replacement yet.
    """
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "discover_sgaquatics_events.py"
    spec = importlib.util.spec_from_file_location("swim_sgaquatics_discovery", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load SG Aquatics discovery script at {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    index_html = module.fetch_text(rule.indexUrl)
    event_links = module.extract_event_links(rule.indexUrl, index_html)
    discoveries = []
    for event_link in event_links:
        inspected = module.inspect_event(event_link)
        documents = [
            DiscoveredDocument(url=pdf.url, filename=pdf.filename, category=pdf.category)
            for pdf in inspected.pdfs
        ]
        discoveries.append(DiscoveredEvent(
            title=inspected.title,
            page_title=inspected.page_title,
            url=inspected.url,
            readiness_status=inspected.status,
            pdf_count=inspected.pdf_count,
            result_pdf_count=inspected.category_counts.get("overall_results", 0),
            category_counts=inspected.category_counts,
            documents=documents,
            source_year=_extract_year(inspected.title) or _extract_year(inspected.page_title or ""),
        ))
    return discoveries
