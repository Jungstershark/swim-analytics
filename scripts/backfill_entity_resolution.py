#!/usr/bin/env python3
"""Backfill entity resolution for already-imported data.

One-off operator script (run inside the backend pod, like the SNAG import):

    1. Backfills ``Swimmer.nameKey`` / ``Swimmer.teamKey``.
    2. Builds the ``TeamCanon`` / ``TeamAlias`` registry from every distinct
       team spelling seen in ``Swimmer`` and ``RelayResult``.
    3. Re-canonicalizes stored team names to the master value.
    4. Merges duplicate Swimmer rows (same name key + team key) by repointing
       their Results/RelayLegs and deleting the duplicates.

Run with ``--dry-run`` first to preview counts without writing.
"""

from __future__ import annotations

import argparse

from app.database import SessionLocal
from app.entity_resolution import merge_duplicate_swimmers, normalize_name, normalize_team, resolve_team
from app.models import RelayLeg, RelayResult, Result, Swimmer, TeamAlias, TeamCanon


def snapshot(db) -> dict[str, int]:
    return {
        "swimmers": db.query(Swimmer).count(),
        "results": db.query(Result).count(),
        "relay_legs": db.query(RelayLeg).count(),
        "team_canons": db.query(TeamCanon).count(),
        "team_aliases": db.query(TeamAlias).count(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    before = snapshot(db)
    merged_swimmers = 0
    canonicalized_teams = 0

    try:
        swimmers = db.query(Swimmer).order_by(Swimmer.id).all()

        # 1. Backfill identity keys.
        for s in swimmers:
            s.nameKey = normalize_name(s.name)
            s.teamKey = normalize_team(s.team)
        db.flush()

        # 2. Build the team registry from every distinct raw spelling. This is
        # the only point at which legacy denormalized values are still source
        # spellings. After a successful run those columns contain canonical
        # display values, so a rerun must not record those masters as new raw
        # aliases. Missing keys are still added defensively for partial/new data.
        raw_teams: set[str] = set()
        for s in swimmers:
            if s.team:
                raw_teams.add(s.team)
        for rr in db.query(RelayResult).all():
            if rr.teamName:
                raw_teams.add(rr.teamName)

        existing_keys = {row.key for row in db.query(TeamCanon).all()}
        if not existing_keys:
            teams_to_register = raw_teams
        else:
            teams_to_register = {raw for raw in raw_teams if normalize_team(raw) not in existing_keys}
        for raw in sorted(teams_to_register):
            resolve_team(db, raw)
        db.flush()

        # Build the map only after every spelling has been considered. A later
        # alias may promote a cleaner master, and all earlier aliases must use
        # that final value rather than the value returned mid-loop.
        canon_by_key = {row.key: row.canonicalName for row in db.query(TeamCanon).all()}
        canonical_map = {raw: canon_by_key[normalize_team(raw)] for raw in raw_teams}

        # 3. Re-canonicalize stored team names.
        for s in swimmers:
            if s.team and s.team != canonical_map.get(s.team, s.team):
                s.team = canonical_map[s.team]
                canonicalized_teams += 1
        for rr in db.query(RelayResult).all():
            if rr.teamName and rr.teamName != canonical_map.get(rr.teamName, rr.teamName):
                rr.teamName = canonical_map[rr.teamName]
                canonicalized_teams += 1
        db.flush()

        # 4. Merge duplicate swimmers (same nameKey + teamKey).
        merged_swimmers = merge_duplicate_swimmers(db)

        after = snapshot(db)

        report = {
            "dry_run": args.dry_run,
            "before": before,
            "after": after,
            "canonicalized_team_names": canonicalized_teams,
            "merged_swimmers": merged_swimmers,
        }
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
        print(report)
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
