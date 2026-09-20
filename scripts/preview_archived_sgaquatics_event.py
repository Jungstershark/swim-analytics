#!/usr/bin/env python3
"""Preview a policy-curated archived SG Aquatics package without DB writes."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys
from pathlib import Path

# Allow running from repo root without installing backend as a package.
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
CURATION_DIR = REPO_ROOT / "config" / "package-curation"
sys.path.insert(0, str(BACKEND_ROOT))

from app.package_curation import load_manifest_curation_policy  # noqa: E402
from app.competition_packages import (  # noqa: E402
    CompetitionIdentity,
    parse_document_identity_payload,
)
from app.package_import import _preflight_documents, parse_competition_manifest  # noqa: E402


def confidence_percent(confidence) -> int:
    if confidence is None:
        return 0
    score = getattr(confidence, "score", None)
    if score is not None:
        return int(round(score * 100))
    return int(round(float(confidence) * 100))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hash-verify and preview a curated archived SG Aquatics package"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--curation-policy", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--title",
        default=None,
        help="Authoritative umbrella competition title, as the import will use it",
    )
    parser.add_argument(
        "--identity",
        type=Path,
        default=None,
        help=(
            "JSON identity for documents whose pages print none. Supplying "
            "--title or --identity runs the same import preflight, so the preview "
            "fails for exactly the packages the import would fail."
        ),
    )
    args = parser.parse_args()

    manifest_path = args.manifest.resolve(strict=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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

    preview_records = []
    totals = {
        "files": 0,
        "events": 0,
        "individual_results": 0,
        "relay_results": 0,
        "failed": 0,
    }

    print(f"Manifest: {manifest_path}")
    print(f"Source page: {manifest.get('source_page')}")
    print(f"Curation policy: {policy.package_id}")
    print(f"Canonical result files: {len(package.documents)}")

    if args.title or args.identity is not None:
        # A dry run should fail for exactly the packages the import would fail.
        identity = (
            CompetitionIdentity(title=args.title.strip(), source="operator")
            if args.title and args.title.strip()
            else None
        )
        document_identity = (
            parse_document_identity_payload(
                json.loads(args.identity.read_text(encoding="utf-8"))
            )
            if args.identity is not None
            else None
        )
        _preflight_documents(
            package.documents, identity=identity, document_identity=document_identity
        )
        print("Preflight: OK")

    for document in package.documents:
        parsed = document.parsed
        event_count = len(parsed.events)
        individual_count = parsed.total_results
        relay_count = parsed.total_relay_results
        score = confidence_percent(document.confidence_score)
        totals["files"] += 1
        totals["events"] += event_count
        totals["individual_results"] += individual_count
        totals["relay_results"] += relay_count
        print(
            f"OK   {score:3d}% {event_count:4d} events "
            f"{individual_count:6d} indiv {relay_count:4d} relay {document.filename}"
        )
        preview_records.append({
            "filename": document.filename,
            "sha256": document.sha256,
            "status": "ok",
            "parser_format": document.parser_name,
            "parser_version": document.parser_version,
            "confidence_percent": score,
            "events": event_count,
            "individual_results": individual_count,
            "relay_results": relay_count,
            "error": None,
        })

    summary = {
        "manifest": str(manifest_path),
        "source_page": manifest.get("source_page"),
        "curation": asdict(package.curation_report) if package.curation_report else None,
        "totals": totals,
        "files": preview_records,
    }

    print("\nTotals:", totals)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print("Preview report:", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
