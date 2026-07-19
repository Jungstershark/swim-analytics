#!/usr/bin/env python3
"""Scrape an SG Aquatics event page into an immutable raw PDF library.

This script downloads every PDF linked from an event page and writes a manifest
with source URL, category, sha256, byte size, and local path. It is deliberately
raw-library first: database import should be a separate derived-data step.
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmlmod
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin

from urllib.request import Request, urlopen


@dataclass
class HttpResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def raise_for_status(self) -> None:
        if not 200 <= self.status_code < 300:
            raise RuntimeError(f"HTTP {self.status_code}")


def fetch(url: str, timeout: int = 30) -> HttpResponse:
    request = Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; swim-analytics-raw-archive/0.1)"},
    )
    with urlopen(request, timeout=timeout) as response:
        return HttpResponse(
            status_code=response.status,
            headers={k.lower(): v for k, v in response.headers.items()},
            content=response.read(),
        )


@dataclass
class PdfRecord:
    url: str
    filename: str
    category: str
    status: int
    content_type: str
    bytes: int
    sha256: str | None
    saved: str | None
    filename_saved: str | None
    filename_reused_with_new_hash: bool = False


def classify(filename: str) -> str:
    name = filename.lower()
    # Specific document-role signals must win over broad meet-title words like
    # "Championships" / "Cships" / "National Age Group Swimming". Otherwise
    # result PDFs from championship pages can be incorrectly archived as event
    # information and skipped by downstream import policy.
    if "medal" in name:
        return "medal_tally"
    if "start-list" in name or "startlist" in name:
        return "start_list"
    if "finals-by-age-group" in name or "age-group-result" in name or "age-group-results" in name:
        return "age_group_results"
    if "result" in name:
        return "overall_results"
    if "cships" in name or "championship" in name or "singapore-national-age-group-swimming" in name:
        return "event_information"
    if "event" in name or "info" in name or "information" in name:
        return "event_information"
    return "other_pdf"


def extract_pdf_links(page_url: str, html: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r"href=[\"']([^\"']+\.pdf)[\"']", html, flags=re.I):
        candidates.append(match.group(1))
    for match in re.finditer(r"https?://[^\s\"'<>]+\.pdf", html, flags=re.I):
        candidates.append(match.group(0))

    seen: set[str] = set()
    ordered: list[str] = []
    for url in candidates:
        clean = htmlmod.unescape(unquote(url.strip()))
        clean = urljoin(page_url, clean)
        if clean not in seen:
            seen.add(clean)
            ordered.append(clean)
    return ordered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("event_url")
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    page = fetch(args.event_url, timeout=30)
    page.raise_for_status()
    links = extract_pdf_links(args.event_url, page.text)

    records: list[PdfRecord] = []
    for url in links:
        filename = url.rsplit("/", 1)[-1]
        category = classify(filename)
        category_dir = args.output_dir / category
        category_dir.mkdir(parents=True, exist_ok=True)
        path = category_dir / filename

        response = fetch(url, timeout=90)
        status = response.status_code
        content_type = response.headers.get("content-type", "")
        is_pdf = status == 200 and (response.content[:4] == b"%PDF" or "pdf" in content_type.lower())
        sha256 = None
        saved = None
        filename_saved = None
        filename_reused_with_new_hash = False
        if is_pdf:
            digest = hashlib.sha256(response.content).hexdigest()
            sha_path = args.output_dir / "by-sha" / digest[:2] / f"{digest}.pdf"
            sha_path.parent.mkdir(parents=True, exist_ok=True)
            if not sha_path.exists():
                sha_path.write_bytes(response.content)

            if path.exists() and path.read_bytes() != response.content:
                filename_reused_with_new_hash = True
                versioned_path = category_dir / f"{path.stem}.{digest[:12]}{path.suffix}"
                versioned_path.write_bytes(response.content)
                filename_saved = str(versioned_path)
            elif not path.exists():
                path.write_bytes(response.content)
                filename_saved = str(path)
            else:
                filename_saved = str(path)

            sha256 = digest
            saved = str(sha_path)

        records.append(PdfRecord(
            url=url,
            filename=filename,
            category=category,
            status=status,
            content_type=content_type,
            bytes=len(response.content),
            sha256=sha256,
            saved=saved,
            filename_saved=filename_saved,
            filename_reused_with_new_hash=filename_reused_with_new_hash,
        ))
        print(f"{category:20s} {'OK' if is_pdf else 'FAIL':4s} {status} {len(response.content):8d} {filename}")

    manifest = {
        "source_page": args.event_url,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "pdf_count": len(links),
        "category_counts": {},
        "files": [asdict(record) for record in records],
    }
    for record in records:
        manifest["category_counts"][record.category] = manifest["category_counts"].get(record.category, 0) + 1

    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("\nManifest:", manifest_path)
    print("Category counts:", manifest["category_counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
