"""Tests for entity resolution (team/swimmer canonicalization)."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.entity_resolution import (
    merge_duplicate_swimmers,
    normalize_name,
    normalize_team,
    pick_better_canonical,
    prettify_team,
    resolve_swimmer,
    resolve_team,
)
from app.models import Meet, RelayLeg, RelayResult, Result, Swimmer, TeamAlias, TeamCanon


def _test_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)()


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def test_normalize_team_collapses_slight_differences():
    variants = [
        "Xavier SchoolSwimClub (Phi",
        "Xavier SchoolSwimClub",
        "Xavier School Swim Club",
        "Xavier  School   Swim   Club",
        "XAVIER SCHOOL SWIM CLUB",
    ]
    keys = {normalize_team(v) for v in variants}
    assert keys == {"xavierschoolswimclub"}


def test_normalize_team_strips_country_and_hytek_codes():
    assert normalize_team("ElkValleyDolphinsSwimClub (Can") == "elkvalleydolphinsswimclub"
    assert normalize_team("Chinese Swimming Club S'Pore") == "chineseswimmingclubspore"
    assert normalize_team("Stamford American Internationa-ZZ") == "stamfordamericaninternationa"
    assert normalize_team("Cis Huskies Swim Team-ZZ") == "cishuskiesswimteam"


def test_team_normalization_does_not_strip_meaningful_suffixes():
    """Only observed HY-TEK noise is removable; branch names remain identity."""
    assert normalize_team("Dolphins (East)") == "dolphinseast"
    assert normalize_team("Dolphins (West)") == "dolphinswest"
    assert normalize_team("Team-ABC") == "teamabc"


def test_normalize_name_strips_case_whitespace_and_guest_marker():
    assert normalize_name("LI, Sitong") == "lisitong"
    assert normalize_name("li, sitong") == "lisitong"
    assert normalize_name("*Tandhiwira, Airien") == "tandhiwiraairien"
    assert normalize_name("  Wang,  Muyun ") == "wangmuyun"


def test_name_normalization_does_not_apply_team_suffix_rules():
    assert normalize_name("Smith, John (Jr)") == "smithjohnjr"
    assert normalize_name("Tan, Yi-XU") == "tanyixu"


def test_prettify_team_strips_tags_and_collapses_whitespace():
    assert prettify_team("Xavier SchoolSwimClub (Phi") == "Xavier SchoolSwimClub"
    assert prettify_team("Xavier  School   Swim   Club") == "Xavier School Swim Club"
    assert prettify_team("Stamford American Internationa-ZZ") == "Stamford American Internationa"


def test_pick_better_canonical_prefers_more_words():
    assert pick_better_canonical("Xavier SchoolSwimClub", "Xavier School Swim Club") == "Xavier School Swim Club"
    assert pick_better_canonical("Xavier School Swim Club", "Xavier SchoolSwimClub") == "Xavier School Swim Club"
    assert pick_better_canonical(None, "Xavier School Swim Club") == "Xavier School Swim Club"
    assert pick_better_canonical("", "Xavier School Swim Club") == "Xavier School Swim Club"


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def test_resolve_team_maps_variants_to_one_master():
    db = _test_session()
    resolve_team(db, "Xavier SchoolSwimClub (Phi")
    resolve_team(db, "Xavier School Swim Club")
    resolve_team(db, "Xavier SchoolSwimClub")
    resolve_team(db, "Xavier SchoolSwimClub (Phi")  # repeated observation

    # One canonical master, promoted to the most complete spelling.
    canon = db.query(TeamCanon).one()
    assert canon.canonicalName == "Xavier School Swim Club"
    assert canon.key == "xavierschoolswimclub"
    # Every source spelling remains available as evidence, even though all three
    # resolve through one normalized key.
    assert {a.rawName for a in db.query(TeamAlias).all()} == {
        "Xavier SchoolSwimClub (Phi",
        "Xavier School Swim Club",
        "Xavier SchoolSwimClub",
    }


def test_canonical_promotion_updates_existing_display_rows():
    from datetime import datetime

    db = _test_session()
    meet = Meet(name="Test Meet", startDate=datetime(2026, 1, 1))
    db.add(meet)
    db.flush()

    swimmer, _ = resolve_swimmer(db, "Gestuvo, Lester", 9, "Xavier SchoolSwimClub (Phi")
    relay = RelayResult(
        meetId=meet.id,
        event="Boys 4x50 Freestyle Relay",
        teamName="Xavier SchoolSwimClub",
        time="2:30.00",
    )
    db.add(relay)
    db.flush()

    assert swimmer.team == "Xavier SchoolSwimClub"
    assert relay.teamName == "Xavier SchoolSwimClub"

    assert resolve_team(db, "Xavier School Swim Club") == "Xavier School Swim Club"
    db.refresh(swimmer)
    db.refresh(relay)
    assert swimmer.team == "Xavier School Swim Club"
    assert relay.teamName == "Xavier School Swim Club"


def test_resolve_team_distinguishes_truly_different_teams():
    db = _test_session()
    assert resolve_team(db, "Aquatic Performance Swim Club") == "Aquatic Performance Swim Club"
    assert resolve_team(db, "X Lab") == "X Lab"
    assert db.query(TeamCanon).count() == 2


def test_resolve_swimmer_merges_same_name_across_team_spelling_variants():
    db = _test_session()
    s1, created1 = resolve_swimmer(db, "Gestuvo, Lester", 9, "Xavier SchoolSwimClub (Phi")
    assert created1 is True

    # Different team spelling but same normalized key -> same swimmer.
    s2, created2 = resolve_swimmer(db, "gestuvo, lester", 9, "Xavier School Swim Club")
    assert created2 is False
    assert s2.id == s1.id
    assert db.query(Swimmer).count() == 1


def test_resolve_swimmer_keeps_name_collision_separate_by_team():
    db = _test_session()
    s14, _ = resolve_swimmer(db, "Cheong, Megan", 14, "X Lab")
    s17, _ = resolve_swimmer(db, "Cheong, Megan", 17, "Aquatic Performance Swim Club")
    assert s14.id != s17.id
    assert db.query(Swimmer).count() == 2


def test_resolve_swimmer_keeps_unknown_team_name_collision_separate_by_age():
    db = _test_session()
    younger, _ = resolve_swimmer(db, "Lee, Alex", 11, None)
    older, _ = resolve_swimmer(db, "Lee, Alex", 16, None)
    assert younger.id != older.id
    assert db.query(Swimmer).count() == 2


def test_resolve_swimmer_updates_age_to_maximum():
    db = _test_session()
    s1, _ = resolve_swimmer(db, "Cheong, Megan", 14, "X Lab")
    s2, created = resolve_swimmer(db, "Cheong, Megan", 17, "X Lab")
    assert created is False
    assert s2.id == s1.id
    assert s2.age == 17


def test_merge_duplicate_swimmers_repoints_results_and_deletes_dups():
    from datetime import datetime

    db = _test_session()
    meet = Meet(name="Test Meet", startDate=datetime(2026, 1, 1))
    db.add(meet)
    db.flush()

    # Two swimmers with the same nameKey+teamKey (the duplicate-swimmer bug).
    keep = Swimmer(name="Gestuvo, Lester", nameKey="gestuvolester", teamKey="xavierschoolswimclub", age=9, team="Xavier School Swim Club")
    dup = Swimmer(name="Gestuvo, Lester", nameKey="gestuvolester", teamKey="xavierschoolswimclub", age=9, team="Xavier School Swim Club")
    db.add_all([keep, dup])
    db.flush()

    r1 = Result(swimmerId=keep.id, meetId=meet.id, event="50 Free", time="30.00")
    r2 = Result(swimmerId=keep.id, meetId=meet.id, event="100 Free", time="1:05.00")
    r3 = Result(swimmerId=dup.id, meetId=meet.id, event="200 IM", time="2:40.00")
    db.add_all([r1, r2, r3])
    db.flush()

    merged = merge_duplicate_swimmers(db)
    assert merged == 1
    assert db.query(Swimmer).count() == 1
    # All results survived and now point at the kept swimmer.
    assert db.query(Result).count() == 3
    assert {r.swimmerId for r in db.query(Result).all()} == {keep.id}
