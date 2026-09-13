#!/usr/bin/env python3
"""Import one archived competition manifest into the relational database."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal  # noqa: E402
from app.package_import import (  # noqa: E402
    import_parsed_competition_documents,
    parse_competition_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hash-verify, parse, validate, and import one competition package"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--title", required=True, help="Authoritative umbrella competition title")
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=Path("data/raw-documents"),
        help="Durable content-addressed raw-document root",
    )
    args = parser.parse_args()

    manifest_path = args.manifest.resolve(strict=True)
    package = parse_competition_manifest(
        manifest_path,
        package_root=manifest_path.parent,
        path_root=REPO_ROOT,
    )
    db = SessionLocal()
    try:
        summary = import_parsed_competition_documents(
            db,
            source_key=package.source_key,
            competition_title=args.title,
            documents=package.documents,
            archive_root=args.archive_root,
        )
    finally:
        db.close()

    print(json.dumps(asdict(summary), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
