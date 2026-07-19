# Swim Analytics — Ingestion Manifests and Parser Routing Architecture

## Why JSON Exists In This Architecture

JSON is not chosen because humans prefer reading JSON. It is chosen because the ingestion pipeline needs a durable, machine-readable handoff between stages.

The core architecture is intentionally staged:

```text
SG Aquatics index page
  → event discovery JSON
  → per-event raw archive manifest JSON
  → parser preview JSON
  → explicit import decision
  → DB rows with provenance
```

Each JSON file is a checkpoint. It records exactly what the previous stage observed or produced, so the next stage does not need to rediscover, guess, or rescrape unnecessarily.

## Why Not Go Straight Site → Parser → DB?

Because that makes scaling fragile.

If we go directly from website scrape to DB import, several problems appear:

- Future/incomplete events look like failures.
- Different event pages may have different PDF layouts.
- Non-result PDFs can accidentally be parsed/imported as results.
- Parser changes are hard to audit.
- Rebuilds depend on the live website still having the same files.
- There is no clean place to inspect what changed between runs.

The JSON artifacts give us stable intermediate layers.

## What Each JSON File Is For

### 1. `event-discovery.json`

Produced by:

```bash
python3 scripts/discover_sgaquatics_events.py \
  --output raw-data/sg-aquatics/event-discovery.json
```

Purpose:

> Represent the SG Aquatics event index as a machine-readable list of event pages and readiness statuses.

Contains:

```json
{
  "index_url": "https://www.sgaquatics.org.sg/swimming/events/event-results/",
  "discovered_at": "2026-07-19T...Z",
  "event_count": 10,
  "status_counts": {
    "results_available": 9,
    "documents_available_no_results": 1
  },
  "events": [
    {
      "title": "Singapore Swim Series 2026",
      "url": "https://www.sgaquatics.org.sg/swimming/events/singapore-swim-series-2026/",
      "page_title": "Singapore Swim Series 2026",
      "status": "results_available",
      "pdf_count": 32,
      "category_counts": {
        "event_information": 2,
        "start_list": 14,
        "overall_results": 16
      },
      "pdfs": [
        {
          "url": "https://www.sgaquatics.org.sg/app/uploads/...pdf",
          "filename": "jan-swim-series-2026-results-day-1-session-1.pdf",
          "category": "overall_results"
        }
      ]
    }
  ]
}
```

Used for:

- deciding which events are ready for archive/preview;
- skipping future/incomplete events without treating them as errors;
- comparing event-index changes over time;
- later feeding `SourceEvent` / `SourceCompetitionPage` rows.

### 2. Per-event `manifest.json`

Produced by:

```bash
python3 scripts/archive_sgaquatics_events.py \
  --select 'SAQ ETP Championships 2026'
```

Internally calls:

```bash
python3 scripts/scrape_sgaquatics_event.py <event_url> <output_dir>
```

Purpose:

> Represent the exact raw PDF library for one competition/event page.

Contains:

```json
{
  "source_page": "https://www.sgaquatics.org.sg/swimming/events/.../",
  "downloaded_at": "2026-07-19T...Z",
  "pdf_count": 3,
  "category_counts": {
    "event_information": 1,
    "start_list": 1,
    "overall_results": 1
  },
  "files": [
    {
      "url": "https://www.sgaquatics.org.sg/app/uploads/...pdf",
      "filename": "saq-etp-championships-2026-full-results.pdf",
      "category": "overall_results",
      "status": 200,
      "content_type": "application/pdf",
      "bytes": 102803,
      "sha256": "...",
      "saved": "raw-data/sg-aquatics/events/.../overall_results/...pdf"
    }
  ]
}
```

Used for:

- preserving exact raw source files and hashes;
- proving whether a file changed later;
- feeding parser preview without hitting the website again;
- later feeding `RawDocument` / `SourceReference` rows;
- rebuilds from raw documents instead of live pages.

### 3. Per-event `preview.json`

Produced by:

```bash
. backend/.venv/bin/activate && \
python3 scripts/preview_archived_sgaquatics_event.py \
  raw-data/sg-aquatics/events/<event>/manifest.json \
  --output raw-data/sg-aquatics/events/<event>/preview.json
```

Purpose:

> Represent parser results before DB import.

Contains:

