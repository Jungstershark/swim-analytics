#!/usr/bin/env python3
"""Backfill browser athlete profiles without mutating source result records.

Run inside the deployed backend pod after the athlete-profile migration:

    python scripts/backfill_athlete_profiles.py --dry-run
    python scripts/backfill_athlete_profiles.py

Profiles only join source Swimmer rows with the same normalized name and
canonical club. Club transfers are deliberately left separate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_ROOT = _REPO_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.database import SessionLocal
from app.entity_resolution import backfill_athlete_profiles
from app.models import AthleteProfile, RelayLeg, Result, Swimmer


def snapshot(db) -> dict[str, int]:
    return {
        "athlete_profiles": db.query(AthleteProfile).count(),
        "linked_swimmers": db.query(Swimmer).filter(Swimmer.athleteProfileId.isnot(None)).count(),
        "swimmers": db.query(Swimmer).count(),
        "results": db.query(Result).count(),
        "relay_legs": db.query(RelayLeg).count(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        before = snapshot(db)
        changes = backfill_athlete_profiles(db)
        after = snapshot(db)
        report = {"dry_run": args.dry_run, "before": before, "after": after, **changes}
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
