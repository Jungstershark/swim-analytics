# Implementation Slice 2 — Source Monitoring Foundation

## Status

Checkpoint: **Gate 3 must-fixes complete; focused Gate 3 re-review pending**.

Implemented after Gate 3 review:

- frontend copy now explicitly says discovery preview only catalogs source event/document links and does not import swim results;
- ambiguous “docs added” wording changed to “document links” / “catalog docs”;
- successful manual preview shows a visible completion banner: source events/document links updated, swim results not imported;
- failed manual preview errors remain visible after data refresh;
- frontend load requests use sequencing + unmount guard to avoid stale responses overwriting newer state;
- accessibility polish: status/error roles, table header scopes, decorative breadcrumb icon hidden;
- mobile Sources discoverability added via compact mobile nav row; inert mobile menu button removed;
- startup `create_all()` is now explicit local-dev opt-in via `SWIM_ANALYTICS_CREATE_ALL_ON_STARTUP`, not production default;
- `GET /api/admin/sources` is read-only and no longer seeds default source/rule rows;
- default SG Aquatics source/rule seeding moved to Alembic migration `d4b63ef2a9c0`.

Gate 3 fix verification:

- `backend/tests`: `53 passed, 29 skipped, 2 warnings`;
- `frontend`: `npx tsc --noEmit && npm run build` passed;
- `git diff --check` passed;
- release-style migration validation: Alembic seeds one SG Aquatics rule, startup is read-only without `SWIM_ANALYTICS_CREATE_ALL_ON_STARTUP`, and `GET /api/admin/sources` remains read-only;
- release-style temp DB smoke through Next rewrites passed:
  - `GET /admin/sources` -> 200 after dev warmup;
  - `/api/admin/sources` -> one migration-seeded SG Aquatics rule;
  - manual discovery preview -> `succeeded`, `10 events`, `9 result-ready`, `241 document links`, `9 action-required`;
  - post-run APIs -> sources `lastStatus=succeeded`, events `10`, runs `1`.

Implemented frontend/admin page:

- `/admin/sources` page for source-monitoring visibility;
- typed frontend API helpers for admin sources, source events, monitor runs, and manual discovery preview;
- nav link to Sources;
- displays readable rules, manual-only/no-scheduler labels, auto-import disabled, last run counters, source events, and recent monitor runs.

Frontend verification so far:

- `npm run build` passed and route table includes `/admin/sources`;
- temp DB local smoke through Next rewrites passed:
  - `GET /admin/sources` -> 200;
  - initial `/api/admin/sources` -> one SG Aquatics source/rule;
  - `POST /api/admin/source-rules/1/run-discovery-preview` -> `succeeded`, `10 events`, `9 result-ready`, `241 docs`, `actionRequired 9`;
  - post-run APIs -> sources `lastStatus=succeeded`, events `10`, runs `1`.
- Browser visual smoke blocked because Chrome is not installed in this environment.

Implemented after focused Gate 2 data/domain re-review:

- `SourceEventDocument` identity is now canonical document URL within a source event;
- filename/category are metadata and may update over time;
- service de-dupes discovered documents by canonical URL before DB writes;
- ORM/migration unique constraint changed to `(sourceEventId, url)`;
- regression and migration validations cover same canonical PDF URL with different filename/category metadata.

Implemented after Gate 2 review:

- canonical URL identity at source-monitoring service boundary;
- duplicate discovered event/document canonical identities are de-duped before DB mutation;
- failed runs roll back source catalog mutations while preserving a terminal failed `MonitorRun`;
- DB-backed partial unique running-run guard: one `running` `MonitorRun` per `SourceRule`;
- admin source rule payload includes last-run status/counts and readable policy labels;
- manual-run endpoint maps missing/disabled/already-running errors to HTTP-safe statuses.

Implemented after Gate 1:

- source-monitoring models and migration;
- deterministic service tests with fake adapter;
- admin API endpoints/helpers;
- live SG Aquatics discovery adapter using existing script;
- source catalog persistence without domain-row mutation;
- migration validation on simulated deployed schema path.

This slice follows the same guardrail as Slice 1:

- preserve existing domain grouping/display behavior;
- use TDD for production code;
- run role-agent reviews at checkpoints;
- keep hidden cron out until platform rules/runs are visible and auditable.

## Goal

Make official-source scraping/monitoring a first-class Swim Analytics platform capability rather than a hidden script pile.

This slice should add the foundation for:

```text
configured source rule
  → manual monitor run
  → discovered source events
  → run summary visible through API/frontend
  → later scheduler/cron can trigger the same rule
```

No automatic DB import in this slice.

## Why Now

SG Aquatics event pages are not static historical catalogs:

