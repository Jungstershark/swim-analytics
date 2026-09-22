"""Entity resolution: canonicalize team and swimmer names.

HY-TEK source PDFs spell the same entity several different ways:

* ``Xavier School Swim Club`` vs ``Xavier SchoolSwimClub`` vs
  ``Xavier SchoolSwimClub (Phi``  (lost spaces, truncated country code)
* ``Stamford American Internationa-ZZ``  (truncated + HY-TEK ``-ZZ`` code)
* ``LI, Sitong`` vs ``Li, Sitong``  (inconsistent casing)

These ``slight differences`` are the root cause of duplicate Swimmer records and
ugly team labels. The fix is a deterministic two-step:

1. **Normalize** a raw string into a lossy key by stripping everything that is
   *not* identity — country tags like ``(Phi)``, HY-TEK abbreviation suffixes
   like ``-ZZ``/``-VD``, case, and all non-alphanumeric characters.
2. **Resolve** that key against a small canonical registry so every spelling
   points at one master value.

Teams are low-collision, so exact-key matches merge automatically. Swimmers are
high-collision, so we only merge on an exact name-key match *and* a matching
(already-canonicalized) team — which keeps the ``Cheong, Megan`` (age 14, X Lab)
vs ``Cheong, Megan`` (age 17, Aquatic Performance) name collision separate.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import AthleteProfile, RelayLeg, RelayResult, Result, Swimmer, TeamAlias, TeamCanon

# Trailing three-letter country/region tag, possibly truncated by the PDF text
# layer: " (Phi)", " (Phi", " (Can)", " (Tpe)", "(THA-US". Restricting
# the grammar is intentional: a meaningful branch suffix such as "(East)"
# must remain part of the team's identity.
_TRAILING_TAG = re.compile(r"\s*\(\s*[A-Z]{3}(?:-[A-Z]{2})?\s*\)?\s*$", re.IGNORECASE)

# Observed HY-TEK abbreviation suffixes used when a long team name is truncated
# to fit a fixed-width column. Do not strip arbitrary -XX/-ABC suffixes: they
# can be a legitimate part of a club name.
_HYTEK_CODE = re.compile(r"-(?:ZZ|VD)\s*$", re.IGNORECASE)

# Guest/foreign swimmers are prefixed with "*" in HY-TEK result rows.
_GUEST_MARKER = re.compile(r"^\*")


def _identity_component(raw: str) -> str:
    value = unicodedata.normalize("NFKC", raw.strip()).casefold()
    return "".join(character for character in value if character.isalnum())


def normalize(raw: str | None) -> str:
    """Collapse case, spacing, and punctuation to a Unicode-safe key."""
    return _identity_component(raw) if raw else ""


def normalize_team(raw: str | None) -> str:
    """Identity key for a team name with observed HY-TEK noise removed."""
    if not raw:
        return ""
    value = _HYTEK_CODE.sub("", raw.strip())
    value = _TRAILING_TAG.sub("", value)
    return normalize(value)


def normalize_name(raw: str | None) -> str:
    """Identity key for a swimmer name, preserving surname/given-name structure.

    HY-TEK normally emits ``Surname, Given``. Keeping that comma boundary in the
    key prevents a lossy collision such as ``Li, An`` == ``Lian`` while still
    reconciling case, spacing, apostrophe, and guest-marker variants.
    """
    if not raw:
        return ""
    value = _GUEST_MARKER.sub("", raw.strip())
    if "," in value:
        surname, given = value.split(",", 1)
        return f"{_identity_component(surname)}|{_identity_component(given)}"
    return f"|{_identity_component(value)}"


def prettify_team(raw: str | None) -> str:
    """Human-readable team name: strip tags/codes and collapse whitespace.

    Deliberately does NOT insert missing spaces (``SchoolSwimClub`` stays as-is);
    the resolver promotes the *most complete* spelling as canonical instead.
    """
    if not raw:
        return ""
    s = raw.strip()
    s = _HYTEK_CODE.sub("", s)
    s = _TRAILING_TAG.sub("", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _canonical_quality(name: str) -> tuple[int, int, int, int, int, str, str]:
    """Deterministically rank readable canonical candidates.

    Character-spaced OCR corruption (``X a v i e r ...``) must never beat a
    normal spelling merely because it contains more whitespace-separated tokens.
    """
    tokens = name.split()
    single_character_ratio = (
        sum(len(token) == 1 for token in tokens) / len(tokens) if tokens else 1.0
    )
    suspicious_character_spacing = len(tokens) >= 4 and single_character_ratio >= 0.6
    multi_character_words = sum(len(token) > 1 for token in tokens)
    mixed_case = int(any(char.islower() for char in name) and any(char.isupper() for char in name))
    return (
        int(not suspicious_character_spacing),
        multi_character_words,
        len(tokens),
        mixed_case,
        len(name),
        name.casefold(),
        name,
    )


def pick_better_canonical(current: str | None, candidate: str | None) -> str:
    """Return the deterministic, safer display master for two equivalent keys."""
    choices = [name for name in (current, candidate) if name]
    return max(choices, key=_canonical_quality) if choices else ""


def resolve_team(db: Session, raw_team: str | None) -> str:
    """Return the canonical team name for a raw source spelling.

    Looks up (or creates) the TeamCanon/TeamAlias registry entry. When a later
    spelling is more complete (more words), the canonical name is promoted so
    the master trends toward the cleanest form seen.
    """
    if not raw_team:
        return ""
    key = normalize_team(raw_team)
    if not key:
        return raw_team

    now = datetime.now(timezone.utc)
    canon = db.query(TeamCanon).filter(TeamCanon.key == key).first()
    if canon is None:
        canon = TeamCanon(canonicalName=prettify_team(raw_team), key=key)
        db.add(canon)
        db.flush()
    else:
        old_canonical = canon.canonicalName
        better = pick_better_canonical(old_canonical, prettify_team(raw_team))
        if better != old_canonical:
            canon.canonicalName = better
            # Display names are currently denormalized on result entities. Keep
            # them converged when a later, more complete spelling is promoted.
            db.query(Swimmer).filter(Swimmer.teamKey == key).update(
                {Swimmer.team: better}, synchronize_session="fetch"
            )
            db.query(AthleteProfile).filter(AthleteProfile.teamKey == key).update(
                {AthleteProfile.team: better}, synchronize_session="fetch"
            )
            db.query(RelayResult).filter(RelayResult.teamName == old_canonical).update(
                {RelayResult.teamName: better}, synchronize_session="fetch"
            )

    # Keep every exact source spelling as provenance. The normalized key maps
    # all aliases to the same canonical entity; rawName remains untouched.
    alias = db.query(TeamAlias).filter(TeamAlias.rawName == raw_team).first()
    if alias is None:
        db.add(
            TeamAlias(
                teamCanonId=canon.id,
                rawName=raw_team,
                key=key,
                firstSeenAt=now,
                lastSeenAt=now,
            )
        )
    else:
        alias.lastSeenAt = now
    db.flush()
    return canon.canonicalName


def resolve_athlete_profile(
    db: Session,
    *,
    name: str | None,
    name_key: str,
    team: str | None,
    team_key: str,
) -> AthleteProfile | None:
    """Find or create a browser profile for one exact name-and-club identity.

    This is intentionally narrower than a person-level identity service. It
    joins source rows across reported ages only when both normalized name and
    canonicalized club agree; club transfers stay separate unless later reviewed.
    """
    if not name_key.replace("|", "") or not team_key or not name or not team:
        return None
    profile = db.query(AthleteProfile).filter(
        AthleteProfile.nameKey == name_key,
        AthleteProfile.teamKey == team_key,
    ).first()
    if profile is None:
        candidate = AthleteProfile(name=name, nameKey=name_key, team=team, teamKey=team_key)
        try:
            # The unique constraint is the final concurrency guard. A nested
            # transaction lets a concurrent importer win without poisoning the
            # caller's wider ingestion transaction.
            with db.begin_nested():
                db.add(candidate)
                db.flush()
        except IntegrityError:
            profile = db.query(AthleteProfile).filter(
                AthleteProfile.nameKey == name_key,
                AthleteProfile.teamKey == team_key,
            ).first()
            if profile is None:
                raise
        else:
            return candidate
    better_name = pick_better_canonical(profile.name, name)
    if better_name != profile.name:
        profile.name = better_name
    if profile.team != team:
        profile.team = team
    return profile


def backfill_athlete_profiles(db: Session) -> dict[str, int]:
    """Attach every complete source row to its exact name-and-club profile.

    The function only creates profiles and writes ``Swimmer.athleteProfileId``.
    It never merges source rows, results, or relay legs.
    """
    created_profiles = 0
    linked_rows = 0
    skipped_rows = 0
    existing_keys = {
        (profile.nameKey, profile.teamKey)
        for profile in db.query(AthleteProfile.nameKey, AthleteProfile.teamKey).all()
    }
    for swimmer in db.query(Swimmer).order_by(Swimmer.id).all():
        name_key = swimmer.nameKey or normalize_name(swimmer.name)
        team_key = swimmer.teamKey or normalize_team(swimmer.team)
        profile = resolve_athlete_profile(
            db,
            name=swimmer.name,
            name_key=name_key,
            team=swimmer.team,
            team_key=team_key,
        )
        if profile is None:
            skipped_rows += 1
            continue
        if (name_key, team_key) not in existing_keys:
            created_profiles += 1
            existing_keys.add((name_key, team_key))
        if swimmer.athleteProfileId != profile.id:
            swimmer.athleteProfileId = profile.id
            linked_rows += 1
    db.flush()
    return {
        "created_profiles": created_profiles,
        "linked_rows": linked_rows,
        "skipped_rows": skipped_rows,
    }


def resolve_swimmer(db: Session, name: str | None, age: int | None, raw_team: str | None) -> tuple[Swimmer, bool]:
    """Find (or create) the Swimmer for a result/leg row.

    Identity is normalized surname/given-name structure plus normalized team and
    reported age. Using keys (not display strings) merges source spelling variants
    for the same competition row. A separate exact name-and-club AthleteProfile
    then joins these source rows across reported ages for browser display.

    The stored ``team`` is the canonical display name, refreshed on each hit so it
    converges to the best spelling as the registry is promoted.

    Returns ``(swimmer, created)``.
    """
    name_key = normalize_name(name)
    if not name_key.replace("|", ""):
        raise ValueError("Cannot resolve swimmer without a non-empty name")
    team_key = normalize_team(raw_team)
    team_display = resolve_team(db, raw_team)
    athlete_profile = resolve_athlete_profile(
        db,
        name=name,
        name_key=name_key,
        team=team_display,
        team_key=team_key,
    )

    # Fail closed when age or team evidence is missing: exact source re-imports
    # are filtered by content hash before resolution, but ambiguous new records
    # must not be destructively attached to an existing person.
    swimmer = None
    if age is not None and team_key:
        swimmer = db.query(Swimmer).filter(
            Swimmer.nameKey == name_key,
            Swimmer.teamKey == team_key,
            Swimmer.age == age,
        ).first()
    if swimmer is None:
        swimmer = Swimmer(
            name=name or "",
            nameKey=name_key,
            teamKey=team_key,
            age=age,
            team=team_display,
            athleteProfileId=athlete_profile.id if athlete_profile else None,
        )
        db.add(swimmer)
        db.flush()
        return swimmer, True
    if swimmer.team != team_display:
        swimmer.team = team_display
    if swimmer.athleteProfileId != (athlete_profile.id if athlete_profile else None):
        swimmer.athleteProfileId = athlete_profile.id if athlete_profile else None
    return swimmer, False


def merge_duplicate_swimmers(
    db: Session,
    identity_keys: Mapping[int, tuple[str, str, int | None]] | None = None,
) -> int:
    """Merge Swimmer rows sharing exact normalized name, team, and age.

    ``identity_keys`` lets the deployment backfill merge legacy rows *before*
    persisting colliding keys, so the database uniqueness index can remain active
    throughout the operation. Runtime callers can omit it and use stored keys.

    The lowest-id row wins. Results and RelayLegs are repointed before duplicate
    rows are deleted. Including age is a conservative ambiguity guard until a
    stable AthleteIdentity/birth-year model exists.

    Returns the number of duplicate rows removed.
    """
    groups: dict[tuple[str, str, int | None], list[Swimmer]] = defaultdict(list)
    for s in db.query(Swimmer).order_by(Swimmer.id).all():
        key = identity_keys[s.id] if identity_keys is not None else (s.nameKey or "", s.teamKey or "", s.age)
        if (
            key[0].replace("|", "")
            and key[1]
            and key[2] is not None
        ):  # fail closed when name, team, or age evidence is missing
            groups[key].append(s)

    merged = 0
    for _key, dupes in groups.items():
        if len(dupes) <= 1:
            continue
        keep = dupes[0]
        for dup in dupes[1:]:
            for r in db.query(Result).filter(Result.swimmerId == dup.id).all():
                r.swimmerId = keep.id
            for leg in db.query(RelayLeg).filter(RelayLeg.swimmerId == dup.id).all():
                leg.swimmerId = keep.id
            db.flush()  # persist repointing before removing the duplicate
            db.delete(dup)
            merged += 1
    db.flush()
    return merged
