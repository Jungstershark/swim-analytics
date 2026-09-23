#!/usr/bin/env python3
"""Import one archived competition manifest into the relational database.

Competition name and date range are caller-supplied: the parser only ever
prefills them. Documents whose pages print their own identity need nothing;
`--identity` names the ones that do not (for example a results sheet with no
competition header line).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
CURATION_DIR = REPO_ROOT / "config" / "package-curation"
sys.path.insert(0, str(BACKEND_ROOT))

from app.competition_packages import parse_document_identity_payload  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.package_curation import load_manifest_curation_policy  # noqa: E402
from app.package_import import (  # noqa: E402
    import_parsed_competition_documents,
    parse_competition_manifest,
)


def _load_document_identity(path: Path | None):
    if path is None:
        return None
    identity_path = path.resolve(strict=True)
    return parse_document_identity_payload(
        json.loads(identity_path.read_text(encoding="utf-8"))
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hash-verify, parse, validate, and import one competition package"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--title", required=True, help="Authoritative umbrella competition title")
    parser.add_argument("--curation-policy", type=Path, default=None)
    parser.add_argument(
        "--source-event-id",
        type=int,
        default=None,
        help="Reviewed source-event ID; requires --expected-source-manifest-sha256",
    )
    parser.add_argument(
        "--expected-source-manifest-sha256",
        default=None,
        help="Reviewed 64-character source manifest SHA-256; requires --source-event-id",
    )
    parser.add_argument(
        "--identity",
        type=Path,
        default=None,
        help=(
            "JSON identity for documents whose pages print none, for example "
            '{"documents": [{"filename": "day-2-heats.pdf", '
            '"segment_name": "20th SNSC 2025", "start_date": "2025-05-31", '
            '"end_date": "2025-06-03"}]}'
        ),
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=Path("data/raw-documents"),
        help="Durable content-addressed raw-document root",
    )
    args = parser.parse_args()
    if (args.source_event_id is None) != (args.expected_source_manifest_sha256 is None):
        parser.error("--source-event-id and --expected-source-manifest-sha256 must be supplied together")

    document_identity = _load_document_identity(args.identity)
    manifest_path = args.manifest.resolve(strict=True)
    policy = load_manifest_curation_policy(
        manifest_path,
        explicit_path=args.curation_policy,
        config_dir=CURATION_DIR,
    )
    package = parse_competition_manifest(
        manifest_path,
        package_root=manifest_path.parent,
        path_root=REPO_ROOT,
        curation_policy=policy,
    )
    db = SessionLocal()
    try:
        summary = import_parsed_competition_documents(
            db,
            source_key=package.source_key,
            competition_title=args.title,
            documents=package.documents,
            archive_root=args.archive_root,
            document_identity=document_identity,
            source_event_id=args.source_event_id,
            expected_source_manifest_sha256=args.expected_source_manifest_sha256,
        )
    finally:
        db.close()

    print(json.dumps(asdict(summary), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
