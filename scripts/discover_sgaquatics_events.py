#!/usr/bin/env python3
"""Discover SG Aquatics swimming event pages and their document/readiness status.

This is a read-only reconnaissance step for official-source ingestion. It starts
from the SG Aquatics event-results index, extracts event detail links, inspects
each detail page for PDF links, and reports whether the page appears importable
now.

Domain assumptions:
- Not every event listed on SG Aquatics has happened yet.
- Future/incomplete pages may have event-info or start-list PDFs but no result
  PDFs; those should be tracked as discovered events, not treated as failures.
- `overall_results` PDFs are the v0 importable category. Other PDF categories
  are useful source documents but archive-only until their domain model exists.
"""
from __future__ import annotations

import argparse
import html as htmlmod
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen

BASE_URL = "https://www.sgaquatics.org.sg"
DEFAULT_INDEX_URL = f"{BASE_URL}/swimming/events/event-results/"
USER_AGENT = "Mozilla/5.0 (compatible; swim-analytics-event-discovery/0.1)"


@dataclass
class EventLink:
    title: str
    url: str


@dataclass
class PdfLink:
    url: str
    filename: str
    category: str


@dataclass
class EventDiscovery:
    title: str
    url: str
    page_title: str | None
    status: str
    pdf_count: int
    category_counts: dict[str, int]
    pdfs: list[PdfLink]


def fetch_text(url: str, timeout: int = 30) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def strip_tags(value: str) -> str:
    return " ".join(htmlmod.unescape(re.sub(r"<[^>]+>", " ", value)).split())


def normalize_url(base_url: str, href: str) -> str:
    return urljoin(base_url, htmlmod.unescape(unquote(href.strip())))


def classify_pdf(filename: str) -> str:
    """Classify SG Aquatics PDF filenames.

    Keep this in sync with `backend/app/ingestion.py` and
    `scripts/scrape_sgaquatics_event.py`: specific document-role words must win
    over broad meet-title words like Championships/Cships.
    """
    name = filename.lower()
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
    if "info" in name or "information" in name or "event" in name:
        return "event_information"
    return "other_pdf"


def extract_page_title(html: str) -> str | None:
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.I | re.S)
    if match:
        return strip_tags(match.group(1))
    title = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    return strip_tags(title.group(1)) if title else None


def focus_swimming_event_list_region(html: str) -> str:
    """Return the page region containing the competitive Swimming Events list.

    The SG Aquatics page HTML includes nearby accordion/menu content for SSPA,
    Water Polo, Artistic Swimming, Diving, and Open Water. The phone UI shows the
    competitive swimming event list between the `Swimming Events` item and the
    following non-event/navigation items such as `Sanctioning Policy` / `Records`.
    Restricting to this region prevents the discovery step from treating other
    discipline pages as swimming competition result pages.
    """
    start_candidates = [
        html.find("Singapore Short-Course Invitational"),
        html.find("SAQ ETP Championships"),
        html.find("56th SNAG"),
    ]
    starts = [pos for pos in start_candidates if pos >= 0]
    if not starts:
        return html
    start = max(0, min(starts) - 1000)

    end_candidates = []
    for marker in ("Sanctioning Policy", "Records", "Water Polo", "Artistic Swimming", "Diving"):
        pos = html.find(marker, min(starts))
        if pos >= 0:
            end_candidates.append(pos)
    end = min(end_candidates) if end_candidates else len(html)
    return html[start:end]


