#!/usr/bin/env python3
"""Diff two SG Aquatics raw archive manifests.

Use this before any scheduled import automation. It detects:

- newly added documents;
- removed documents;
- same URL/filename/category identity with changed SHA256;
- category changes for the same source URL/filename.

This protects ongoing events where result PDFs are added daily and cases where
SG Aquatics reuses the same PDF filename/URL for corrected content.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

IMPORTABLE_CATEGORIES = {"overall_results", "other_pdf"}


def _identity(record: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    return (record.get("url"), record.get("filename"), record.get("category"))


def _url_filename_identity(record: dict[str, Any]) -> tuple[str | None, str | None]:
    return (record.get("url"), record.get("filename"))


def _summarize(record: dict[str, Any]) -> dict[str, Any]:
    category = record.get("category")
    return {
        "url": record.get("url"),
        "filename": record.get("filename"),
        "category": category,
        "sha256": record.get("sha256"),
        "saved": record.get("saved"),
        "importable": category in IMPORTABLE_CATEGORIES,
    }


def diff_manifests(old_manifest: dict[str, Any], new_manifest: dict[str, Any]) -> dict[str, Any]:
    old_files = [record for record in old_manifest.get("files", []) if record.get("sha256")]
    new_files = [record for record in new_manifest.get("files", []) if record.get("sha256")]

    old_by_identity = {_identity(record): record for record in old_files}
    new_by_identity = {_identity(record): record for record in new_files}

    added = [
        _summarize(record)
        for identity, record in new_by_identity.items()
        if identity not in old_by_identity
    ]
    removed = [
        _summarize(record)
        for identity, record in old_by_identity.items()
        if identity not in new_by_identity
    ]

    changed_same_identity = []
    for identity, new_record in new_by_identity.items():
        old_record = old_by_identity.get(identity)
        if not old_record:
            continue
        old_sha = old_record.get("sha256")
        new_sha = new_record.get("sha256")
        if old_sha and new_sha and old_sha != new_sha:
            category = new_record.get("category")
            changed_same_identity.append({
                "url": new_record.get("url"),
                "filename": new_record.get("filename"),
                "category": category,
                "old_sha256": old_sha,
                "new_sha256": new_sha,
                "old_saved": old_record.get("saved"),
                "new_saved": new_record.get("saved"),
                "importable": category in IMPORTABLE_CATEGORIES,
            })

    old_by_url_filename = {_url_filename_identity(record): record for record in old_files}
    category_changes = []
    for record in new_files:
        old_record = old_by_url_filename.get(_url_filename_identity(record))
        if old_record and old_record.get("category") != record.get("category"):
            category_changes.append({
                "url": record.get("url"),
                "filename": record.get("filename"),
                "old_category": old_record.get("category"),
                "new_category": record.get("category"),
                "sha256": record.get("sha256"),
                "importable": record.get("category") in IMPORTABLE_CATEGORIES,
            })

    return {
        "old_source_page": old_manifest.get("source_page"),
        "new_source_page": new_manifest.get("source_page"),
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "changed_same_identity": len(changed_same_identity),
            "category_changes": len(category_changes),
            "importable_added": sum(1 for item in added if item["importable"]),
            "importable_changed_same_identity": sum(1 for item in changed_same_identity if item["importable"]),
        },
        "added_documents": added,
        "removed_documents": removed,
        "changed_same_identity": changed_same_identity,
        "category_changes": category_changes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diff two SG Aquatics event manifest JSON files")
    parser.add_argument("old_manifest", type=Path)
    parser.add_argument("new_manifest", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    old_manifest = json.loads(args.old_manifest.read_text(encoding="utf-8"))
    new_manifest = json.loads(args.new_manifest.read_text(encoding="utf-8"))
    diff = diff_manifests(old_manifest, new_manifest)

    rendered = json.dumps(diff, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
