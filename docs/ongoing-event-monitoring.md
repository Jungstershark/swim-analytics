# Swim Analytics — Ongoing Event Monitoring and Re-Vetting Policy

## Problem

SG Aquatics event pages are live operational pages. During an ongoing meet:

- one or two result PDFs may be added each day/session;
- start lists may appear before results;
- result PDFs may be replaced after corrections;
- the site may reuse the same filename for updated content;
- an event may remain listed for months before completion;
- old events may still change if a corrected PDF is uploaded.

Therefore the system must not assume “discovered once = all good forever.”

## Current Direction

The ingestion system should treat source monitoring as a first-class Swim Analytics platform capability, not as an invisible one-off server cron.

Platform-level source monitoring should have:

- database-backed source configurations;
- visible rules in the frontend/admin UI;
- explicit cadence and monitoring windows;
- last-run / next-run / last-change status;
- parser/confidence/import-policy outcomes;
- audit logs for changed PDFs and source revisions;
- manual run / pause / approve-import controls.

The repeated monitoring process is:

```text
scheduled discovery
  → compare event list/statuses
  → archive candidate event pages
  → hash every PDF
  → detect added/changed/removed documents
  → preview changed result PDFs
  → require validation/import policy before DB mutation
```

## SG Aquatics Year-Rollover Behavior

Jung Yi observed that SG Aquatics appears to refresh the event-results page around year-end so the visible list becomes the current year's events. That explains why older 2025 results may no longer appear prominently on the index even though event detail pages and uploaded PDFs can still exist.

Architecture implication:

- The event index is a discovery feed, not the permanent historical catalog.
- Once an event page/PDF is discovered, Swim Analytics should persist it as a `SourceEvent`/raw document record.
- Year rollover should create a new index snapshot, not delete older source events from our archive.
- Older events should move to a lower-frequency monitoring policy rather than disappearing from the platform.
- If old event URLs eventually break, our raw by-SHA archive still preserves the source files we previously captured.

This prevents the platform from depending on SG Aquatics' current-year navigation as the only source of historical truth.

## Key Rule: URL/Filename Is Not Identity

A PDF's durable identity is its content hash:

```text
sha256(raw PDF bytes)
```

Filename and URL are source references, not immutable identity.

Why:

- SG Aquatics can upload `results-day-1.pdf` today and replace it tomorrow with corrected content.
- The URL and filename may stay the same.
- If we key only by filename, we silently lose the previous version and cannot explain changed results.

## Archive Behavior

`scripts/scrape_sgaquatics_event.py` now stores each PDF in two ways:

1. Immutable content-addressed path:

```text
<event>/by-sha/<first-two-hash-chars>/<sha256>.pdf
```

2. Human/source filename path:

```text
<event>/<category>/<filename>.pdf
```

The manifest field meanings:

| Field | Meaning |
|---|---|
| `sha256` | Actual content identity. |
| `saved` | Immutable content-addressed path; this is what parser preview should read. |
| `filename_saved` | Source-friendly filename copy/version path. |
| `filename_reused_with_new_hash` | True if same filename already existed with different bytes. |

If the same filename appears with new content, the script preserves the new content under `by-sha` and writes a versioned filename copy rather than destroying evidence.

## Ongoing Event States

An event page can move through states:

```text
pending_no_documents
  → documents_available_no_results
  → results_available
  → results_available_with_new_documents
  → results_available_with_changed_documents
  → stable/no_change
```

Current discovery statuses are simpler:

```text
results_available
documents_available_no_results
pending_no_documents
no_documents_found
```

Future monitoring should add explicit change statuses based on comparing the new manifest to the previous manifest.

## Daily / Periodic Monitoring Semantics

For events that are not obviously finished/stable:

1. Re-fetch the event index.
2. Re-fetch each discovered event detail page.
3. Compare PDF URL/filename/category list.
4. Download candidate PDFs and hash content.
5. Compare hashes to prior known hashes.
6. For any new hash in an importable category:
   - run parser detection;
   - run parser preview;
   - record confidence/counts;
   - mark as ready-for-review or rejected.
7. Do **not** auto-import unless the event/import policy explicitly allows it.

For events older than a chosen stability window, e.g. 2 months:

- keep lower-frequency checks, e.g. weekly/monthly;
- still detect same-filename hash changes;
- do not silently overwrite imported results;
- surface changes as “source revision detected.”

## Import Safety For Ongoing Events

The system should not assume newly added PDFs are automatically safe.

A new result PDF must pass:

```text
DocumentClassification == overall_results or approved generic result
ParserDetection selects known parser/model
ParserConfidence passes threshold
ImportPolicy allows category/event/status
Dedup/revision logic finds no unsafe conflict
```

Only then should rows be imported or proposed for import.

## Same-Filename Replacement Policy

If the same source URL/filename has a different SHA256 later:

```text
old hash: keep archived
new hash: archive separately
status: source_revision_detected
next action: parse preview + compare counts/results
```

Possible outcomes:

| Outcome | Action |
|---|---|
| New hash only adds missing rows | Candidate import/update. |
| New hash changes existing times/placements | Flag for review before replacing. |
| New hash lowers parser confidence | Do not import automatically. |
| New hash is non-result/corrupt | Archive and flag. |

## Platform Model: Source Rules and Monitor Runs

This is feasible and reusable if we separate **source-specific adapters** from **platform monitoring rules**.

