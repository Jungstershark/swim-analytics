"""Tests for Slice 3 browser read models."""
import json

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
    list_browser_athletes,
    list_browser_swimmers,
    make_event_key,
    no_time_warning,
    source_warning,
)
from app.database import Base
from app.entity_resolution import backfill_athlete_profiles
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
        parserVersion="hytek-v2",
        status="succeeded",
        confidenceScore=100,
        confidencePassed=True,
    )
    meet = Meet(name="56th SNAG Seniors", startDate=datetime(2026, 3, 17), parserFormat="hytek")
    swimmer = Swimmer(name="Pung, Zhi En Timothy", age=17, team="Aquatic Performance Swim Club")
    second = Swimmer(name="Chew, Wen Yu Titus", age=17, team="Aquatic Performance Swim Club")
    suspicious = Swimmer(
        name="Abdul Khair, Daria Suhayr3 W) r1:02.53 Mark, Ivan Royston",
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
            resultStatus="finished",
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
            resultStatus="finished",
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
            resultStatus="finished",
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
            resultStatus="finished",
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
        resultStatus="finished",
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
    backfill_athlete_profiles(db)
    db.commit()
    return {"meet": meet, "swimmer": swimmer, "second": second, "suspicious": suspicious, "relay": relay}


def test_browser_swimmer_list_deduplicates_same_meet_hybrid_card_aggregates_without_per_row_loop():
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
    assert row["event_count"] == 3
    assert row["latest_meet"]["name"] == "56th SNAG Seniors"
    # Contract guard: list/card counts must not issue a count/latest query per row.
    assert len(statements) <= 4


def test_browser_swimmer_list_aggregates_one_athlete_profile_across_ages():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    swimmer = seeded["swimmer"]
    profile_id = swimmer.athleteProfileId
    aged_row = Swimmer(
        name=swimmer.name,
        nameKey="pung|zhientimothy",
        teamKey="aquaticperformanceswimclub",
        age=18,
        team=swimmer.team,
        athleteProfileId=profile_id,
    )
    db.add(aged_row)
    db.flush()
    db.add(Result(
        swimmerId=aged_row.id,
        meetId=seeded["meet"].id,
        event="Men 15 & Over 200 LC Meter Freestyle",
        time="2:00.00",
        resultStatus="finished",
        swimDate=datetime(2026, 3, 19),
    ))
    db.commit()

    payload = list_browser_athletes(db, q="Pung", limit=100)

    assert payload["pagination"]["total"] == 1
    assert payload["data"][0]["athlete_profile_id"] == profile_id
    assert payload["data"][0]["ages"] == [17, 18]
    assert payload["data"][0]["individual_result_count"] == 3


def test_browser_swimmer_list_includes_relay_only_card_aggregates():
    db = _test_session()
    meet = Meet(name="Relay Only Meet", startDate=datetime(2026, 7, 1), parserFormat="hytek")
    swimmer = Swimmer(name="Relay, Only", age=15, team="Example Club")
    db.add_all([meet, swimmer])
    db.flush()
    relay = RelayResult(
        meetId=meet.id,
        event="Mixed 4x50 SC Meter Freestyle Relay",
        teamName="Example Club",
        relayLetter="A",
        time="1:50.00",
        round="Timed Final",
        swimDate=datetime(2026, 7, 1),
    )
    db.add(relay)
    db.flush()
    db.add(RelayLeg(
        relayResultId=relay.id,
        legNumber=1,
        swimmerId=swimmer.id,
        swimmerName=swimmer.name,
        age=swimmer.age,
    ))
    db.commit()
    backfill_athlete_profiles(db)
    db.commit()

    row = list_browser_swimmers(db)["data"][0]

    assert row["individual_result_count"] == 0
    assert row["relay_result_count"] == 1
    assert row["meet_count"] == 1
    assert row["event_count"] == 1
    assert row["latest_meet"]["id"] == meet.id


def test_browser_swimmer_list_latest_meet_is_scoped_to_each_swimmer_on_tied_dates():
    db = _test_session()
    date = datetime(2026, 7, 1)
    meet_a = Meet(name="Meet A", startDate=date, parserFormat="hytek")
    meet_b = Meet(name="Meet B", startDate=date, parserFormat="hytek")
    swimmer_a = Swimmer(name="Athlete, A", team="A Club")
    swimmer_b = Swimmer(name="Athlete, B", team="B Club")
    db.add_all([meet_a, meet_b, swimmer_a, swimmer_b])
    db.flush()
    relay_a = RelayResult(meetId=meet_a.id, event="Relay A", teamName="A Club")
    relay_b = RelayResult(meetId=meet_b.id, event="Relay B", teamName="B Club")
    db.add_all([relay_a, relay_b])
    db.flush()
    db.add_all([
        RelayLeg(relayResultId=relay_a.id, legNumber=1, swimmerId=swimmer_a.id, swimmerName=swimmer_a.name),
        RelayLeg(relayResultId=relay_b.id, legNumber=1, swimmerId=swimmer_b.id, swimmerName=swimmer_b.name),
    ])
    db.commit()
    backfill_athlete_profiles(db)
    db.commit()

    rows = {row["name"]: row for row in list_browser_swimmers(db, limit=100)["data"]}

    assert rows[swimmer_a.name]["latest_meet"]["id"] == meet_a.id
    assert rows[swimmer_b.name]["latest_meet"]["id"] == meet_b.id


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


def test_browser_event_exposes_official_no_swim_status_without_false_no_time_warning():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    ns_result = Result(
        swimmerId=seeded["swimmer"].id,
        meetId=seeded["meet"].id,
        event="Men 15 & Over 200 LC Meter Freestyle",
        time=None,
        placement=None,
        isDQ=False,
        resultStatus="dns",
        round="Prelim",
        swimDate=datetime(2026, 3, 18),
        sourceDocumentSha256="abc123",
        parseJobId=1,
        sourceEventNumber="19",
    )
    db.add(ns_result)
    db.commit()

    event_key = make_event_key(seeded["meet"].id, ns_result.event, "19")
    row = browser_event(db, meet_id=seeded["meet"].id, event_key=event_key)["data"][0]

    assert row["status"] == "dns"
    assert "no_time_result" not in {warning["type"] for warning in row["warnings"]}


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


def test_browser_relay_linked_suspicious_name_is_flagged_instead_of_high_confidence():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    relay = seeded["relay"]
    suspicious = seeded["suspicious"]
    db.add(RelayLeg(
        relayResultId=relay.id,
        legNumber=3,
        swimmerId=suspicious.id,
        swimmerName=suspicious.name,
        age=suspicious.age,
    ))
    db.commit()
    event_key = make_event_key(seeded["meet"].id, relay.event, relay.sourceEventNumber)

    row = browser_event(db, meet_id=seeded["meet"].id, event_key=event_key)["data"][0]
    leg = next(leg for leg in row["legs"] if leg["swimmer_id"] == suspicious.id)

    assert leg["identity_match_confidence"] == "needs_review"
    assert leg["identity_status"] == "needs_review"
    assert leg["warning_count"] == 1
    assert row["warning_count"] == 1
    warning = next(warning for warning in row["warnings"] if warning["type"] == "relay_identity_needs_review")
    assert warning["message"] == "This relay swimmer name could not be verified."
    detail_leg = next(
        leg for leg in browser_swimmer_detail(db, suspicious.id)["relay_history"][0]["legs"]
        if leg["swimmer_id"] == suspicious.id
    )
    assert detail_leg["identity_match_confidence"] == "needs_review"


def test_browser_relay_source_name_is_checked_even_when_linked_profile_name_is_clean():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    relay = seeded["relay"]
    swimmer = seeded["swimmer"]
    leg = next(leg for leg in relay.legs if leg.swimmerId == swimmer.id)
    leg.swimmerName = "Corrupt R1:02.53 Name"
    db.commit()
    event_key = make_event_key(seeded["meet"].id, relay.event, relay.sourceEventNumber)

    event_row = browser_event(db, meet_id=seeded["meet"].id, event_key=event_key)["data"][0]
    event_leg = next(item for item in event_row["legs"] if item["swimmer_id"] == swimmer.id)
    detail_leg = next(
        item for item in browser_swimmer_detail(db, swimmer.id)["relay_history"][0]["legs"]
        if item["swimmer_id"] == swimmer.id
    )

    for projected_leg in (event_leg, detail_leg):
        assert projected_leg["swimmer_name"] == "Corrupt R1:02.53 Name"
        assert projected_leg["identity_match_confidence"] == "needs_review"
        assert projected_leg["identity_status"] == "needs_review"
        assert projected_leg["warning_count"] == 1


def test_browser_relay_warning_uses_plain_athlete_facing_copy():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    relay = seeded["relay"]
    relay.legParseStatus = "partial"
    relay.legParseWarning = "leg 3: corrupted name structure; missing safe legs [3]"
    db.commit()
    event_key = make_event_key(seeded["meet"].id, relay.event, relay.sourceEventNumber)

    row = browser_event(db, meet_id=seeded["meet"].id, event_key=event_key)["data"][0]
    warning = next(warning for warning in row["warnings"] if warning["type"] == "relay_legs_quarantined")

    assert warning["message"] == "Some relay swimmers could not be verified from the official result."
    assert "corrupted name structure" not in warning["message"]


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


def test_browser_unlinked_source_swimmer_keeps_its_legacy_detail_route():
    db = _test_session()
    meet = Meet(name="Evidence Gaps Meet", startDate=datetime(2026, 7, 1), parserFormat="hytek")
    swimmer = Swimmer(name="Unknown, Club", age=15, team=None)
    db.add_all([meet, swimmer])
    db.flush()
    db.add(Result(
        swimmerId=swimmer.id,
        meetId=meet.id,
        event="Girls 50 LC Meter Freestyle",
        time="30.00",
        resultStatus="finished",
        swimDate=datetime(2026, 7, 1),
    ))
    db.commit()

    payload = browser_swimmer_detail(db, swimmer.id)

    assert payload is not None
    assert payload["swimmer"]["source_swimmer_id"] == swimmer.id
    assert payload["swimmer"]["identity_status"] == "source_row_unlinked"
    assert payload["stats"]["individual_result_count"] == 1
    catalogue = list_browser_athletes(db)
    assert catalogue["pagination"]["total"] == 1
    assert catalogue["data"][0]["source_swimmer_id"] == swimmer.id
    assert catalogue["data"][0]["athlete_profile_id"] is None
    assert browser_overview(db)["counts"]["swimmers"] == 1


def test_browser_swimmer_detail_includes_relay_only_meets_and_events_in_generic_totals():
    db = _test_session()
    meet = Meet(name="Relay Only Meet", startDate=datetime(2026, 7, 1), parserFormat="hytek")
    swimmer = Swimmer(name="Relay, Only", age=15, team="Example Club")
    db.add_all([meet, swimmer])
    db.flush()
    relay = RelayResult(
        meetId=meet.id,
        event="Mixed 4x50 SC Meter Freestyle Relay",
        teamName="Example Club",
        relayLetter="A",
        time="1:50.00",
        round="Timed Final",
        swimDate=datetime(2026, 7, 1),
    )
    db.add(relay)
    db.flush()
    db.add(RelayLeg(
        relayResultId=relay.id,
        legNumber=1,
        swimmerId=swimmer.id,
        swimmerName=swimmer.name,
        age=swimmer.age,
    ))
    db.commit()
    backfill_athlete_profiles(db)
    db.commit()

    payload = browser_swimmer_detail(db, swimmer.id)

    assert payload["stats"]["individual_result_count"] == 0
    assert payload["stats"]["relay_result_count"] == 1
    assert payload["stats"]["meet_count"] == 1
    assert payload["stats"]["event_count"] == 1
    assert payload["course_history"] == []


def test_browser_swimmer_detail_groups_history_course_first_with_fastest_recorded():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    swimmer = seeded["swimmer"]
    meet = seeded["meet"]
    db.add_all([
        Result(
            swimmerId=swimmer.id,
            meetId=meet.id,
            event="Men Open 50 SC Meter Freestyle",
            time="23.90",
            placement=2,
            round="Final",
            resultStatus="finished",
            swimDate=datetime(2026, 2, 1),
            splits=json.dumps([{"distance": 25, "cumulative": "11.50", "split": None}]),
            sourceDocumentSha256="abc123",
            parseJobId=1,
            sourceEventNumber="201",
        ),
        Result(
            swimmerId=swimmer.id,
            meetId=meet.id,
            event="Men 25-29 50 SC Meter Freestyle",
            time="23.70",
            placement=1,
            round="Final",
            resultStatus="finished",
            swimDate=datetime(2026, 2, 2),
            sourceDocumentSha256="abc123",
            parseJobId=1,
            sourceEventNumber="202",
        ),
        Result(
            swimmerId=swimmer.id,
            meetId=meet.id,
            event="Men Open 50 SC Meter Freestyle",
            time=None,
            round="Final",
            resultStatus="dq",
            isDQ=True,
            swimDate=datetime(2026, 2, 3),
            sourceDocumentSha256="abc123",
            parseJobId=1,
            sourceEventNumber="203",
        ),
        Result(
            swimmerId=swimmer.id,
            meetId=meet.id,
            event="Men Open 50 SC Meter Freestyle",
            time="1.00",
            round="Final",
            resultStatus="unknown",
            swimDate=datetime(2026, 2, 4),
            sourceDocumentSha256="abc123",
            parseJobId=1,
            sourceEventNumber="204",
        ),
    ])
    db.commit()

    payload = browser_swimmer_detail(db, swimmer.id)

    assert [group["course"] for group in payload["course_history"]] == ["LCM", "SCM"]
    scm = next(group for group in payload["course_history"] if group["course"] == "SCM")
    event = scm["events"][0]
    assert event["event"] == "50 Freestyle"
    assert payload["stats"]["event_count"] == 4
    assert event["canonical_event_key"] == "scm-50-freestyle"
    assert event["fastest_recorded"]["time"] == "23.70"
    assert event["performance_count"] == 4
    assert event["finished_performance_count"] == 2
    assert [row["swim_date"] for row in event["performances"]] == ["2026-02-01", "2026-02-02", "2026-02-03", "2026-02-04"]
    assert event["split_coverage"] == {"available": 1, "total": 4}
    assert event["performances"][0]["splits"][0]["distance"] == 25


def test_athlete_visible_warning_copy_does_not_expose_parser_or_database_jargon():
    messages = [
        source_warning("result", 1, None, None)[0]["message"],
        no_time_warning("result", 1, False, "not-a-time")[0]["message"],
    ]

    banned = {"hash", "parse", "parser", "provenance", "database", "job"}
    assert all(not any(word in message.lower() for word in banned) for message in messages)


def test_browser_swimmer_detail_does_not_merge_lcm_and_scm_bests():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    swimmer = seeded["swimmer"]
    meet = seeded["meet"]
    db.add(Result(
        swimmerId=swimmer.id,
        meetId=meet.id,
        event="Men Open 50 SC Meter Freestyle",
        time="23.00",
        round="Final",
        resultStatus="finished",
        swimDate=datetime(2026, 2, 1),
        sourceDocumentSha256="abc123",
        parseJobId=1,
        sourceEventNumber="201",
    ))
    db.commit()

    payload = browser_swimmer_detail(db, swimmer.id)
    lcm = next(group for group in payload["course_history"] if group["course"] == "LCM")
    scm = next(group for group in payload["course_history"] if group["course"] == "SCM")

    assert next(event for event in lcm["events"] if event["event"] == "50 Freestyle")["fastest_recorded"]["time"] == "24.51"
    assert scm["events"][0]["fastest_recorded"]["time"] == "23.00"


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


def test_suspicious_name_sql_filter_matches_python_projection_and_exposes_warning_count():
    db = _test_session()
    seeded = _seed_browser_fixture(db)

    warned = list_browser_swimmers(db, has_warnings=True, limit=100)
    clean = list_browser_swimmers(db, has_warnings=False, limit=100)

    assert [row["id"] for row in warned["data"]] == [seeded["suspicious"].id]
    assert warned["data"][0]["warning_count"] == 1
    assert all(row["warning_count"] == 0 for row in clean["data"])
    assert warned["pagination"]["total"] + clean["pagination"]["total"] == 3


def test_browser_data_quality_counts_and_paginates_beyond_200_warnings():
    db = _test_session()
    db.add_all([
        Swimmer(name=f"Athlete {index} LC Meter Freestyle", age=12, team="Example")
        for index in range(201)
    ])
    db.commit()

    payload = browser_data_quality(db, page=5, limit=50)

    assert payload["summary"] == {"suspicious_swimmer_name": 201}
    assert payload["pagination"]["total"] == 201
    assert payload["pagination"]["total_pages"] == 5
    assert len(payload["data"]) == 1


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


def test_browser_meets_api_returns_hybrid_grouped_aggregates_in_constant_queries_without_mutation():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    before = _domain_counts(db)
    statements: list[str] = []

    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def _count_queries(*args):
        statements.append(args[2])

    def _override_db():
        yield db

    main.app.dependency_overrides[main.get_db] = _override_db
    try:
        response = TestClient(main.app).get("/api/browser/meets")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["pagination"] == {"page": 1, "limit": 50, "total": 1, "total_pages": 1}
    row = response.json()["data"][0]
    assert row == {
        "id": seeded["meet"].id,
        "name": "56th SNAG Seniors",
        "date": "2026-03-17",
        "end_date": None,
        "location": None,
        "event_group_count": 4,
        "individual_result_count": 4,
        "relay_result_count": 1,
        "total_rows": 5,
        "missing_source_count": 1,
    }
    assert len(statements) <= 2
    assert _domain_counts(db) == before


def test_browser_meets_api_includes_relay_only_meets():
    db = _test_session()
    meet = Meet(name="Relay Only", startDate=datetime(2026, 7, 1), parserFormat="hytek")
    db.add(meet)
    db.flush()
    db.add(RelayResult(
        meetId=meet.id,
        event="Mixed 4x50 SC Meter Freestyle Relay",
        sourceEventNumber="9",
        teamName="Example Club",
        relayLetter="A",
        time="1:50.00",
        resultStatus="finished",
    ))
    db.commit()

    def _override_db():
        yield db

    main.app.dependency_overrides[main.get_db] = _override_db
    try:
        response = TestClient(main.app).get("/api/browser/meets", params={"q": "relay"})
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 200
    row = response.json()["data"][0]
    assert row["event_group_count"] == 1
    assert row["individual_result_count"] == 0
    assert row["relay_result_count"] == 1
    assert row["total_rows"] == 1
    assert row["missing_source_count"] == 1


def test_browser_meets_api_filters_orders_and_paginates_with_stable_id_ties():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    tied_date = datetime(2026, 8, 1)
    zulu = Meet(name="Zulu Invitational", startDate=tied_date, parserFormat="hytek")
    alpha = Meet(name="Alpha Invitational", startDate=tied_date, parserFormat="hytek")
    db.add_all([zulu, alpha])
    db.commit()

    def _override_db():
        yield db

    main.app.dependency_overrides[main.get_db] = _override_db
    try:
        client = TestClient(main.app)
        first = client.get(
            "/api/browser/meets",
            params={"page": 1, "limit": 1, "sort": "date", "order": "desc"},
        ).json()
        second = client.get(
            "/api/browser/meets",
            params={"page": 2, "limit": 1, "sort": "date", "order": "desc"},
        ).json()
        filtered = client.get(
            "/api/browser/meets",
            params={"q": "invitational", "sort": "name", "order": "asc"},
        ).json()
    finally:
        main.app.dependency_overrides.clear()

    assert first["pagination"] == {"page": 1, "limit": 1, "total": 3, "total_pages": 3}
    assert [first["data"][0]["id"], second["data"][0]["id"]] == [zulu.id, alpha.id]
    assert [row["name"] for row in filtered["data"]] == ["Alpha Invitational", "Zulu Invitational"]
    assert seeded["meet"].id not in {row["id"] for row in filtered["data"]}


def test_browser_meets_event_groups_deduplicate_same_union_tuple():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    relay = RelayResult(
        meetId=seeded["meet"].id,
        event="Men 15 & Over 50 LC Meter Freestyle",
        sourceEventNumber="17",
        teamName="Example Club",
        relayLetter="B",
        time="1:45.00",
        resultStatus="finished",
    )
    db.add(relay)
    db.commit()

    def _override_db():
        yield db

    main.app.dependency_overrides[main.get_db] = _override_db
    try:
        row = TestClient(main.app).get("/api/browser/meets").json()["data"][0]
    finally:
        main.app.dependency_overrides.clear()

    assert row["event_group_count"] == 4
    assert row["individual_result_count"] == 4
    assert row["relay_result_count"] == 2
    assert row["total_rows"] == 6


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


def test_browser_individual_rows_expose_exhibition_without_changing_fastest_eligibility():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    exhibition = db.query(Result).filter(Result.time == "24.51").one()
    exhibition.isExhibition = True
    db.commit()

    event_key = make_event_key(
        seeded["meet"].id,
        "Men 15 & Over 50 LC Meter Freestyle",
        "17",
    )
    event_payload = browser_event(
        db,
        meet_id=seeded["meet"].id,
        event_key=event_key,
    )
    swimmer_payload = browser_swimmer_detail(db, seeded["swimmer"].id)

    assert event_payload is not None
    event_row = next(row for row in event_payload["data"] if row["id"] == exhibition.id)
    assert event_row["is_exhibition"] is True
    assert swimmer_payload is not None
    freestyle = next(
        event
        for course in swimmer_payload["course_history"]
        for event in course["events"]
        if event["event"] == "50 Freestyle" and course["course"] == "LCM"
    )
    assert freestyle["fastest_recorded"]["id"] == exhibition.id
    assert freestyle["fastest_recorded"]["is_exhibition"] is True


def test_legacy_swimmer_endpoint_excludes_unknown_status_from_personal_bests():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    swimmer = seeded["swimmer"]
    meet = seeded["meet"]
    db.add(Result(
        swimmerId=swimmer.id,
        meetId=meet.id,
        event="Men 15 & Over 50 LC Meter Freestyle",
        time="1.00",
        placement=1,
        round="Final",
        resultStatus="unknown",
        swimDate=datetime(2026, 3, 18),
        sourceEventNumber="17",
    ))
    db.commit()

    def _override_db():
        yield db

    main.app.dependency_overrides[main.get_db] = _override_db
    try:
        response = TestClient(main.app).get(f"/api/swimmers/{swimmer.id}")
        assert response.status_code == 200
        personal_best = next(
            item for item in response.json()["personal_bests"]
            if item["event"] == "Men 15 & Over 50 LC Meter Freestyle"
        )
        assert personal_best["time"] == "24.51"
    finally:
        main.app.dependency_overrides.clear()


def test_individual_api_contracts_expose_exhibition_provenance():
    db = _test_session()
    seeded = _seed_browser_fixture(db)
    exhibition = db.query(Result).filter(Result.time == "24.51").one()
    exhibition.isExhibition = True
    db.commit()

    def _override_db():
        yield db

    main.app.dependency_overrides[main.get_db] = _override_db
    try:
        client = TestClient(main.app)
        listed = client.get("/api/results").json()["data"]
        detailed = client.get(f"/api/results/{exhibition.id}").json()
        meet = client.get(f"/api/meets/{seeded['meet'].id}").json()
        combined = client.get(
            "/api/results/all", params={"row_type": "individual"}
        ).json()["data"]
    finally:
        main.app.dependency_overrides.clear()

    assert next(row for row in listed if row["id"] == exhibition.id)["is_exhibition"] is True
    assert detailed["is_exhibition"] is True
    meet_row = next(
        row
        for event in meet["events"]
        for row in event["results"]
        if row["id"] == exhibition.id
    )
    assert meet_row["is_exhibition"] is True
    assert next(row for row in combined if row["id"] == exhibition.id)["is_exhibition"] is True


def test_combined_results_endpoint_filters_row_type_and_rejects_unknown_values():
    db = _test_session()
    _seed_browser_fixture(db)

    def _override_db():
        yield db

    main.app.dependency_overrides[main.get_db] = _override_db
    try:
        client = TestClient(main.app)
        individuals = client.get("/api/results/all", params={"row_type": "individual"})
        relays = client.get("/api/results/all", params={"row_type": "relay"})
        all_rows = client.get("/api/results/all", params={"row_type": "all"})
        invalid = client.get("/api/results/all", params={"row_type": "unsupported"})

        assert individuals.status_code == 200
        assert {row["type"] for row in individuals.json()["data"]} == {"individual"}
        assert individuals.json()["pagination"]["total"] == 4
        assert relays.status_code == 200
        assert {row["type"] for row in relays.json()["data"]} == {"relay"}
        assert relays.json()["pagination"]["total"] == 1
        assert all_rows.status_code == 200
        assert {row["type"] for row in all_rows.json()["data"]} == {"individual", "relay"}
        assert all_rows.json()["pagination"]["total"] == 5
        assert invalid.status_code == 422
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
