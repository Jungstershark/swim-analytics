"""Tests for Slice 3 browser read models."""

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.browser import (
    browser_data_quality,
    browser_event,
    browser_meet,
    browser_overview,
    browser_swimmer_detail,
    list_browser_swimmers,
    make_event_key,
)
from app.database import Base
from app.models import Meet, ParseJob, RawDocument, RelayLeg, RelayResult, Result, Swimmer


def _test_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)()


def _seed_browser_fixture(db: Session) -> dict[str, object]:
    raw = RawDocument(
        sha256="abc123",
        byteSize=42,
        contentType="application/pdf",
        storagePath="/tmp/abc123.pdf",
        originalFilename="result.pdf",
        category="overall_results",
    )
    db.add(raw)
    db.flush()
    parse_job = ParseJob(
        rawDocumentId=raw.id,
        parserName="hytek",
        parserVersion="hytek-v1",
        status="succeeded",
        confidenceScore=100,
        confidencePassed=True,
    )
    meet = Meet(name="56th SNAG Seniors", startDate=datetime(2026, 3, 17), parserFormat="hytek")
    swimmer = Swimmer(name="Pung, Zhi En Timothy", age=17, team="Aquatic Performance Swim Club")
    second = Swimmer(name="Chew, Wen Yu Titus", age=17, team="Aquatic Performance Swim Club")
    suspicious = Swimmer(
        name="Abdul Khair, Daria Suhayr3 W) r1:02.53 Mark, Ivan Royston LC Meter Freestyle Seed Time",
        age=11,
        team="X Lab",
    )
    db.add_all([parse_job, meet, swimmer, second, suspicious])
    db.flush()

    results = [
        Result(
            swimmerId=swimmer.id,
            meetId=meet.id,
            event="Men 15 & Over 50 LC Meter Freestyle",
            time="24.51",
            seedTime="25.00",
            placement=1,
            round="Final",
            swimDate=datetime(2026, 3, 17),
            sourceDocumentSha256=raw.sha256,
            parseJobId=parse_job.id,
            sourceEventNumber="17",
        ),
        Result(
            swimmerId=second.id,
            meetId=meet.id,
            event="Men 15 & Over 50 LC Meter Freestyle",
            time="25.11",
            placement=2,
            round="Final",
            swimDate=datetime(2026, 3, 17),
            sourceDocumentSha256=raw.sha256,
            parseJobId=parse_job.id,
            sourceEventNumber="17",
        ),
        Result(
            swimmerId=swimmer.id,
            meetId=meet.id,
            event="Men 15 & Over 100 LC Meter Freestyle",
            time="54.99",
            placement=3,
            round="Final",
            swimDate=datetime(2026, 3, 18),
            sourceDocumentSha256=raw.sha256,
            parseJobId=parse_job.id,
            sourceEventNumber="18",
        ),
        Result(
            swimmerId=suspicious.id,
            meetId=meet.id,
            event="Women 11-12 50 LC Meter Freestyle",
            time="31.00",
            placement=1,
            round="Final",
            swimDate=datetime(2026, 3, 17),
            sourceEventNumber="31",
        ),
    ]
    db.add_all(results)
    relay = RelayResult(
        meetId=meet.id,
        event="Men 15 & Over 4x50 LC Meter Freestyle Relay",
        teamName="Aquatic Performance Swim Club",
        relayLetter="A",
        time="1:40.00",
        placement=1,
        round="Final",
        swimDate=datetime(2026, 3, 17),
        sourceDocumentSha256=raw.sha256,
        parseJobId=parse_job.id,
        sourceEventNumber="101",
    )
    db.add(relay)
    db.flush()
    db.add_all([
        RelayLeg(relayResultId=relay.id, legNumber=1, swimmerId=swimmer.id, swimmerName=swimmer.name, age=17, splitTime="24.50"),
        RelayLeg(relayResultId=relay.id, legNumber=2, swimmerId=second.id, swimmerName=second.name, age=17, splitTime="24.70"),
    ])
    db.commit()
    return {"meet": meet, "swimmer": swimmer, "second": second, "suspicious": suspicious, "relay": relay}


def test_browser_swimmer_list_owns_find_myself_without_per_row_loop():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    statements: list[str] = []
    engine = db.get_bind()

    @event.listens_for(engine, "before_cursor_execute")
    def _count_queries(*args):
        statements.append(args[2])

    payload = list_browser_swimmers(db, q="Pung", limit=100)

    assert payload["pagination"]["total"] == 1
    row = payload["data"][0]
    assert row["id"] == seeded["swimmer"].id
    assert row["individual_result_count"] == 2
    assert row["relay_result_count"] == 1
    assert row["meet_count"] == 1
    assert row["event_count"] == 2
    assert row["latest_meet"]["name"] == "56th SNAG Seniors"
    # Contract guard: list/card counts must not issue a count/latest query per row.
    assert len(statements) <= 4


def test_browser_meet_returns_event_index_not_full_rows():
    db = _test_session()
    seeded = _seed_browser_fixture(db)

    payload = browser_meet(db, seeded["meet"].id)

    assert payload["meet"]["name"] == "56th SNAG Seniors"
    assert payload["summary"]["individual_result_count"] == 4
    assert payload["summary"]["relay_result_count"] == 1
    relay_group = next(g for g in payload["event_groups"] if "Relay" in g["event_label"])
    assert relay_group["relay_count"] == 1
    assert relay_group["individual_count"] == 0
    assert relay_group["derived"] is True
    assert relay_group["normalization_status"] == "raw_event_string"
    assert "results" not in relay_group


