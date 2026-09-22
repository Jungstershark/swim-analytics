"""Tests for entity resolution (team/swimmer canonicalization)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.entity_resolution import (
    backfill_athlete_profiles,
    merge_duplicate_swimmers,
    normalize_name,
    normalize_team,
    pick_better_canonical,
    prettify_team,
    resolve_swimmer,
    resolve_team,
)
from app.models import AthleteProfile, Meet, RelayLeg, RelayResult, Result, Swimmer, TeamAlias, TeamCanon


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
    assert normalize_name("LI, Sitong") == "li|sitong"
    assert normalize_name("li, sitong") == "li|sitong"
    assert normalize_name("*Tandhiwira, Airien") == "tandhiwira|airien"
    assert normalize_name("  Wang,  Muyun ") == "wang|muyun"


def test_name_normalization_preserves_structural_and_unicode_distinctions():
    assert normalize_name("Li, An") != normalize_name("Lian")
    assert normalize_name("王伟") == "|王伟"
    assert normalize_name("李娜") == "|李娜"
    assert normalize_name("王伟") != normalize_name("李娜")


def test_name_normalization_does_not_apply_team_suffix_rules():
    assert normalize_name("Smith, John (Jr)") == "smith|johnjr"
    assert normalize_name("Tan, Yi-XU") == "tan|yixu"


def test_prettify_team_strips_tags_and_collapses_whitespace():
    assert prettify_team("Xavier SchoolSwimClub (Phi") == "Xavier SchoolSwimClub"
    assert prettify_team("Xavier  School   Swim   Club") == "Xavier School Swim Club"
    assert prettify_team("Stamford American Internationa-ZZ") == "Stamford American Internationa"


def test_pick_better_canonical_prefers_readable_name_deterministically():
    clean = "Xavier School Swim Club"
    joined = "Xavier SchoolSwimClub"
    corrupt = "X a v i e r S c h o o l S w i m C l u b"
    assert pick_better_canonical(joined, clean) == clean
    assert pick_better_canonical(clean, joined) == clean
    assert pick_better_canonical(clean, corrupt) == clean
    assert pick_better_canonical(corrupt, clean) == clean
    assert pick_better_canonical(None, clean) == clean
    assert pick_better_canonical("", clean) == clean


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
    profile_id = swimmer.athleteProfileId

    assert resolve_team(db, "Xavier School Swim Club") == "Xavier School Swim Club"
    db.refresh(swimmer)
    db.refresh(relay)
    assert swimmer.team == "Xavier School Swim Club"
    assert db.get(AthleteProfile, profile_id).team == "Xavier School Swim Club"
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


def test_resolve_swimmer_keeps_same_team_name_collision_separate_by_age():
    db = _test_session()
    younger, _ = resolve_swimmer(db, "Cheong, Megan", 14, "X Lab")
    older, created = resolve_swimmer(db, "Cheong, Megan", 17, "X Lab")
    assert created is True
    assert older.id != younger.id
    assert db.query(Swimmer).count() == 2


def test_athlete_profile_combines_same_name_and_club_across_ages_only():
    db = _test_session()
    age_24, _ = resolve_swimmer(db, "Ong, Jung Yi", 24, "Chinese Swimming Club S'Pore")
    age_25, _ = resolve_swimmer(db, "ong, jung yi", 25, "Chinese Swimming Club S'Pore")
    transferred, _ = resolve_swimmer(db, "Ong, Jung Yi", 26, "Another Club")

    assert age_24.id != age_25.id
    assert age_24.athleteProfileId == age_25.athleteProfileId
    assert transferred.athleteProfileId != age_24.athleteProfileId
    assert db.query(AthleteProfile).count() == 2


def test_athlete_profile_rejects_malformed_identity_keys():
    db = _test_session()
    db.add(AthleteProfile(name="Unknown", nameKey="|", team="Club", teamKey="club"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    db.add(AthleteProfile(name="Known, Swimmer", nameKey="known|swimmer", team="Club", teamKey=""))
    with pytest.raises(IntegrityError):
        db.flush()


def test_athlete_profile_backfill_links_source_rows_without_merging_them():
    db = _test_session()
    rows = [
        Swimmer(name="Ong, Jung Yi", nameKey="ong|jungyi", teamKey="chineseswimmingclubspore", age=24, team="Chinese Swimming Club S'pore"),
        Swimmer(name="Ong, Jung Yi", nameKey="ong|jungyi", teamKey="chineseswimmingclubspore", age=25, team="Chinese Swimming Club S'pore"),
        Swimmer(name="Ong, Jung Yi", nameKey="ong|jungyi", teamKey="anotherclub", age=26, team="Another Club"),
    ]
    db.add_all(rows)
    db.flush()

    report = backfill_athlete_profiles(db)

    assert report == {"created_profiles": 2, "linked_rows": 3, "skipped_rows": 0}
    assert db.query(Swimmer).count() == 3
    assert rows[0].athleteProfileId == rows[1].athleteProfileId
    assert rows[2].athleteProfileId != rows[0].athleteProfileId


def test_resolve_swimmer_keeps_missing_identity_evidence_separate():
    db = _test_session()
    missing_age_1, _ = resolve_swimmer(db, "Lee, Alex", None, "Known Club")
    missing_age_2, _ = resolve_swimmer(db, "Lee, Alex", None, "Known Club")
    missing_team_1, _ = resolve_swimmer(db, "Lee, Alex", 12, None)
    missing_team_2, _ = resolve_swimmer(db, "Lee, Alex", 12, None)
    assert missing_age_1.id != missing_age_2.id
    assert missing_team_1.id != missing_team_2.id
    assert db.query(Swimmer).count() == 4


def test_swimmer_identity_has_database_uniqueness_guard():
    db = _test_session()
    db.add_all([
        Swimmer(name="A", nameKey="family|given", teamKey="club", age=12, team="Club"),
        Swimmer(name="A", nameKey="family|given", teamKey="club", age=12, team="Club"),
    ])
    with pytest.raises(IntegrityError):
        db.flush()


def test_merge_duplicate_swimmers_skips_ambiguous_missing_evidence():
    db = _test_session()
    rows = [
        Swimmer(name="Lee, Alex", age=None, team="Known Club"),
        Swimmer(name="Lee, Alex", age=None, team="Known Club"),
        Swimmer(name="Lee, Alex", age=12, team=None),
        Swimmer(name="Lee, Alex", age=12, team=None),
    ]
    db.add_all(rows)
    db.flush()
    keys = {
        rows[0].id: ("lee|alex", "knownclub", None),
        rows[1].id: ("lee|alex", "knownclub", None),
        rows[2].id: ("lee|alex", "", 12),
        rows[3].id: ("lee|alex", "", 12),
    }
    assert merge_duplicate_swimmers(db, keys) == 0
    assert db.query(Swimmer).count() == 4


def test_merge_duplicate_swimmers_repoints_results_and_deletes_dups():
    from datetime import datetime

    db = _test_session()
    meet = Meet(name="Test Meet", startDate=datetime(2026, 1, 1))
    db.add(meet)
    db.flush()

    # Two swimmers with the same normalized name/team/age (the duplicate bug),
    # plus two ambiguity controls that must remain separate.
    keep = Swimmer(name="Gestuvo, Lester", nameKey=None, teamKey=None, age=9, team="Xavier School Swim Club")
    dup = Swimmer(name="Gestuvo, Lester", nameKey=None, teamKey=None, age=9, team="Xavier SchoolSwimClub (Phi")
    older = Swimmer(name="Gestuvo, Lester", nameKey=None, teamKey=None, age=16, team="Xavier School Swim Club")
    other_team = Swimmer(name="Gestuvo, Lester", nameKey=None, teamKey=None, age=9, team="Other Club")
    db.add_all([keep, dup, older, other_team])
    db.flush()

    r1 = Result(swimmerId=keep.id, meetId=meet.id, event="50 Free", time="30.00", rawTeamName="Xavier School Swim Club")
    r2 = Result(swimmerId=keep.id, meetId=meet.id, event="100 Free", time="1:05.00", rawTeamName="Xavier School Swim Club")
    r3 = Result(swimmerId=dup.id, meetId=meet.id, event="200 IM", time="2:40.00", rawTeamName="Xavier SchoolSwimClub (Phi")
    relay = RelayResult(meetId=meet.id, event="4x50 Free", teamName="Xavier School Swim Club", time="2:00.00")
    db.add_all([r1, r2, r3, relay])
    db.flush()
    leg = RelayLeg(relayResultId=relay.id, legNumber=1, swimmerId=dup.id, swimmerName=dup.name)
    db.add(leg)
    db.flush()

    identity_keys = {
        keep.id: ("gestuvo|lester", "xavierschoolswimclub", 9),
        dup.id: ("gestuvo|lester", "xavierschoolswimclub", 9),
        older.id: ("gestuvo|lester", "xavierschoolswimclub", 16),
        other_team.id: ("gestuvo|lester", "otherclub", 9),
    }
    merged = merge_duplicate_swimmers(db, identity_keys)
    assert merged == 1
    assert db.query(Swimmer).count() == 3
    assert db.get(Swimmer, older.id) is not None
    assert db.get(Swimmer, other_team.id) is not None
    # All results and relay legs survived and now point at the kept swimmer.
    assert db.query(Result).count() == 3
    assert {r.swimmerId for r in db.query(Result).all()} == {keep.id}
    assert {r.rawTeamName for r in db.query(Result).all()} == {
        "Xavier School Swim Club",
        "Xavier SchoolSwimClub (Phi",
    }
    assert db.query(RelayLeg).one().swimmerId == keep.id
