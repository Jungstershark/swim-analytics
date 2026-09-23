"""Tests for source monitoring platform primitives."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

import app.source_monitoring as source_monitoring

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import CompetitionDay, CompetitionEdition, CompetitionSegment, CompetitionSession, Meet, MonitorRun, RawDocument, RelayLeg, RelayResult, Result, SourceEvent, SourceEventDocument, SourceReference, SourceRule, SourceSite, Swimmer
from app.main import admin_list_sources, admin_list_source_events, admin_list_monitor_runs
from app.source_monitoring import DiscoveredDocument, DiscoveredEvent, ensure_default_sgaquatics_source, run_discovery_preview


def _test_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)()


def _event(title: str, url: str, status: str = "results_available") -> DiscoveredEvent:
    return DiscoveredEvent(
        title=title,
        page_title=title,
        url=url,
        readiness_status=status,
        pdf_count=1,
        result_pdf_count=1 if status == "results_available" else 0,
        category_counts={"overall_results": 1} if status == "results_available" else {"event_information": 1},
        documents=[
            DiscoveredDocument(
                url=f"{url.rstrip('/')}/result.pdf",
                filename="result.pdf",
                category="overall_results" if status == "results_available" else "event_information",
            )
        ],
    )


def test_default_sgaquatics_source_config_is_idempotent():
    db = _test_session()

    first_site, first_rule = ensure_default_sgaquatics_source(db)
    second_site, second_rule = ensure_default_sgaquatics_source(db)

    assert first_site.id == second_site.id
    assert first_rule.id == second_rule.id
    assert db.query(SourceSite).count() == 1
    assert db.query(SourceRule).count() == 1
    assert first_site.adapterType == "sgaquatics_events"
    assert first_rule.autoImportPolicy == "preview_only"


def test_discovery_preview_upserts_events_documents_and_monitor_run():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)

    run = run_discovery_preview(
        db,
        rule.id,
        discover=lambda _rule: [_event("SAQ ETP Championships 2026", "https://example.test/saq-etp/")],
    )

    assert run.status == "succeeded"
    assert run.finishedAt is not None
    assert run.triggerType == "manual_api"
    assert run.eventsDiscovered == 1
    assert run.eventsWithResults == 1
    assert run.addedEvents == 1
    assert run.updatedEvents == 0

    event = db.query(SourceEvent).one()
    assert event.sourceRuleId == rule.id
    assert event.title == "SAQ ETP Championships 2026"
    assert event.readinessStatus == "results_available"
    assert event.isCurrentlyListed is True
    assert event.lastSeenInIndexAt is not None

    document = db.query(SourceEventDocument).one()
    assert document.sourceEventId == event.id
    assert document.filename == "result.pdf"
    assert document.category == "overall_results"


def test_discovery_preview_is_idempotent_and_retains_rollover_absent_events():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)
    url = "https://example.test/2025-event/"

    first_run = run_discovery_preview(db, rule.id, discover=lambda _rule: [_event("2025 Event", url)])
    second_run = run_discovery_preview(db, rule.id, discover=lambda _rule: [])

    assert first_run.addedEvents == 1
    assert second_run.addedEvents == 0
    assert second_run.absentFromIndexEvents == 1
    assert db.query(SourceEvent).count() == 1
    assert db.query(SourceEventDocument).count() == 1
    event = db.query(SourceEvent).one()
    assert event.url == "https://example.test/2025-event"
    assert event.isCurrentlyListed is False
    assert event.readinessStatus == "results_available"


def test_discovery_preview_does_not_touch_domain_tables():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)

    before = {
        "meets": db.query(Meet).count(),
        "swimmers": db.query(Swimmer).count(),
        "results": db.query(Result).count(),
        "relay_results": db.query(RelayResult).count(),
        "relay_legs": db.query(RelayLeg).count(),
    }

    run_discovery_preview(db, rule.id, discover=lambda _rule: [_event("Safe Event", "https://example.test/safe/")])

    after = {
        "meets": db.query(Meet).count(),
        "swimmers": db.query(Swimmer).count(),
        "results": db.query(Result).count(),
        "relay_results": db.query(RelayResult).count(),
        "relay_legs": db.query(RelayLeg).count(),
    }
    assert after == before


def test_discovery_preview_canonicalizes_event_and_document_urls():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)
    base = "https://example.test/event"

    run_discovery_preview(
        db,
        rule.id,
        discover=lambda _rule: [
            DiscoveredEvent(
                title="Canonical",
                page_title="Canonical",
                url=f"{base}/#section",
                readiness_status="results_available",
                pdf_count=1,
                result_pdf_count=1,
                category_counts={"overall_results": 1},
                documents=[DiscoveredDocument(url=f"{base}/result.pdf#v1", filename="result.pdf", category="overall_results")],
            ),
            DiscoveredEvent(
                title="Canonical Duplicate",
                page_title="Canonical Duplicate",
                url=f"{base}",
                readiness_status="results_available",
                pdf_count=1,
                result_pdf_count=1,
                category_counts={"overall_results": 1},
                documents=[DiscoveredDocument(url=f"{base}/result.pdf", filename="result.pdf", category="overall_results")],
            ),
        ],
    )

    assert db.query(SourceEvent).count() == 1
    assert db.query(SourceEventDocument).count() == 1
    event = db.query(SourceEvent).one()
    document = db.query(SourceEventDocument).one()
    assert event.url == base
    assert document.url == f"{base}/result.pdf"


def test_discovery_preview_rejects_conflicting_metadata_for_one_canonical_document_url():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)
    base = "https://example.test/meet"

    run = run_discovery_preview(
        db,
        rule.id,
        discover=lambda _rule: [
            DiscoveredEvent(
                title="Canonical",
                page_title="Canonical",
                url=base,
                readiness_status="results_available",
                pdf_count=2,
                result_pdf_count=1,
                category_counts={"overall_results": 1, "other_pdf": 1},
                documents=[
                    DiscoveredDocument(url=f"{base}/result.pdf#old", filename="result.pdf", category="overall_results"),
                    DiscoveredDocument(url=f"{base}/result.pdf", filename="RESULT.pdf", category="other_pdf"),
                ],
            )
        ],
    )

    assert run.status == "failed"
    assert db.query(SourceEvent).count() == 0
    assert db.query(SourceEventDocument).count() == 0


def test_discovery_preview_rolls_back_source_catalog_on_mid_run_failure():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)

    run = run_discovery_preview(
        db,
        rule.id,
        discover=lambda _rule: [
            _event("Valid", "https://example.test/valid/"),
            _event("Invalid", "https://example.test/invalid/", status="bad_status"),
        ],
    )

    assert run.status == "failed"
    assert db.query(MonitorRun).count() == 1
    assert db.query(SourceEvent).count() == 0
    assert db.query(SourceEventDocument).count() == 0


def test_admin_sources_read_endpoint_does_not_seed_or_mutate_empty_db():
    db = _test_session()

    sources = admin_list_sources(db=db)

    assert sources == {"data": []}
    assert db.query(SourceSite).count() == 0
    assert db.query(SourceRule).count() == 0


def test_admin_source_endpoint_helpers_return_visible_platform_state():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)
    run_discovery_preview(db, rule.id, discover=lambda _rule: [_event("Visible Event", "https://example.test/visible/")])

    sources = admin_list_sources(db=db)
    events = admin_list_source_events(db=db)
    runs = admin_list_monitor_runs(db=db)

    assert sources["data"][0]["name"] == "SG Aquatics"
    rule_payload = sources["data"][0]["rules"][0]
    assert rule_payload["scheduleLabel"] == "Not configured"
    assert rule_payload["autoImportLabel"] == "Disabled / preview_only"
    assert rule_payload["lastRun"]["status"] == "succeeded"
    assert rule_payload["lastRun"]["eventsDiscovered"] == 1
    assert rule_payload["lastRun"]["eventsWithResults"] == 1
    assert rule_payload["lastRun"]["actionRequiredCount"] == 1
    assert "Cadence: Manual only" in rule_payload["policyLabels"]
    assert "Preview catalog categories: overall_results, other_pdf" in rule_payload["policyLabels"]
    assert events["data"][0]["title"] == "Visible Event"
    assert events["data"][0]["processingStatus"] == "results_not_imported"
    assert events["data"][0]["documentCount"] == 1
    assert runs["data"][0]["triggerType"] == "manual_api"
    assert runs["data"][0]["status"] == "succeeded"


def test_discovery_preview_persists_a_stable_event_manifest_fingerprint():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)
    url = "https://example.test/manifest/"

    run_discovery_preview(
        db, rule.id, discover=lambda _rule: [_event("Manifest Event", url)]
    )
    event = db.query(SourceEvent).one()
    first_fingerprint = getattr(event, "manifestSha256", None)

    assert isinstance(first_fingerprint, str)
    assert len(first_fingerprint) == 64

    run_discovery_preview(
        db, rule.id, discover=lambda _rule: [_event("Manifest Event", url)]
    )
    assert db.query(SourceEvent).one().manifestSha256 == first_fingerprint


def test_linked_edition_is_not_claimed_current_without_a_manifest_snapshot():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)
    run_discovery_preview(
        db,
        rule.id,
        discover=lambda _rule: [_event("Linked Event", "https://example.test/linked/")],
    )
    event = db.query(SourceEvent).one()
    db.add(
        CompetitionEdition(
            sourceKey="https://example.test/imported-package",
            sourceEventId=event.id,
            title="Linked Event",
            resolverVersion="test",
        )
    )
    db.commit()

    payload = admin_list_source_events(db=db)["data"][0]

    assert payload["processingStatus"] == "imported_without_manifest_baseline"


def test_linked_edition_with_current_baseline_is_collapsible_as_imported():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)
    run_discovery_preview(
        db,
        rule.id,
        discover=lambda _rule: [_event("Baseline Event", "https://example.test/baseline/")],
    )
    event = db.query(SourceEvent).one()
    edition = CompetitionEdition(
        sourceKey="https://example.test/baseline-package",
        sourceEventId=event.id,
        title="Baseline Event",
        resolverVersion="test",
    )
    db.add(edition)
    db.commit()
    edition.sourceManifestSha256 = event.manifestSha256
    edition.sourceManifestCaptureKind = "monitoring_baseline"
    edition.sourceManifestCapturedAt = datetime(2026, 9, 23, tzinfo=timezone.utc)

    payload = admin_list_source_events(db=db)["data"][0]

    assert payload["processingStatus"] == "imported_since_tracking"


def test_source_manifest_change_reopens_an_imported_competition_for_review():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)
    url = "https://example.test/changed/"
    run_discovery_preview(db, rule.id, discover=lambda _rule: [_event("Changed Event", url)])
    event = db.query(SourceEvent).one()
    edition = CompetitionEdition(
        sourceKey="https://example.test/changed-package",
        sourceEventId=event.id,
        sourceManifestSha256=event.manifestSha256,
        sourceManifestCaptureKind="monitoring_baseline",
        sourceManifestCapturedAt=datetime(2026, 9, 23, tzinfo=timezone.utc),
        title="Changed Event",
        resolverVersion="test",
    )
    db.add(edition)
    db.commit()

    changed = DiscoveredEvent(
        title="Changed Event",
        page_title="Changed Event",
        url=url,
        readiness_status="results_available",
        pdf_count=2,
        result_pdf_count=2,
        category_counts={"overall_results": 2},
        documents=[
            DiscoveredDocument(url=f"{url.rstrip('/')}/result.pdf", filename="result.pdf", category="overall_results"),
            DiscoveredDocument(url=f"{url.rstrip('/')}/revised-result.pdf", filename="revised-result.pdf", category="overall_results"),
        ],
    )
    run_discovery_preview(db, rule.id, discover=lambda _rule: [changed])

    assert admin_list_source_events(db=db)["data"][0]["processingStatus"] == "source_changed_since_import"


def test_removed_source_page_is_retained_without_becoming_an_alert():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)
    url = "https://example.test/retained/"
    run_discovery_preview(db, rule.id, discover=lambda _rule: [_event("Retained Event", url)])
    event = db.query(SourceEvent).one()
    db.add(CompetitionEdition(
        sourceKey="https://example.test/retained-package",
        sourceEventId=event.id,
        sourceManifestSha256=event.manifestSha256,
        sourceManifestCaptureKind="monitoring_baseline",
        sourceManifestCapturedAt=datetime(2026, 9, 23, tzinfo=timezone.utc),
        title="Retained Event",
        resolverVersion="test",
    ))
    db.commit()

    run_discovery_preview(db, rule.id, discover=lambda _rule: [])

    payload = admin_list_source_events(db=db)["data"][0]
    assert payload["isCurrentlyListed"] is False
    assert payload["processingStatus"] == "imported_since_tracking"


def test_backfill_links_only_exact_source_page_with_imported_document_evidence():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)
    source_page = "https://example.test/55th-snag/"
    run_discovery_preview(
        db,
        rule.id,
        discover=lambda _rule: [_event("55th SNAG 2025", source_page)],
    )
    event = db.query(SourceEvent).one()
    edition = CompetitionEdition(
        sourceKey=source_page,
        title="55th SNAG 2025",
        resolverVersion="test",
    )
    raw = RawDocument(sha256="a" * 64, byteSize=1, storagePath="/tmp/source.pdf")
    db.add_all([edition, raw])
    db.flush()
    segment = CompetitionSegment(
        competitionEditionId=edition.id,
        key="Results",
        name="Results",
        resolutionStatus="unknown",
        resolverVersion="test",
    )
    db.add(segment)
    db.flush()
    day = CompetitionDay(
        competitionSegmentId=segment.id,
        resolutionStatus="unknown",
        resolverVersion="test",
    )
    db.add(day)
    db.flush()
    db.add_all([
        CompetitionSession(
            competitionDayId=day.id,
            sourceDocumentSha=raw.sha256,
            resolutionStatus="unknown",
            resolverVersion="test",
        ),
        SourceReference(
            rawDocumentId=raw.id,
            sourceType="sg-aquatics",
            sourcePageUrl=source_page,
            sourceIdentity="fixture:55th-snag",
        ),
    ])
    db.commit()

    summary = source_monitoring.backfill_source_event_links(db)

    db.refresh(edition)
    assert summary == {
        "linked": 1,
        "skipped_ambiguous": 0,
        "skipped_no_exact_match": 0,
        "skipped_missing_source_evidence": 0,
    }
    assert edition.sourceEventId == event.id
    assert edition.sourceManifestSha256 is None
    assert edition.sourceManifestCaptureKind is None
    assert edition.sourceManifestCapturedAt is None


def test_backfill_never_uses_title_similarity_without_exact_source_page_evidence():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)
    run_discovery_preview(
        db,
        rule.id,
        discover=lambda _rule: [_event("Recurring Championship 2026", "https://example.test/official-page/")],
    )
    edition = CompetitionEdition(
        sourceKey="https://example.test/another-page/",
        title="Recurring Championship 2026",
        resolverVersion="test",
    )
    db.add(edition)
    db.commit()

    summary = source_monitoring.backfill_source_event_links(db)

    assert summary["linked"] == 0
    assert summary["skipped_no_exact_match"] == 1
    assert edition.sourceEventId is None


def test_backfill_rejects_duplicate_source_events_for_the_same_page():
    db = _test_session()
    site, rule = ensure_default_sgaquatics_source(db)
    duplicate_rule = SourceRule(
        sourceSiteId=site.id,
        name="Duplicate SG Aquatics catalogue",
        indexUrl="https://example.test/duplicate-index",
        enabled=True,
        cadencePolicy="{}",
        activeWindowPolicy="{}",
        staleWindowPolicy="{}",
        categoriesToArchive="[]",
        categoriesToPreview="[]",
        categoriesAllowedForImport="[]",
    )
    db.add(duplicate_rule)
    db.flush()
    source_page = "https://example.test/duplicated-event/"
    run_discovery_preview(db, rule.id, discover=lambda _rule: [_event("Duplicated event", source_page)])
    run_discovery_preview(db, duplicate_rule.id, discover=lambda _rule: [_event("Duplicated event", source_page)])
    edition = CompetitionEdition(sourceKey=source_page, title="Duplicated event", resolverVersion="test")
    db.add(edition)
    db.commit()

    summary = source_monitoring.backfill_source_event_links(db)

    assert summary["linked"] == 0
    assert summary["skipped_ambiguous"] == 1
    assert edition.sourceEventId is None


def test_exact_import_source_page_acknowledges_current_manifest():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)
    source_page = "https://example.test/imported-now/"
    run_discovery_preview(
        db,
        rule.id,
        discover=lambda _rule: [_event("Imported now", source_page)],
    )
    event = db.query(SourceEvent).one()
    edition = CompetitionEdition(
        sourceKey="https://example.test/imported-now",
        title="Imported now",
        resolverVersion="test",
    )
    db.add(edition)
    db.commit()

    source_monitoring.acknowledge_imported_source_manifest(
        db,
        edition,
        source_key=source_page,
        source_event_id=event.id,
        expected_manifest_sha256=event.manifestSha256,
        imported_document_urls=[f"{source_page}result.pdf"],
        captured_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )

    payload = admin_list_source_events(db=db)["data"][0]
    assert edition.sourceEventId == event.id
    assert edition.sourceManifestSha256 == event.manifestSha256
    assert edition.sourceManifestCaptureKind == "imported"
    assert payload["processingStatus"] == "imported_links_unchanged_bytes_unchecked"


def test_acknowledgement_uses_live_documents_and_persisted_rule_categories():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)
    rule.categoriesAllowedForImport = '["other_pdf"]'
    source_page = "https://example.test/live-documents/"
    observed = replace(_event("Live documents", source_page), documents=[
        DiscoveredDocument(url=f"{source_page}overall.pdf", filename="overall.pdf", category="overall_results"),
        DiscoveredDocument(url=f"{source_page}old.pdf", filename="old.pdf", category="other_pdf"),
        DiscoveredDocument(url=f"{source_page}new.pdf", filename="new.pdf", category="other_pdf"),
    ])
    run_discovery_preview(db, rule.id, discover=lambda _rule: [observed])
    current = replace(_event("Live documents", source_page), documents=[
        DiscoveredDocument(url=f"{source_page}overall.pdf", filename="overall.pdf", category="overall_results"),
        DiscoveredDocument(url=f"{source_page}new.pdf", filename="new.pdf", category="other_pdf"),
    ])
    run_discovery_preview(db, rule.id, discover=lambda _rule: [current])
    event = db.query(SourceEvent).one()
    edition = CompetitionEdition(sourceKey=source_page, title="Live documents", resolverVersion="test")
    db.add(edition)
    db.commit()

    source_monitoring.acknowledge_imported_source_manifest(
        db,
        edition,
        source_key=source_page,
        source_event_id=event.id,
        expected_manifest_sha256=event.manifestSha256,
        imported_document_urls=[f"{source_page}new.pdf"],
    )

    assert edition.sourceManifestSha256 == event.manifestSha256


def test_acknowledgement_allows_only_declared_curated_subsets():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)
    source_page = "https://example.test/curated-subset/"
    observed = _event("Curated subset", source_page)
    observed.documents.append(
        DiscoveredDocument(url=f"{source_page}second.pdf", filename="second.pdf", category="overall_results")
    )
    run_discovery_preview(db, rule.id, discover=lambda _rule: [observed])
    event = db.query(SourceEvent).one()
    edition = CompetitionEdition(sourceKey=source_page, title="Curated subset", resolverVersion="test")
    db.add(edition)
    db.commit()

    with pytest.raises(ValueError, match="partial source import"):
        source_monitoring.acknowledge_imported_source_manifest(
            db,
            edition,
            source_key=source_page,
            source_event_id=event.id,
            expected_manifest_sha256=event.manifestSha256,
            imported_document_urls=[f"{source_page}result.pdf"],
        )
    source_monitoring.acknowledge_imported_source_manifest(
        db,
        edition,
        source_key=source_page,
        source_event_id=event.id,
        expected_manifest_sha256=event.manifestSha256,
        imported_document_urls=[f"{source_page}result.pdf"],
        is_curated_subset=True,
    )

    assert edition.sourceManifestSha256 == event.manifestSha256


def test_source_bound_acknowledgement_rejects_a_stale_or_partial_package():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)
    source_page = "https://example.test/stale-package/"
    run_discovery_preview(
        db,
        rule.id,
        discover=lambda _rule: [_event("Stale package", source_page)],
    )
    event = db.query(SourceEvent).one()
    expected_manifest = event.manifestSha256
    edition = CompetitionEdition(sourceKey=source_page, title="Stale package", resolverVersion="test")
    db.add(edition)
    db.commit()

    with pytest.raises(ValueError, match="Imported documents"):
        source_monitoring.acknowledge_imported_source_manifest(
            db,
            edition,
            source_key=source_page,
            source_event_id=event.id,
            expected_manifest_sha256=expected_manifest,
            imported_document_urls=[f"{source_page}stale-result.pdf"],
        )
    assert edition.sourceManifestSha256 is None

    changed = _event("Stale package", source_page)
    changed.documents[0] = DiscoveredDocument(
        url=f"{source_page}replacement-result.pdf",
        filename="replacement-result.pdf",
        category="overall_results",
    )
    run_discovery_preview(db, rule.id, discover=lambda _rule: [changed])

    with pytest.raises(ValueError, match="Source page changed"):
        source_monitoring.acknowledge_imported_source_manifest(
            db,
            edition,
            source_key=source_page,
            source_event_id=event.id,
            expected_manifest_sha256=expected_manifest,
            imported_document_urls=[f"{source_page}result.pdf"],
        )
    assert edition.sourceManifestSha256 is None


def test_discovery_preview_records_failed_monitor_run():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)

    def fail(_rule):
        raise RuntimeError("source unavailable")

    run = run_discovery_preview(db, rule.id, discover=fail)

    assert run.status == "failed"
    assert run.finishedAt is not None
    assert "source unavailable" in run.errorMessage
    assert db.query(MonitorRun).count() == 1
