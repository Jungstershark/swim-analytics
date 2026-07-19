"""Source monitoring service primitives.

This module owns platform-visible source discovery state. It deliberately does
not import swimming domain rows (`Meet`, `Swimmer`, `Result`, etc.). The SG
Aquatics adapter discovers event pages/documents; later archive/hash/import
slices can consume this source catalog.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import MonitorRun, SourceEvent, SourceEventDocument, SourceRule, SourceSite

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
            document_by_key[doc_url] = DiscoveredDocument(url=doc_url, filename=document.filename, category=document.category)

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
            event_changed_by_documents = False
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
                    lastSeenInIndexAt=now,
                    lastCheckedAt=now,
                    lastChangedAt=now,
                )
                db.add(event)
                db.flush()
                run.addedEvents += 1
            else:
                changed = any([
                    event.title != discovered_event.title,
                    event.pageTitle != discovered_event.page_title,
                    event.readinessStatus != discovered_event.readiness_status,
                    event.pdfCount != discovered_event.pdf_count,
                    event.resultPdfCount != discovered_event.result_pdf_count,
                    event.categoryCountsJson != category_counts_json,
                    event.isCurrentlyListed is not True,
                ])
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
                    event_changed_by_documents = True
                else:
                    metadata_changed = existing_doc.filename != document.filename or existing_doc.category != document.category
                    if not existing_doc.isCurrentlyListed or metadata_changed:
                        run.updatedDocuments += 1
                        event_changed_by_documents = True
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
                    event_changed_by_documents = True

            if event_changed_by_documents and event.lastChangedAt != now:
                event.lastChangedAt = now

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