def extract_event_links(index_url: str, html: str) -> list[EventLink]:
    """Extract event detail links from the event-results page.

    The SG Aquatics mobile menu displays event links from the page HTML, but not
    every link is a result-bearing event. We keep likely event pages and exclude
    navigation/policy links.
    """
    index_path = urlparse(index_url).path.rstrip("/")
    html = focus_swimming_event_list_region(html)
    candidates: list[EventLink] = []
    for match in re.finditer(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, flags=re.I | re.S):
        href = normalize_url(index_url, match.group(1))
        label = strip_tags(match.group(2))
        if not label:
            continue

        parsed = urlparse(href)
        if parsed.netloc and parsed.netloc != urlparse(BASE_URL).netloc:
            continue
        path = parsed.path.rstrip("/")
        if not path or path == index_path:
            continue
        if path.endswith("/swimming/events") or "sanctioning-policy" in path:
            continue
        if ".pdf" in path.lower() or "/app/uploads/" in path:
            continue

        looks_like_event = (
            "/swimming/events/" in path
            or bool(re.search(r"\b(\d{2}(?:st|nd|rd|th)|SNAG|SNSC|Swim Series|Championship|Invitational|Open Water|ETP)\b", label, flags=re.I))
        )
        if looks_like_event:
            candidates.append(EventLink(title=label, url=href))

    seen: set[str] = set()
    ordered: list[EventLink] = []
    for candidate in candidates:
        if candidate.url in seen:
            continue
        seen.add(candidate.url)
        ordered.append(candidate)
    return ordered


def extract_pdf_links(page_url: str, html: str) -> list[PdfLink]:
    candidates: list[str] = []
    for match in re.finditer(r"href=[\"']([^\"']+\.pdf)[\"']", html, flags=re.I):
        candidates.append(match.group(1))
    for match in re.finditer(r"https?://[^\s\"'<>]+\.pdf", html, flags=re.I):
        candidates.append(match.group(0))

    seen: set[str] = set()
    pdfs: list[PdfLink] = []
    for raw in candidates:
        url = normalize_url(page_url, raw)
        if url in seen:
            continue
        seen.add(url)
        filename = url.rsplit("/", 1)[-1]
        pdfs.append(PdfLink(url=url, filename=filename, category=classify_pdf(filename)))
    return pdfs


def determine_status(category_counts: dict[str, int], html: str) -> str:
    if category_counts.get("overall_results", 0) > 0:
        return "results_available"
    if category_counts:
        return "documents_available_no_results"
    if re.search(r"coming soon|file to be uploaded|to be uploaded", html, flags=re.I):
        return "pending_no_documents"
    return "no_documents_found"


def inspect_event(event: EventLink) -> EventDiscovery:
    html = fetch_text(event.url)
    page_title = extract_page_title(html)
    pdfs = extract_pdf_links(event.url, html)
    category_counts: dict[str, int] = {}
    for pdf in pdfs:
        category_counts[pdf.category] = category_counts.get(pdf.category, 0) + 1
    status = determine_status(category_counts, html)
    return EventDiscovery(
        title=event.title,
        url=event.url,
        page_title=page_title,
        status=status,
        pdf_count=len(pdfs),
        category_counts=category_counts,
        pdfs=pdfs,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover SG Aquatics swimming events and result readiness")
    parser.add_argument("--index-url", default=DEFAULT_INDEX_URL)
    parser.add_argument("--output", type=Path, default=Path("raw-data/sg-aquatics/event-discovery.json"))
    parser.add_argument("--limit", type=int, default=None, help="Optional event limit for quick checks")
    args = parser.parse_args()

    index_html = fetch_text(args.index_url)
    event_links = extract_event_links(args.index_url, index_html)
    if args.limit is not None:
        event_links = event_links[: args.limit]

    discoveries: list[EventDiscovery] = []
    for event in event_links:
        try:
            discovery = inspect_event(event)
        except Exception as exc:  # keep discovery robust across odd/unfinished pages
            discovery = EventDiscovery(
                title=event.title,
                url=event.url,
                page_title=None,
                status=f"error:{type(exc).__name__}",
                pdf_count=0,
                category_counts={},
                pdfs=[],
            )
        discoveries.append(discovery)
        print(f"{discovery.status:30s} {discovery.pdf_count:3d} {discovery.title} -> {discovery.url}")
        if discovery.category_counts:
            print(f"  {discovery.category_counts}")

    report = {
        "index_url": args.index_url,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "event_count": len(discoveries),
        "status_counts": {},
        "events": [asdict(discovery) for discovery in discoveries],
    }
    for discovery in discoveries:
        report["status_counts"][discovery.status] = report["status_counts"].get(discovery.status, 0) + 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\nReport:", args.output)
    print("Status counts:", report["status_counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