- ongoing events may add one or two result PDFs per day/session;
- corrected PDFs may reuse the same URL/filename;
- year-end page rollover refreshes the visible index to the new year's events;
- old event detail pages and PDFs may still exist even if no longer listed prominently.

Therefore Swim Analytics needs persistent source state instead of relying on today's visible SG Aquatics index.

## Scope

### In Scope

1. Backend models:
   - `SourceSite`
   - `SourceRule`
   - `SourceEvent`
   - `SourceEventDocument`
   - `MonitorRun`

2. Backend read/manual-run API:
   - list source sites/rules;
   - list known source events;
   - list monitor runs;
   - manually run a source rule in preview/discovery mode.

3. SG Aquatics adapter integration:
   - reuse existing discovery logic from `scripts/discover_sgaquatics_events.py`;
   - store event readiness summaries;
   - do not import result rows.

4. Frontend read-only admin surface:
   - `/admin/sources` or equivalent;
   - show configured source rules, event counts, last run status, and action-required state.

5. Migration + tests.

### Out of Scope

- No hidden cron/scheduled worker yet.
- No automatic import/update/replacement of result rows.
- No public user-facing source admin permissions model.
- No full source-revision diff UI yet.
- No domain normalization (`Session`, `MeetEvent`, `AthleteIdentity`, etc.) in this slice.

## Proposed Data Model

### `SourceSite`

Represents a source website family/adapter.

Fields:

```text
id
name
baseUrl
adapterType
isEnabled
createdAt
updatedAt
```

Identity/uniqueness:

```text
UNIQUE(adapterType, baseUrl)
```

Initial row example:

```text
name: SG Aquatics
baseUrl: https://www.sgaquatics.org.sg
adapterType: sgaquatics_events
isEnabled: true
```

### `SourceRule`

Visible platform rule controlling what to monitor and how.

Fields:

```text
id
sourceSiteId
name
indexUrl
enabled
cadencePolicy
activeWindowPolicy
staleWindowPolicy
categoriesToArchive
categoriesToPreview
categoriesAllowedForImport
autoImportPolicy
createdAt
updatedAt
```

Identity/uniqueness:

```text
UNIQUE(sourceSiteId, indexUrl)
```

Policy fields can be JSON strings in v0 to avoid over-normalizing prematurely, but must be canonical JSON and rendered as readable rules in the frontend instead of raw blobs.

Initial row example:

```text
name: SG Aquatics Swimming Events
indexUrl: https://www.sgaquatics.org.sg/swimming/events/event-results/
autoImportPolicy: preview_only
```

### `SourceEvent`

Known event detail page discovered by a source rule.

Fields:

```text
id
sourceRuleId
title
pageTitle
url
sourceYear
sourceDateLabel
readinessStatus
statusReason
isCurrentlyListed
pdfCount
resultPdfCount
categoryCountsJson
firstSeenAt
lastSeenInIndexAt
lastCheckedAt
lastChangedAt
lastErrorMessage
createdAt
updatedAt
```

Important domain/source assumptions:

> SG Aquatics index is a discovery feed, not a permanent historical catalog. Once an event is discovered, it should remain in Swim Analytics even if a future year-end rollover removes it from the visible index.

> `SourceEvent` is source metadata, not the same thing as domain `Meet`. This slice must not create/update/delete `Meet`, `Swimmer`, `Result`, `RelayResult`, or `RelayLeg`.

Identity/uniqueness:

```text
UNIQUE(sourceRuleId, url)
```

Use normalized canonical URL as identity. Do not use title as identity; event names may repeat by year or change cosmetically.

Readiness status values are source readiness only:

```text
pending_no_documents
documents_available_no_results
results_available
no_documents_found
```

Do not overload readiness with change/action state.

### `SourceEventDocument`

Per-PDF document-link state discovered on an event page.

Fields:

```text
id
sourceEventId
url
filename
category
firstSeenAt
lastSeenAt
lastCheckedAt
lastHashSha256
lastHashCheckedAt
isCurrentlyListed
createdAt
updatedAt
```

Identity/uniqueness:

```text
UNIQUE(sourceEventId, url, filename, category)
```

This preserves document-level discovery state even when counts are unchanged. In this slice, same-filename replacement detection is only possible if/when bytes are downloaded and hashed. If manual discovery does not archive/hash PDFs yet, then changed-content detection is explicitly deferred, but the document-link identity is persisted so the next archive/hash slice can diff safely.

Change/action state belongs in `MonitorRun.summaryJson`, not in `SourceEvent.readinessStatus`.

### `MonitorRun`

One execution of a source rule.

Fields:

