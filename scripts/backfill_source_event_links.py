#!/usr/bin/env python3
"""Safely link historical SG Aquatics catalogue pages to imported editions.

Run after the source-manifest migration and a fresh manual catalogue check:

    python scripts/backfill_source_event_links.py --dry-run
    python scripts/backfill_source_event_links.py

Only exact canonical source URLs with matching imported-document provenance are
linked. Historic imports keep their freshness baseline empty: only a later,
source-bound re-import can establish that the imported evidence matches the
observed page manifest.
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
from app.models import CompetitionEdition, SourceEvent
from app.source_monitoring import backfill_source_event_links


def snapshot(db) -> dict[str, int]:
    return {
        "source_events": db.query(SourceEvent).count(),
        "source_events_with_manifest": db.query(SourceEvent).filter(
            SourceEvent.manifestSha256.isnot(None)
        ).count(),
        "competition_editions": db.query(CompetitionEdition).count(),
        "linked_editions": db.query(CompetitionEdition).filter(
            CompetitionEdition.sourceEventId.isnot(None)
        ).count(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        before = snapshot(db)
        changes = backfill_source_event_links(db)
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