```json
{
  "manifest": "raw-data/sg-aquatics/events/.../manifest.json",
  "source_page": "https://www.sgaquatics.org.sg/swimming/events/.../",
  "totals": {
    "files": 1,
    "events": 15,
    "individual_results": 410,
    "relay_results": 0,
    "failed": 0
  },
  "files": [
    {
      "filename": "saq-etp-championships-2026-full-results.pdf",
      "path": "raw-data/sg-aquatics/events/...pdf",
      "sha256": "...",
      "status": "ok",
      "parser_format": "hytek",
      "confidence_percent": 75,
      "events": 15,
      "individual_results": 410,
      "relay_results": 0,
      "error": null
    }
  ]
}
```

Used for:

- detecting low-confidence parser runs before import;
- comparing parser quality across competition types;
- deciding whether a new document format needs a new parser/model;
- later creating `ParseJob` records;
- giving maintainers a safe review gate.

## Parser Architecture: Do Not Let One Parser Swallow Everything

The parser layer should be a registry/router, not a single giant parser.

Current parser:

```text
HyTekParser
  format_name: hytek
  parser_version: hytek-v1
```

Current routing foundation:

```text
file
  → each parser sniffs file cheaply
  → each parser returns DetectionResult
  → registry selects highest-confidence parser
  → selected parser parses
  → ParseJob records parser name/version/confidence/counts
```

The detection result includes:

```text
parser
format_name
parser_version
confidence
reason
can_parse
```

This protects the current HY-TEK parser because future formats do not require weakening its regex assumptions. Instead, we add another parser/model with its own detection rules.

## Future Parser Families

Possible future parser/model types:

| Parser | Use case | Detection signals |
|---|---|---|
| `hytek-v1` | Current SG Aquatics HY-TEK Meet Manager PDFs | `HY-TEK`, `MEET MANAGER`, known event/result headers |
| `hytek-alt-v1` | HY-TEK-like but layout variant / lower confidence | HY-TEK-ish headers but column/session differences |
| `omega-v1` | Omega/timing-system exports if encountered | Omega branding, different result table structure |
| `open-water-v1` | Open water result PDFs | distance/category/rank formats unlike pool events |
| `artistic/diving` parsers | Other aquatics disciplines | entirely different scoring model; not swim-performance import |
| `llm-assisted-table-v1` | Fallback extraction for unusual but important PDFs | low deterministic confidence; requires strict validation/human review |

Important: an LLM/model parser should not silently import. It should produce structured candidates plus diagnostics that pass validation before import.

## Routing Rule

The system should choose parser by **format detection**, not by event name alone.

Event/page metadata can hint, but actual parser choice should depend on document evidence:

```text
filename
PDF first-page text
headers/branding
column names
event/result row patterns
known failure signatures
```

A page like `Singapore Swim Series 2026` can still use HY-TEK if its PDFs match HY-TEK. A different event under the same SG Aquatics site may need another parser.

## Import Rule

Parser support does not automatically mean import eligibility.

Separate decisions:

```text
DocumentClassification: what kind of file is this?
ParserDetection: which parser can parse this file?
ParserConfidence: did parsing look reliable?
ImportPolicy: should parsed rows enter Result/RelayResult now?
```

Example:

```text
age_group_results
  classification: age_group_results
  parser: maybe hytek
  confidence: maybe high
  import policy: archive-only for now
```

That is correct because it may describe alternate rankings over the same swims, not new swim performances.

## Why SAQ ETP 75% Confidence Matters

The SAQ ETP smoke test originally parsed as:

```text
1 result PDF
15 events
410 individual results
0 relay results
75% confidence
```

Root cause: the PDF is HY-TEK but uses a single-day meet header:

```text
SAQ Emerging Talents Championships 2026 - 31/5/2026
```

The original parser expected a date range:

```text
56th SNAG Seniors - 17/3/2026 to 22/3/2026
```

After adding a regression test and supporting single-day headers, SAQ ETP now previews at:

```text
parser_format: hytek
parser_version: hytek-v1
confidence: 100%
events: 15
individual_results: 410
relay_results: 0
```

This was a HY-TEK variant within the same parser family, not a new parser family.

## Design Principle

Do not make the HY-TEK parser broader until it becomes unreliable.

Prefer:

```text
specific parser + explicit detection + confidence + tests
```

rather than:

```text
one increasingly permissive parser that accepts everything
```

## Next Implementation Step

1. Add parser detection diagnostics to preview JSON, including detection reason and parser version.
2. Inspect SAQ ETP unmatched lines/confidence checks.
3. Decide whether it is:
   - HY-TEK with harmless confidence-check mismatch;
   - HY-TEK variant needing targeted parser improvements;
   - a genuinely different format needing a new parser.
4. Add tests from real SAQ ETP samples before changing parser behavior.