```text
id
sourceRuleId
triggerType
triggeredBy
adapterVersion
indexUrlSnapshot
ruleConfigSnapshotJson
startedAt
finishedAt
status
eventsDiscovered
eventsWithResults
addedEvents
updatedEvents
unchangedEvents
absentFromIndexEvents
addedDocuments
updatedDocuments
unchangedDocuments
actionRequiredCount
errorMessage
summaryJson
createdAt
updatedAt
```

Lifecycle semantics:

- create `MonitorRun` at start with `status = running`;
- always set `finishedAt`, terminal `status`, `errorMessage`, and `summaryJson` in success and error paths;
- terminal statuses: `succeeded`, `failed`, `partial_failed`;
- adapter/page-level failures should appear in `summaryJson`, not only as API 500s;
- v0 manual run should be synchronous;
- concurrent runs for the same `SourceRule` should be rejected while one is `running`.

## API Shape

Initial read-only/admin endpoints:

```text
GET  /api/admin/sources
GET  /api/admin/source-events
GET  /api/admin/monitor-runs
POST /api/admin/source-rules/{id}/run-discovery-preview
```

`run-discovery-preview` should be labeled clearly in code/UI:

> Run discovery preview — updates the source-event/document catalog and records a `MonitorRun`; does not archive PDFs or import result rows.

It should:

1. load the source rule;
2. choose adapter by `adapterType`;
3. discover current event pages;
4. upsert `SourceEvent` and `SourceEventDocument` rows;
5. create `MonitorRun` summary;
6. return what changed;
7. not archive/download PDFs and not import rows in this slice. Same-filename content replacement detection is deferred to archive/hash slice.

## Frontend Shape

Initial admin page should show enough to verify the platform direction:

```text
/admin/sources
```

Sections:

1. Source rules
   - site, adapter, index URL, enabled, readable policy, last status.
   - explicitly show `Schedule: Not configured`, `Last trigger: Manual`, and `Automatic import: Disabled / preview_only` in v0.
2. Latest monitor runs
   - status, started/finished, events discovered, events with results, error.
3. Known events
   - title, status, pdf count, result pdf count, first/last seen, last checked.
4. Manual action
   - button: Run discovery preview.

## TDD Checkpoints

### Checkpoint A — model/API foundation

Tests first:

- creating default SG Aquatics source config is idempotent;
- repeated manual runs upsert the same source events/documents rather than duplicating them;
- manual run stores `MonitorRun` and upserts `SourceEvent`/`SourceEventDocument`;
- year-rollover behavior retains previously known source events absent from a later discovery and marks them not currently listed;
- source readiness status remains separate from monitor-run change/action summary.

### Checkpoint B — adapter boundary

Tests first:

- adapter output can be injected/faked for deterministic API tests;
- `run-discovery-preview` does not create/update/delete `Meet`, `Swimmer`, `Result`, `RelayResult`, or `RelayLeg` rows;
- adapter failure records a terminal failed `MonitorRun` with `finishedAt`, `errorMessage`, and `summaryJson`.

### Checkpoint C — frontend visibility

Tests/build:

- frontend builds;
- admin page renders source rules/runs/events from mocked or live API shape.

## Review Team Gates

### Gate 1 — pre-implementation design review

Roles:

1. Data/domain reviewer: source-event model, year rollover, category/status semantics.
2. Product/UX reviewer: admin visibility, rule configuration, no hidden cron.
3. Ops/maintainability reviewer: scheduler boundary, auditability, retries, error state, migration safety.

### Gate 2 — backend implementation review

After models/API/tests/migration but before frontend.

### Gate 3 — frontend/admin review

After frontend page but before final verification/commit.

## Gate 1 Review Outcome

Gate 1 reviewers approved the direction after tightening these design requirements:

- persist document-level discovery state via `SourceEventDocument`, not only event counts;
- clearly defer same-filename replacement detection unless the slice downloads/hashes bytes;
- separate source readiness from change/action status;
- split rollover timestamps: `firstSeenAt`, `lastSeenInIndexAt`, `lastCheckedAt`, `lastChangedAt`, `isCurrentlyListed`;
- define uniqueness/idempotency constraints;
- define `MonitorRun` lifecycle/failure semantics and concurrency behavior;
- rename/copy `run-preview` as `run-discovery-preview` because it persists source catalog state;
- frontend must show scheduler absence and render policies as readable rules, not raw JSON blobs;
- production schema changes must be migration-backed, not rely on startup `create_all()`.

## Open Questions / Defaults

1. Admin routes can be unauthenticated for Sharklet-private v0, but should be named `/admin/...` to reserve permissioning later.
2. Policy fields remain JSON strings in v0 for flexibility.
3. Auto-import defaults to `preview_only`.
4. Scheduler/cron is explicitly deferred until source rules and monitor runs are visible.
