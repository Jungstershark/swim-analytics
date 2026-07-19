#!/usr/bin/env python3
"""Archive SG Aquatics event PDFs from an event-discovery report.

This is the bridge between:

1. `discover_sgaquatics_events.py` — finds event detail pages and classifies
   whether result PDFs are available.
2. `scrape_sgaquatics_event.py` — downloads all PDFs for one event page into an
   immutable raw-library folder with a manifest.

This script intentionally performs raw archiving only. It does not import into
Postgres. Database import remains a separate, explicit derived-data step.

Domain assumptions:
- One SG Aquatics index can contain future/incomplete events. By default, only
  events with `status == results_available` are archived.
- Event pages may contain source documents beyond result PDFs; archive all PDFs
  because start lists, event information, medal tallies, and age-group rankings
  are future source material even when not imported as v0 results.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_DISCOVERY = Path("raw-data/sg-aquatics/event-discovery.json")
DEFAULT_OUTPUT_ROOT = Path("raw-data/sg-aquatics/events")


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "event"


def load_discovery(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def event_matches(event: dict, selectors: list[str]) -> bool:
    if not selectors:
        return True
    haystack = f"{event.get('title', '')} {event.get('page_title', '')} {event.get('url', '')}".lower()
    return any(selector.lower() in haystack for selector in selectors)


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive PDFs for SG Aquatics events selected from discovery JSON")
    parser.add_argument("--discovery", type=Path, default=DEFAULT_DISCOVERY)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--select",
        action="append",
        default=[],
        help="Substring selector for event title/page title/URL. Can be repeated. Defaults to all matching status events.",
    )
    parser.add_argument(
        "--status",
        action="append",
        default=["results_available"],
        help="Event status to archive. Defaults to results_available. Repeat for multiple statuses.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    discovery = load_discovery(args.discovery)
    events = discovery.get("events", [])
    selected = [
        event for event in events
        if event.get("status") in set(args.status) and event_matches(event, args.select)
    ]
    if args.limit is not None:
        selected = selected[: args.limit]

    print(f"Discovery: {args.discovery}")
    print(f"Selected events: {len(selected)}")

    if not selected:
        return 0

    for event in selected:
        title = event.get("page_title") or event.get("title") or "event"
        slug = slugify(title)
        output_dir = args.output_root / slug
        url = event["url"]
        print(f"\n{event.get('status'):30s} {event.get('pdf_count', 0):3d} {title}")
        print(f"  url: {url}")
        print(f"  out: {output_dir}")
        if args.dry_run:
            continue

        cmd = [sys.executable, "scripts/scrape_sgaquatics_event.py", url, str(output_dir)]
        subprocess.run(cmd, check=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