Do not make the platform generic in a fake “scrape any website perfectly” way. Instead:

```text
SourceSite
  └─ adapter_type: sgaquatics_events

SourceRule
  ├─ source_site_id
  ├─ enabled
  ├─ index_url
  ├─ cadence_policy
  ├─ active_window_policy
  ├─ stale_window_policy
  ├─ categories_to_archive
  ├─ categories_to_preview
  ├─ categories_allowed_for_import
  ├─ parser_policy
  └─ auto_import_policy: off / preview_only / approved_only

MonitorRun
  ├─ source_rule_id
  ├─ started_at / finished_at
  ├─ status
  ├─ discovered_events
  ├─ added_documents
  ├─ changed_documents
  ├─ removed_documents
  ├─ preview_passed / preview_failed
  └─ action_required
```

The SG Aquatics-specific part is only the adapter:

```text
fetch SG Aquatics event index
extract Swimming Events region
find event detail pages
extract PDFs
classify event readiness
```

The reusable platform part is:

```text
schedule rule
run monitor
store raw documents by SHA
manifest diff
parser routing
confidence checks
import gate
frontend visibility
approval workflow
```

So yes: this is feasible and worth doing. It is reusable at the right abstraction layer:

- reusable monitor/rule/run/import infrastructure;
- source-specific adapters for SG Aquatics, future federation sites, user uploads, etc.

## Frontend/Admin UI Direction

The frontend should eventually expose a “Sources” or “Ingestion” admin area.

Possible pages:

```text
/admin/sources
/admin/sources/sgaquatics
/admin/source-runs/:id
/admin/import-queue
```

The UI should show:

| Surface | Shows |
|---|---|
| Source rules | Site, URL, adapter, enabled/paused, cadence, active/stale windows. |
| Event discovery | Known competitions, status, first/last seen, result availability. |
| Monitor runs | Last run, next run, changes found, errors. |
| Document archive | PDFs, categories, SHA256, source URL, filename reuse/revision flags. |
| Parser preview | Parser/model chosen, confidence, counts, warnings. |
| Import queue | Ready for import, blocked, needs review, imported. |

This lets scraper/cron behavior be auditable rather than hidden.

## Database Model Implication

The current slice already has the right foundation:

```text
RawDocument.sha256
SourceReference.sourceUrl / filenameSeen
DocumentClassification
ParseJob
IngestionRun
Result.sourceDocumentSha256
Result.parseJobId
Result.ingestionRunId
```

Next schema layer should likely add:

```text
SourceSite
  name
  base_url
  adapter_type

SourceRule
  source_site_id
  enabled
  index_url
  cadence_policy
  active_window_policy
  stale_window_policy
  import_policy

SourceEvent / SourceCompetitionPage
  url
  title
  organization
  current_status
  first_seen_at
  last_checked_at

SourceEventSnapshot / ManifestSnapshot
  source_event_id
  manifest_hash
  checked_at
  added_documents
  changed_documents
  removed_documents
```

This allows a scheduled monitor to say:

```text
No changes since last check.
```

or:

```text
2 new result PDFs added.
1 existing result PDF changed content with same filename.
Preview confidence: 100%, 92%, 0 failed.
Needs import approval.
```

## What The System Should Eventually Report

Example daily monitor output:

```text
SG Aquatics monitor — 2026-03-20

Changed events:
- 56th SNAG 2026
  - +2 overall_results PDFs
  - +2 start_list PDFs
  - 0 same-filename hash changes
  - parser preview: 2/2 passed, 100% confidence
  - action: ready for import review

No-result/future events:
- Singapore Short-Course Invitational 2026
  - still event-info only
```

Example same-filename replacement output:

```text
Source revision detected:
- jan-swim-series-2026-results-day-2-session-2.pdf
  - same URL/filename
  - old sha256: abc...
  - new sha256: def...
  - preview confidence: 100%
  - result count changed: 214 → 216
  - action: manual review before replacing imported rows
```

## Current Implementation Status

Implemented now:

- content-addressed raw PDF storage in the scraper;
- manifest fields needed to detect same-filename reuse;
- parser preview reads immutable `saved` SHA path;
- `scripts/diff_sgaquatics_manifest.py` detects added/removed/changed same-identity documents;
- tests for manifest diff behavior in `backend/tests/test_sgaquatics_manifest_diff.py`;
- SAQ ETP re-preview now passes at 100% after single-day HY-TEK header fix.

Not implemented yet:

- scheduled monitor cron;
- SourceEvent/ManifestSnapshot DB tables;
- automatic import/update policy;
- source-revision comparison UI.

## Recommended Next Implementation

1. Keep using `scripts/diff_sgaquatics_manifest.py` as the tested comparison guardrail before any scheduled monitor/import automation.

2. Add platform-visible source monitoring models before creating any hidden cron:

```text
SourceSite
SourceRule
SourceEvent
SourceEventSnapshot / ManifestSnapshot
MonitorRun
```

3. Add a read-only admin UI surface that displays:

- configured source rules;
- last/next run status;
- known event pages;
- added/changed/removed PDFs;
- parser preview results;
- action-required import queue.

4. Only after rules/runs are visible and auditable, add a scheduler/worker that triggers enabled `SourceRule`s.

5. Keep auto-import off initially; use `preview_only` / `approved_only` until we trust revision and replacement behavior.
