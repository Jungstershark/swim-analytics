#!/usr/bin/env python3
"""Preview archived SG Aquatics result PDFs without importing into the DB.

Given a raw-library `manifest.json`, parse only `overall_results` files through
the backend parser and emit a summary. This is the operator-side equivalent of
website upload preview: read-only, confidence/count oriented, and safe to run on
new competition pages before choosing whether to import.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from repo root without installing backend as a package.
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.parsers.base import detect_and_parse, detect_parser  # noqa: E402


def confidence_percent(confidence) -> int:
    if confidence is None:
        return 0
    score = getattr(confidence, "score", None)
    if score is not None:
        return int(round(score * 100))
    return int(round(float(confidence) * 100))


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview archived SG Aquatics overall result PDFs")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    files = [record for record in manifest.get("files", []) if record.get("category") == "overall_results" and record.get("saved")]

    preview_records = []
    totals = {
        "files": 0,
        "events": 0,
        "individual_results": 0,
        "relay_results": 0,
        "failed": 0,
    }

    print(f"Manifest: {args.manifest}")
    print(f"Source page: {manifest.get('source_page')}")
    print(f"Overall result files: {len(files)}")

    for record in files:
        path = Path(record["saved"])
        try:
            detection = detect_parser(path)
            parsed, confidence, parser_format = detect_and_parse(path)
            event_count = len(parsed.events)
            individual_count = sum(len(event.results) for event in parsed.events)
            relay_count = sum(len(event.relay_results) for event in parsed.events)
            score = confidence_percent(confidence)
            status = "ok"
            error = None
            parser_version = detection.parser_version
            detection_confidence = detection.confidence
            detection_reason = detection.reason
            totals["files"] += 1
            totals["events"] += event_count
            totals["individual_results"] += individual_count
            totals["relay_results"] += relay_count
            print(f"OK   {score:3d}% {event_count:4d} events {individual_count:6d} indiv {relay_count:4d} relay {path.name}")
        except Exception as exc:
            event_count = individual_count = relay_count = 0
            score = 0
            parser_format = None
            parser_version = None
            detection_confidence = 0
            detection_reason = None
            status = "failed"
            error = f"{type(exc).__name__}: {exc}"
            totals["failed"] += 1
            print(f"FAIL {path.name}: {error}")

        preview_records.append({
            "filename": record.get("filename"),
            "path": str(path),
            "sha256": record.get("sha256"),
            "status": status,
            "parser_format": parser_format,
            "parser_version": parser_version,
            "detection_confidence": detection_confidence,
            "detection_reason": detection_reason,
            "confidence_percent": score,
            "events": event_count,
            "individual_results": individual_count,
            "relay_results": relay_count,
            "error": error,
        })

    summary = {
        "manifest": str(args.manifest),
        "source_page": manifest.get("source_page"),
        "totals": totals,
        "files": preview_records,
    }

    print("\nTotals:", totals)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print("Preview report:", args.output)
    return 1 if totals["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
