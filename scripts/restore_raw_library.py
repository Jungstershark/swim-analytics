#!/usr/bin/env python3
"""Restore the raw PDF library from the tracked manifests.

The PDFs themselves are gitignored (`raw-data/**/*.pdf`), but every manifest is
tracked and records the source URL, byte size, and sha256 of each document. That
makes the recipe library reproducible on any machine without copying files
between hosts or trusting a source page that may have changed since archiving.

This script is a *replay*, not a re-scrape:

- It never re-reads the source event page, so the raw library it produces is
  byte-identical to the one the manifests were written against.
- It refuses to keep a download whose size or sha256 disagrees with the manifest.
- It never overwrites a file that already matches, so re-running is cheap.

Usage:
    python scripts/restore_raw_library.py --dry-run
    python scripts/restore_raw_library.py --limit 5
    python scripts/restore_raw_library.py                       # whole corpus
    python scripts/restore_raw_library.py --verify-only         # check, no network
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_GLOB = "raw-data/**/manifest.json"
USER_AGENT = "swim-analytics-raw-restore/1.0 (+local development)"


def tracked_manifests(root: Path) -> list[Path]:
    """Manifests that belong to the repo, in a stable order."""
    return sorted(p for p in root.glob(MANIFEST_GLOB) if ".git" not in p.parts)


def resolve_target(root: Path, manifest_path: Path, entry: dict) -> Path | None:
    """Map a manifest entry to its repo-relative destination.

    `saved` is repo-relative in most manifests and an absolute path from the
    archiving host in others, so strip anything up to the repo folder name
    before falling back to "next to the manifest".
    """
    saved = (entry.get("saved") or "").replace("\\", "/").strip()
    filename = (entry.get("filename") or "").strip()
    if not filename:
        return None

    # Anchor on `raw-data/` rather than the host's absolute prefix, so a clone
    # under any directory name resolves the same way.
    if "raw-data/" in saved:
        rel = saved[saved.index("raw-data/"):]
        return root / rel
    return manifest_path.parent / filename


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path, timeout: int = 90) -> None:
    """Fetch to a temp file in the destination directory, then rename."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    handle = urllib.request.urlopen(request, timeout=timeout)
    with handle:
        if getattr(handle, "status", 200) != 200:
            raise urllib.error.URLError(f"HTTP {handle.status}")
        fd, tmp_name = tempfile.mkstemp(
            dir=str(destination.parent), prefix=".restore-", suffix=".part"
        )
        try:
            with os.fdopen(fd, "wb") as out:
                shutil.copyfileobj(handle, out, length=1024 * 1024)
            os.replace(tmp_name, destination)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT,
                        help="repository root (default: inferred from this script)")
    parser.add_argument("--manifest", type=Path, action="append", default=None,
                        help="specific manifest(s); default is every tracked manifest")
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after N downloads (useful for a quick local corpus)")
    parser.add_argument("--category", default=None,
                        help="only download files of this manifest category, e.g. results")
    parser.add_argument("--dry-run", action="store_true", help="print the plan only")
    parser.add_argument("--verify-only", action="store_true",
                        help="check existing files against the manifest; never download")
    parser.add_argument("--force", action="store_true",
                        help="re-download even when a matching file already exists")
    args = parser.parse_args()

    root = args.root.resolve()
    manifests = args.manifest or tracked_manifests(root)
    if not manifests:
        print(f"no manifests found under {root}/{MANIFEST_GLOB}", file=sys.stderr)
        return 2

    present = missing = downloaded = drifted = failed = planned = 0
    first_error: str | None = None
    reached_limit = False

    for manifest_path in manifests:
        if reached_limit:
            break
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            failed += 1
            first_error = first_error or f"{manifest_path}: {exc}"
            print(f"FAIL  {manifest_path}: cannot read manifest ({exc})")
            continue

        for entry in manifest.get("files", []):
            if entry.get("status") != 200:
                continue
            if args.category and entry.get("category") != args.category:
                continue

            target = resolve_target(root, manifest_path, entry)
            if target is None:
                failed += 1
                first_error = first_error or f"{manifest_path}: entry without filename"
                continue

            expected_sha = (entry.get("sha256") or "").strip()
            relative = target.relative_to(root) if target.is_relative_to(root) else target

            if target.exists() and not args.force:
                if expected_sha and file_digest(target) == expected_sha:
                    present += 1
                    continue
                drifted += 1
                print(f"DRIFT {relative} (on disk does not match manifest sha256)")

            if args.verify_only:
                missing += 1
                print(f"MISS  {relative}")
                continue

            if args.dry_run:
                planned += 1
                print(f"PLAN  {relative}  <- {entry.get('url')}")
                continue

            if args.limit is not None and downloaded >= args.limit:
                reached_limit = True
                break

            url = entry.get("url")
            try:
                download(url, target)
            except Exception as exc:  # noqa: BLE001 - report and continue
                failed += 1
                first_error = first_error or f"{relative}: {exc}"
                print(f"FAIL  {relative}: {exc}")
                continue

            actual_sha = file_digest(target)
            expected_bytes = entry.get("bytes")
            actual_bytes = target.stat().st_size
            if (expected_sha and actual_sha != expected_sha) or (
                expected_bytes is not None and actual_bytes != expected_bytes
            ):
                failed += 1
                target.unlink(missing_ok=True)
                note = f"sha256 {actual_sha[:12]} != {expected_sha[:12]}" if expected_sha else "size mismatch"
                first_error = first_error or f"{relative}: {note}"
                print(f"FAIL  {relative}: {note} (discarded)")
                continue

            downloaded += 1
            print(f"OK    {relative}  ({actual_bytes:,} bytes)")

    print(
        f"\nverified={present} downloaded={downloaded} missing={missing} "
        f"drifted={drifted} planned={planned} failed={failed}"
    )
    if first_error:
        print(f"first error: {first_error}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
