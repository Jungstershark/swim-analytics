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
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import RelayLeg, Result, Swimmer, TeamAlias, TeamCanon

# Trailing country/region tag, possibly truncated by the PDF text layer:
#   " (Phi)", " (Phi", " (Can)", " (Tpe)"
_TRAILING_TAG = re.compile(r"\s*\([^)]*\)?\s*$")

# HY-TEK abbreviation suffix used when a long team name is truncated to fit a
# fixed-width column: "Stamford American Internationa-ZZ", "...Swim Team-VD".
_HYTEK_CODE = re.compile(r"-[A-Z]{2,3}\s*$")

# Anything that is not a lowercase letter or digit (spaces, commas, hyphens,
# apostrophes, periods) is removed from the key.
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Guest/foreign swimmers are prefixed with "*" in HY-TEK result rows.
_GUEST_MARKER = re.compile(r"^\*")


def normalize(raw: str | None) -> str:
    """Collapse a raw string to a lossy identity key.

    Order matters: strip the HY-TEK code and trailing country tag *before*
    removing non-alphanumerics so those fragments never pollute the key.
    """
    if not raw:
        return ""
    s = raw.strip()
    s = _HYTEK_CODE.sub("", s)
    s = _TRAILING_TAG.sub("", s)
    s = s.lower()
    s = _NON_ALNUM.sub("", s)
    return s


def normalize_team(raw: str | None) -> str:
    """Identity key for a team name."""
    return normalize(raw)


def normalize_name(raw: str | None) -> str:
    """Identity key for a swimmer name (guest marker stripped)."""
    if not raw:
        return ""
    return normalize(_GUEST_MARKER.sub("", raw.strip()))


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


def _canonical_quality(name: str) -> tuple[int, int]:
    """Rank a candidate canonical: prefer more words, then longer."""
    return (len(name.split()), len(name))


def pick_better_canonical(current: str | None, candidate: str | None) -> str:
    """Return whichever spelling is the 'better' master value."""
    if not current:
        return candidate or ""
    if not candidate:
        return current
    return candidate if _canonical_quality(candidate) > _canonical_quality(current) else current


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

    alias = db.query(TeamAlias).filter(TeamAlias.key == key).first()
    if alias is not None:
        canon = db.query(TeamCanon).filter(TeamCanon.id == alias.teamCanonId).first()
        if canon is not None:
            better = pick_better_canonical(canon.canonicalName, prettify_team(raw_team))
            if better != canon.canonicalName:
                canon.canonicalName = better
            return canon.canonicalName

    # New canonical entity.
    canon = TeamCanon(canonicalName=prettify_team(raw_team), key=key)
    db.add(canon)
    db.flush()
    db.add(TeamAlias(teamCanonId=canon.id, rawName=raw_team, key=key, firstSeenAt=datetime.now(timezone.utc)))
    db.flush()
    return canon.canonicalName


def resolve_swimmer(db: Session, name: str | None, age: int | None, raw_team: str | None) -> tuple[Swimmer, bool]:
    """Find (or create) the Swimmer for a result/leg row.

    Identity is the normalized name key plus the normalized team key. Using the
    *keys* (not the display strings) means the same person merges even when their
    team was spelled ``Xavier SchoolSwimClub (Phi`` in one PDF and
    ``Xavier School Swim Club`` in another, while same-name/different-team people
    (the ``Cheong, Megan`` age-14 vs age-17 case) stay separate. Age is treated as
    volatile (a swimmer ages up between meets), so it is updated, not matched.

    The stored ``team`` is the canonical display name, refreshed on each hit so it
    converges to the best spelling as the registry is promoted.

    Returns ``(swimmer, created)``.
    """
    name_key = normalize_name(name)
    team_key = normalize_team(raw_team)
    team_display = resolve_team(db, raw_team)

    swimmer = db.query(Swimmer).filter(
        Swimmer.nameKey == name_key,
        Swimmer.teamKey == team_key,
    ).first()
    if swimmer is None:
        swimmer = Swimmer(name=name or "", nameKey=name_key, teamKey=team_key, age=age, team=team_display)
        db.add(swimmer)
        db.flush()
        return swimmer, True
    if age and (swimmer.age is None or age > swimmer.age):
        swimmer.age = age
    if swimmer.team != team_display:
        swimmer.team = team_display
    return swimmer, False


def merge_duplicate_swimmers(db: Session) -> int:
    """Merge Swimmer rows that share the same (nameKey, teamKey).

    Duplicates arise when the same person was imported with a team spelling that
    normalized to a different key (pre-entity-resolution) or with inconsistent
    name casing. The lowest-id row wins; its age is raised to the max seen; the
    duplicates' Results and RelayLegs are repointed and the duplicates deleted.

    Returns the number of duplicate rows removed.
    """
    groups: dict[tuple[str, str], list[Swimmer]] = defaultdict(list)
    for s in db.query(Swimmer).order_by(Swimmer.id).all():
        key = (s.nameKey or "", s.teamKey or "")
        if key[0]:  # ignore rows without a name key
            groups[key].append(s)

    merged = 0
    for _key, dupes in groups.items():
        if len(dupes) <= 1:
            continue
        keep = dupes[0]
        for dup in dupes[1:]:
            if dup.age and (keep.age is None or dup.age > keep.age):
                keep.age = dup.age
            for r in db.query(Result).filter(Result.swimmerId == dup.id).all():
                r.swimmerId = keep.id
            for leg in db.query(RelayLeg).filter(RelayLeg.swimmerId == dup.id).all():
                leg.swimmerId = keep.id
            db.flush()  # persist repointing before removing the duplicate
            db.delete(dup)
            merged += 1
    db.flush()
    return merged
