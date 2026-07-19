"""Tests for source monitoring platform primitives."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Meet, MonitorRun, RelayLeg, RelayResult, Result, SourceEvent, SourceEventDocument, SourceRule, SourceSite, Swimmer
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


def test_discovery_preview_uses_canonical_document_url_as_identity():
    db = _test_session()
    _site, rule = ensure_default_sgaquatics_source(db)
    base = "https://example.test/meet"

    run = run_discovery_preview(
        db,
        rule.id,
        discover=lambda _rule: [
            DiscoveredEvent(
                title="Same PDF Different Metadata",
                page_title="Same PDF Different Metadata",
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

    assert run.status == "succeeded"
    assert db.query(SourceEventDocument).count() == 1
    document = db.query(SourceEventDocument).one()
    assert document.url == f"{base}/result.pdf"
    # Latest discovered metadata is retained as metadata, not as identity.
    assert document.filename == "RESULT.pdf"
    assert document.category == "other_pdf"


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
    assert events["data"][0]["documentCount"] == 1
    assert runs["data"][0]["triggerType"] == "manual_api"
    assert runs["data"][0]["status"] == "succeeded"


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