def test_browser_event_is_paginated_row_owner_with_discriminators_and_sources():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    event_key = make_event_key(seeded["meet"].id, "Men 15 & Over 50 LC Meter Freestyle", "17")

    payload = browser_event(db, meet_id=seeded["meet"].id, event_key=event_key, limit=1)

    assert payload["event_group"]["event_key"] == event_key
    assert payload["pagination"]["total"] == 2
    assert payload["pagination"]["total_pages"] == 2
    row = payload["data"][0]
    assert row["row_type"] == "individual"
    assert row["source"]["source_scope"] == "result"
    assert row["swimmer"]["name"] == "Pung, Zhi En Timothy"


def test_browser_event_includes_relay_rows_and_leg_identity_contract():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    event_key = make_event_key(seeded["meet"].id, "Men 15 & Over 4x50 LC Meter Freestyle Relay", "101")

    payload = browser_event(db, meet_id=seeded["meet"].id, event_key=event_key)

    assert payload["pagination"]["total"] == 1
    row = payload["data"][0]
    assert row["row_type"] == "relay"
    assert row["source"]["source_scope"] == "parent_relay_result"
    assert row["legs"][0]["matched_by"] == "relay_leg_swimmer_id"
    assert row["legs"][0]["identity_match_confidence"] == "high"


def test_browser_swimmer_detail_keeps_relay_history_out_of_pbs():
    db = _test_session()
    seeded = _seed_browser_fixture(db)

    payload = browser_swimmer_detail(db, seeded["swimmer"].id)

    assert payload["stats"]["individual_result_count"] == 2
    assert payload["stats"]["relay_result_count"] == 1
    assert {pb["event"] for pb in payload["personal_bests"]} == {
        "Men 15 & Over 50 LC Meter Freestyle",
        "Men 15 & Over 100 LC Meter Freestyle",
    }
    assert payload["relay_history"][0]["row_type"] == "relay"


def test_browser_data_quality_surfaces_parser_contaminated_names_and_missing_sources():
    db = _test_session()
    _seed_browser_fixture(db)

    payload = browser_data_quality(db)
    warning_types = {w["type"] for w in payload["data"]}

    assert "suspicious_swimmer_name" in warning_types
    assert "missing_result_source" in warning_types
    suspicious = next(w for w in payload["data"] if w["type"] == "suspicious_swimmer_name")
    assert suspicious["entity_kind"] == "swimmer"
    assert suspicious["source_fields"] == ["Swimmer.name"]


def test_browser_get_helpers_are_read_only_for_domain_counts():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    event_key = make_event_key(seeded["meet"].id, "Men 15 & Over 50 LC Meter Freestyle", "17")
    before = _domain_counts(db)

    browser_overview(db)
    list_browser_swimmers(db, limit=100)
    browser_swimmer_detail(db, seeded["swimmer"].id)
    browser_meet(db, seeded["meet"].id)
    browser_event(db, meet_id=seeded["meet"].id, event_key=event_key)
    browser_data_quality(db)

    assert _domain_counts(db) == before


def test_browser_event_invalid_key_returns_empty_warning_not_fuzzy_match():
    db = _test_session()
    seeded = _seed_browser_fixture(db)

    payload = browser_event(db, meet_id=seeded["meet"].id, event_key="bad-key")

    assert payload["event_group"] is None
    assert payload["data"] == []
    assert payload["warnings"][0]["type"] == "event_key_not_found"


def test_browser_api_routes_smoke_with_real_response_contracts():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    event_key = make_event_key(seeded["meet"].id, "Men 15 & Over 50 LC Meter Freestyle", "17")

    def _override_db():
        yield db

    main.app.dependency_overrides[main.get_db] = _override_db
    try:
        client = TestClient(main.app)

        overview = client.get("/api/browser/overview")
        assert overview.status_code == 200
        assert overview.json()["counts"]["meets"] == 1

        swimmers = client.get("/api/browser/swimmers", params={"q": "Pung", "limit": 5})
        assert swimmers.status_code == 200
        assert swimmers.json()["data"][0]["relay_result_count"] == 1

        swimmer = client.get(f"/api/browser/swimmers/{seeded['swimmer'].id}")
        assert swimmer.status_code == 200
        assert swimmer.json()["stats"]["relay_result_count"] == 1

        meet = client.get(f"/api/browser/meets/{seeded['meet'].id}")
        assert meet.status_code == 200
        assert meet.json()["summary"]["event_group_count"] == 4

        event_response = client.get(
            "/api/browser/events",
            params={"meet_id": seeded["meet"].id, "event_key": event_key, "limit": 1},
        )
        assert event_response.status_code == 200
        assert event_response.json()["pagination"]["total"] == 2

        data_quality = client.get("/api/browser/data-quality")
        assert data_quality.status_code == 200
        assert "suspicious_swimmer_name" in data_quality.json()["summary"]
    finally:
        main.app.dependency_overrides.clear()


def _domain_counts(db: Session) -> dict[str, int]:
    return {
        "meets": db.query(Meet).count(),
        "swimmers": db.query(Swimmer).count(),
        "results": db.query(Result).count(),
        "relay_results": db.query(RelayResult).count(),
        "relay_legs": db.query(RelayLeg).count(),
        "raw_documents": db.query(RawDocument).count(),
    }
