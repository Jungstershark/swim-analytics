# SG Aquatics Event Discovery Logic

## Source Page

Primary index page:

```text
https://www.sgaquatics.org.sg/swimming/events/event-results/
```

This page corresponds to the mobile menu path shown by Jung Yi:

```text
Singapore Aquatics → menu → Swimming → Events → Swimming Events
```

## Page Logic Observed

The visible mobile list includes competitive swimming event pages such as:

- Singapore Short-Course Invitational 2026
- SAQ ETP Championships 2026
- 21st SNSC 2026
- 56th SNAG 2026
- Singapore Swim Series 2026
- 11th Singapore National Swimming Championships (25m) 2025
- 47th SEA AGE Group Aquatics Championships
- 20th SNSC 2025
- Singapore Swim Series 2025
- 55th SNAG 2025

Important: not every listed event has happened yet, so not every detail page has result PDFs.

## Detail Page Pattern

Event detail pages may contain:

- event-information PDFs;
- start-list PDFs;
- result PDFs;
- full-results PDFs;
- medal tally PDFs;
- age-group/finals placement PDFs;
- expandable sections, e.g. `SNAG Juniors` / `SNAG Seniors`.

For example, `56th SNAG 2026` has:

```text
Event Information
SNAG Juniors
  START LIST
  RESULTS
  MEDAL TALLY
SNAG Seniors
  START LIST
  RESULTS
  Placings based on Age Groups
  MEDAL TALLY
```

## Discovery Status Categories

The discovery script classifies event pages by document readiness:

| Status | Meaning |
|---|---|
| `results_available` | At least one `overall_results` PDF exists; page is candidate for parser preview/import. |
| `documents_available_no_results` | PDFs exist, but no result PDFs yet; track, but do not import. |
| `pending_no_documents` | Page text suggests files are not uploaded yet. |
| `no_documents_found` | No PDFs discovered; may be future, non-result, or unsupported page. |

## Why JSON Manifests

Discovery/archive/preview outputs are stored as JSON because they are pipeline artifacts:

- machine-readable by the next script;
- stable enough for git diffs and tests;
- preserve exact URLs, hashes, statuses, categories, and parser counts;
- easy to convert into Markdown, CSV, DB rows, or UI pages later.

JSON is not intended as the final user-facing format. It is the ingestion control-plane format.

## Current Focused Discovery Output

Script:

```bash
python3 scripts/discover_sgaquatics_events.py \
  --output raw-data/sg-aquatics/event-discovery.json
```

Latest focused discovery found:

```text
Status counts: {'documents_available_no_results': 1, 'results_available': 9}
```

The one non-result-ready competitive swimming page currently found:

```text
Singapore Short-Course Invitational 2026
  status: documents_available_no_results
  PDFs: event_information only
```

## Implementation Notes

The SG Aquatics HTML contains more than the visible competitive swimming event list. Nearby accordion/menu content can include:

- SSPA pages;
- Water Polo;
- Artistic Swimming;
- Diving;
- Open Water;
- Records / Officials / Sanctioning Policy.

Therefore `scripts/discover_sgaquatics_events.py` intentionally focuses on the competitive swimming event-list region between the first known swimming event and non-event/navigation markers. This avoids incorrectly treating other discipline/menu pages as swimming competition result pages.

## Domain Assumptions

- A page without result PDFs is not a failure; it may be future/incomplete.
- `overall_results` remains the v0 importable result category.
- `start_list`, `event_information`, `medal_tally`, and `age_group_results` are archived/source documents, not immediate `Result` imports.
- Filename classification must check specific document-role words (`result`, `start-list`, `medal`, `finals-by-age-group`) before broad meet-title words (`Championships`, `Cships`, `National Age Group Swimming`).

## First Multi-Competition Smoke Test

Archived and previewed:

```text
SAQ ETP Championships 2026
https://www.sgaquatics.org.sg/swimming/events/11thsnsc-25m-2025/saq-etp-championships-2026/
```

Archive command:

```bash
python3 scripts/archive_sgaquatics_events.py \
  --select 'SAQ ETP Championships 2026'
```

Archive result:

```text
event_information: 1
start_list: 1
overall_results: 1
```

Preview command:

```bash
. backend/.venv/bin/activate && \
python3 scripts/preview_archived_sgaquatics_event.py \
  raw-data/sg-aquatics/events/saq-etp-championships-2026/manifest.json \
  --output raw-data/sg-aquatics/events/saq-etp-championships-2026/preview.json
```

Preview result after parser header fix:

```text
files: 1
events: 15
individual_results: 410
relay_results: 0
parser confidence: 100%
failed: 0
```

Root cause of the original 75% confidence was a single-day HY-TEK meet header (`SAQ Emerging Talents Championships 2026 - 31/5/2026`) rather than the date-range header used by 56th SNAG. The parser now supports both.

## Next Step

Use the discovery report to pick candidate pages for raw-archive download and parser preview. Recommended candidates after 56th SNAG:

1. `Singapore Swim Series 2026` — many result PDFs and likely useful parser variation.
2. `SAQ ETP Championships 2026` — smaller page, good smoke test.
3. `21st SNSC 2026` — modern championship-style page.
4. `55th SNAG 2025` — previous SNAG year for cross-year comparison.
