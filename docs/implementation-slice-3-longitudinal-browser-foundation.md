# Implementation Slice 3 — Longitudinal Browser Foundation

Status: **Gate 1 MUST-FIX addressed; focused re-review pending**  
Branch: `feat/longitudinal-browser-foundation`

## Why this slice

After loading 56th SNAG 2026 into production, Swim Analytics now has enough real cardinality to stop treating the UI as a thin parser demo. The next product foundation is a Meet Mobile-respecting but longitudinally stronger browsing experience:

```text
Meet → event/round/session-ish view → swimmer → race history → progression
```

This does **not** change the current strategic focus or chase Meet Mobile scraping. Meet Mobile historical capture remains KIV in `docs/meet-mobile-historical-data-strategy.md`. This slice focuses on official-source data already in our DB.

## Live production baseline

Current live production data after SNAG import:

| Metric | Count |
|---|---:|
| Meets | 2 |
| Swimmers | 1,955 |
| Individual results | 10,649 |
| Relay results | 348 |
| Relay legs | 1,367 |
| Raw documents | 17 |
| Source references | 17 |

Meets:

| Meet | Individual results | Distinct swimmers |
|---|---:|---:|
| 56th SNAG Juniors | 4,195 | 828 |
| 56th SNAG Seniors | 6,454 | 1,162 |

Top observed event cardinalities include 275 rows for `Men 15 & Over 50 LC Meter Freestyle` and 215 rows for `Women 15 & Over 50 LC Meter Freestyle`, so UI must handle long event result tables.

## Current product gaps

Existing pages are useful but still feel like accumulated vertical slices:

| Surface | Current gap |
|---|---|
| `/swimmers` | Lists swimmers, but search/team filtering is basic and API does N+1 count queries per row. |
| `/swimmers/[id]` | Has PBs and competition history, but recent history is capped to 20 individual swims; relay rows are separate; event progression is not first-class. |
| `/meets/[id]` | Groups individual results by event only; relay results are absent; no session/day summary; long event tables require better progressive disclosure. |
| `/results` | Powerful table but broad/global; not a coherent swimmer-first or meet-first journey. |
| Data quality | Live sample exposed at least one parser-contaminated swimmer name, e.g. a name containing race/split text. This must be tracked as data-quality debt, not hidden by UI polish. |
| Source trust | User-facing result pages do not yet surface source/provenance/confidence enough for maintainers/admins. |

## Slice goal

Create the first **longitudinal browser foundation**:

1. A swimmer can find themselves and see their history clearly.
2. A meet/event viewer can browse the official result structure without losing relays.
3. The UI exposes enough source/data-quality context to remain honest.
4. The backend gives frontend a deliberate browser API contract instead of forcing it to reconstruct domain meaning from generic result lists.

## Non-goals

- No Meet Mobile scraping implementation in this slice.
- No Android automation yet.
- No hidden scheduler/auto-import.
- No replacement of the existing parser unless a focused parser bug is isolated with fixtures/tests.
- No full timing-system/HY-TEK meet-ops integration.
- No major schema expansion unless Gate 1 reviewers agree the read model cannot be safely expressed from current tables.

## Proposed vertical slice

### Backend/API

Add browser-focused read models that preserve current DB schema and make the main user journeys explicit.

#### Endpoint ownership

| Endpoint | Purpose | Pagination/limits | Notes |
|---|---|---|---|
| `GET /api/browser/overview` | Counts, latest meets, top events, source/provenance summary for landing/dashboard cards. | none | One compact dashboard payload. |
| `GET /api/browser/swimmers` | **Find myself** list/typeahead owner: name/team search, counts, latest meet, data-quality flags. | `page>=1`, `limit<=100`, default `50` | Replaces N+1-style list needs for Slice 3 UI; existing `/api/swimmers` may remain compatibility. |
| `GET /api/browser/swimmers/{id}` | Full swimmer history grouped by event and meet; PBs; improvement deltas; relay participation; source-backed result counts. | history groups may be capped in future; v0 returns all for one swimmer | Primary swimmer profile read model. |
| `GET /api/browser/meets/{id}` | Meet summary and **event group index only**: event counts, round counts, row counts, relay/individual counts, source summary. | none | Must **not** return full meet-scale result tables. |
| `GET /api/browser/events` | Row-owner for one meet/event group, suitable for long tables and direct linking. | `page>=1`, `limit<=200`, default `50` | Filters: `meet_id`, `event_key`; optional `round`, `row_type=all|individual|relay`, `order=place|time|name`. |
| `GET /api/browser/data-quality` | Lightweight warnings: suspicious swimmer names, missing source hashes, no-time rows, parse/provenance coverage. | `page>=1`, `limit<=100`, default `50`; sample cap per warning | Also summary counts by warning type/severity. |

#### Stable event identity contract

Because the current schema has no normalized `MeetEvent`/`Session` table, browser v0 must expose event groups as **derived display groups**, not authoritative domain objects.

Event group fields:

```json
{
  "event_key": "meet-2-src-17-men-15-over-50-lc-meter-freestyle",
  "meet_id": 2,
  "source_event_number": "17",
  "event_label": "Men 15 & Over 50 LC Meter Freestyle",
  "normalization_status": "raw_event_string",
  "derived": true,
  "rounds": ["Prelim", "Final"],
  "swim_dates": ["2026-03-17"],
  "individual_count": 275,
  "relay_count": 0,
  "total_rows": 275
}
```

Key derivation:

1. Prefer `meet_id + sourceEventNumber + event` where `sourceEventNumber` exists.
2. Fall back to `meet_id + event`.
3. Slug the composite deterministically for URLs.
4. Keep raw `event_label` in the response; never ask the frontend to reconstruct event identity from table text.

Session/day language:

- v0 may display `round` and `swim_date` groupings.
- v0 must not label these as first-class “sessions” because no `Session` domain table exists yet.
- API responses should include `derived: true` / `normalization_status: "raw_event_string"` wherever event/session-ish meaning is derived.

#### Event row contract

`/api/browser/events` returns a discriminated row model:

```json
{
  "event_group": { "event_key": "...", "event_label": "...", "derived": true },
  "data": [
    {
      "row_type": "individual",
      "id": 123,
      "round": "Final",
      "swim_date": "2026-03-17",
      "placement": 1,
      "time": "24.51",
      "is_dq": false,
      "swimmer": { "id": 10, "name": "...", "team": "...", "age": 17 },
      "source": { "document_sha256": "...", "parse_job_id": 7, "source_scope": "result" },
      "warnings": []
    },
    {
      "row_type": "relay",
      "id": 55,
      "round": "Final",
      "placement": 1,
      "time": "1:42.00",
      "team_name": "...",
      "relay_letter": "A",
      "legs": [
        {
          "leg_number": 1,
          "swimmer_id": 10,
          "swimmer_name": "...",
          "split_time": "25.10",
          "matched_by": "relay_leg_swimmer_id",
          "identity_match_confidence": "high"
        }
      ],
      "source": { "document_sha256": "...", "parse_job_id": 7, "source_scope": "parent_relay_result" },
      "warnings": []
    }
  ],
  "pagination": { "page": 1, "limit": 50, "total": 275, "total_pages": 6 }
}
```

Relay rows must be first-class rows, not inferred from separate tables in the frontend.

#### Swimmer search/list contract

`GET /api/browser/swimmers` is the Slice 3 “find myself” owner.

Filters/sort:

| Param | Semantics |
|---|---|
| `q` | Case-insensitive swimmer name search. |
| `team` | Case-insensitive team/club search. |
| `min_results` | Optional integer lower bound. |
| `has_warnings` | Optional boolean for data-quality triage. |
| `sort` | `name|team|result_count|latest_meet`, default `name`. |
| `order` | `asc|desc`, default based on sort. |

List item fields:

```json
{
  "id": 855,
  "name": "Pung, Zhi En Timothy",
  "age": 17,
  "team": "Aquatic Performance Swim Club",
  "individual_result_count": 19,
  "relay_result_count": 2,
  "meet_count": 1,
  "event_count": 12,
  "latest_meet": { "id": 2, "name": "56th SNAG Seniors", "date": "2026-03-17" },
  "warning_count": 0,
  "warnings": []
}
```

Acceptance must include 1,955-swimmer search/list behavior and mobile-friendly list cards.

#### Swimmer detail relay identity contract

Relay participation in `GET /api/browser/swimmers/{id}` must use explicit identity semantics:

1. Primary match: `RelayLeg.swimmerId == swimmer.id` → `matched_by="relay_leg_swimmer_id"`, confidence `high`.
2. Safe fallback only if primary misses and `normalized(RelayLeg.swimmerName) == normalized(Swimmer.name)` with no ambiguous same-name swimmers in the candidate teams/meet → confidence `medium`, `matched_by="normalized_name_unique_in_meet"`.
3. Ambiguous/unmatched relay legs must not be silently merged into swimmer history. Return row/profile warnings instead.
4. Relay rows do not contribute to PB/progression unless a future explicit rule is approved.

#### Data-quality warning contract

Warning schema:

```json
{
  "type": "suspicious_swimmer_name",
  "severity": "warning",
  "entity_kind": "swimmer",
  "entity_id": 123,
  "message": "Swimmer name contains timing/event-like artifacts.",
  "count": 1,
  "sample_rows": [{ "result_id": 456, "meet_id": 2, "event_key": "..." }],
  "source_fields": ["Swimmer.name"]
}
```

Initial warning types:

| Type | Detection rule | Severity |
|---|---|---|
| `suspicious_swimmer_name` | Name contains timing patterns, event fragments, `LC Meter`, lane/result artifacts, or unusually long parser-contaminated strings. | warning |
| `missing_result_source` | Individual/relay result lacks `sourceDocumentSha256` or `parseJobId`. | warning |
| `relay_identity_ambiguous` | Relay leg fallback would match multiple candidate swimmers. | warning |
| `relay_identity_unmatched` | Relay leg has no swimmer ID and no safe unique fallback. | info/warning depending count |
| `no_time_result` | Non-DQ result has no parseable time. | info |

Warnings must be row/profile-scoped where relevant: swimmer and meet/event browser responses include warning counts/flags and affected IDs, not only the separate `/data-quality` endpoint.

The browser endpoints should be read-only and optimized enough for SNAG cardinality. Avoid N+1 query loops on large list surfaces.

### Frontend

Keep current routes but refit them around user jobs:

| Route | User job |
|---|---|
| `/` | Understand database coverage and jump into meets/swimmers/results. |
| `/meets/[id]` | Browse a meet like Meet Mobile baseline: event group index, counts, source/quality summary. |
| `/meets/[id]/events/[eventKey]` | Canonical direct link to one event group with paginated individual/relay rows. |
| `/swimmers/[id]` | Understand one swimmer longitudinally: PBs, event history, progression, relays, source coverage. |
| `/results` | Advanced global search/filter, not the main longitudinal story. |

#### Frontend deep-link/state contract

`/meets/[id]/events/[eventKey]` is the canonical user-facing event direct link. Query params mirror the row-owner API:

| Param | Semantics |
|---|---|
| `page` | 1-based page, default `1`. |
| `limit` | Page size, default `50`, max `200`. |
| `round` | Optional exact round filter such as `Final` or `Prelim`. |
| `row_type` | `all|individual|relay`, default `all`. |
| `order` | `place|time|name`, default `place`. |

Navigation behavior:

- `/meets/[id]` renders the event group index and links each group to `/meets/[id]/events/[eventKey]`.
- Event detail page includes a clear return link to `/meets/[id]` preserving no hidden state requirement.
- Swimmer profile history rows can link to `/meets/[id]/events/[eventKey]` when `event_key` is available.
- Invalid `eventKey` returns a user-facing not-found/empty state with a link back to `/meets/[id]`; it must not silently fall back to a fuzzy event match.
- Pagination/sort/filter state lives in the URL query string so refresh/back/forward preserve the exact event view.
- `/meets/[id]?event_key=...` is not canonical in Slice 3; if encountered later, it may redirect to `/meets/[id]/events/[eventKey]` but the initial implementation should prefer the explicit nested route.

### Data quality handling

Add visible, non-blocking warnings rather than silently hiding bad rows:

- suspicious swimmer names with embedded timing/event artifacts;
- results without sourceDocumentSha256;
- parse jobs/confidence coverage;
- relay leg source coverage.

These warnings should route to admin/review surfaces later; in this slice they can be read-only visibility.

## Acceptance criteria

### Product/IA

- Swimmer-first journey answers: “What are my PBs, how many swims/meets, what events do I swim, and what changed over time?”
- Meet-first journey answers: “What events happened, what rounds/results exist, and where are relays?”
- Global results remains a power-search surface, not the only way to understand the database.
- Meet Mobile principle translated: preserve familiar meet/event/swimmer navigation, but add longitudinal meaning.

### Data/domain

- Individual and relay results are both represented where user expects meet/event completeness.
- PB/progression excludes DQ/no-time rows and preserves round/meet/date context.
- The API distinguishes individual vs relay rows explicitly.
- Source/provenance coverage is measurable.
- Suspicious parser-contaminated names are discoverable as quality warnings.

### Engineering

- Backend tests cover browser read models using deterministic fixtures.
- No production migrations unless explicitly approved after Gate 1.
- Browser list/card endpoints use aggregate SQL/read-model helper functions rather than per-row DB loops.
- Query-count instrumentation tests prove `GET /api/browser/swimmers?limit=100` and `GET /api/browser/meets/{id}` do not scale query count linearly with returned rows.
- Cardinality tests cover SNAG-shaped cases: 100-swimmer pages, 200-row event pages, mixed individual/relay event groups, and ambiguous relay identity fixtures.
- Browser GET endpoints do not mutate row counts or `updatedAt` timestamps for core tables.
- No new Alembic revision is added unless this doc is explicitly updated and approved.
- Startup remains read-only unless `SWIM_ANALYTICS_CREATE_ALL_ON_STARTUP` is explicitly set.
- No scheduler, cron, background worker, or import mutation path is added.
- Frontend browser API helpers live in one API module; pages must not reconstruct event identity or row discriminators from display strings.
- Frontend types must be covered by explicit TypeScript interfaces plus `npx tsc --noEmit`; if/when OpenAPI generation is introduced, this slice should migrate to generated schemas instead of duplicate handwritten types.

### Ops/release

- Read-only slice: no startup side effects, no hidden cron, no import mutations.
- Existing ingestion/import/delete routes remain unchanged.
- Local smoke must verify:
  - `/`
  - `/swimmers`
  - one real `/swimmers/{id}` using a high-cardinality SNAG swimmer
  - one real `/meets/{id}`
  - `/api/browser/overview`
  - `/api/browser/swimmers?limit=5`
  - `/api/browser/swimmers/{id}`
  - `/api/browser/meets/{id}`
  - `/api/browser/events?meet_id={id}&event_key={key}`
  - `/api/browser/data-quality`
- Live smoke after deploy must assert 200s, non-empty expected counts, relay presence for a relay-bearing event/swimmer, data-quality warning counts, and identical pre/post row counts for `Meet`, `Swimmer`, `Result`, `RelayResult`, `RelayLeg`, `RawDocument`, and `SourceReference`.

## Reviewer gate plan

### Gate 1 — design approval before implementation

Reviewers:

| Reviewer | Focus |
|---|---|
| Product/IA | User jobs, Meet Mobile baseline translation, route ownership, mobile/cardinality. |
| Data/domain | Swimmer/meet/event/relay semantics, PB/progression rules, data-quality warning model. |
| Engineering/ops | API seams, query efficiency, no migration unless needed, release/test plan. |

Gate 1 output must be `APPROVE` or `MUST FIX` with concrete blockers.

### Gate 2 — backend/API implementation review

After backend tests pass, reviewers check query semantics, domain correctness, and release safety.

### Gate 3 — frontend/product review

After UI implementation and local smoke, reviewers check visible experience, accessibility/mobile, and truthful source/data-quality language.

## Initial known risks

| Risk | Mitigation |
|---|---|
| Parser-contaminated swimmer names undermine trust | Expose data-quality warnings; isolate parser bug as separate focused fix if necessary. |
| Existing schema lacks explicit Session/MeetEvent | Start with read models; defer schema only if reviewers find ambiguity blocks user jobs. |
| Large event result tables become unwieldy | Event-level endpoint and progressive disclosure; avoid loading everything when not needed. |
| UI overclaims analytics | Use cautious labels: PBs, event history, source coverage; avoid unsupported coaching claims. |
| Relays get lost | Include relay rows in meet/event and swimmer history read models. |

## Gate 1 MUST-FIX resolution

Initial Gate 1 returned `MUST FIX` from Product/IA, Data/domain, and Engineering/Ops. This revision addresses those blockers as follows:

| Reviewer blocker | Resolution in this doc |
|---|---|
| “Find myself” lacks owner | Added `GET /api/browser/swimmers` as the list/typeahead/search owner with filters, pagination, aggregate count fields, warnings, and mobile-card acceptance. |
| Meet detail risks loading meet-scale tables | Changed `GET /api/browser/meets/{id}` to summary/event-index only; `GET /api/browser/events` is the paginated row-owner. |
| Event identity/direct linking underspecified | Added stable derived `event_key` contract using `meet_id + sourceEventNumber + event` fallback to `meet_id + event`, derived/raw normalization flags, and canonical frontend route `/meets/[id]/events/[eventKey]` with URL-owned pagination/filter/sort state and invalid-key behavior. |
| Relay identity can lose swimmer histories | Added relay identity semantics: primary `RelayLeg.swimmerId`, safe normalized-name fallback only when unique, ambiguity warnings, and no silent PB/progression merges. |
| Session/MeetEvent safety unclear | Explicitly states v0 event/session-ish groups are derived read models; no first-class “Session” UI/API language until schema exists. |
| Relay leg provenance not measurable | Defines relay leg source as inherited from parent `RelayResult` with `source_scope="parent_relay_result"`. |
| Data-quality endpoint unsafe | Added warning schema, types, severity, stable IDs, sample caps, and row/profile-scoped warning propagation. |
| Query efficiency too vague | Added aggregate-query/read-model helper requirement, query-count tests, and SNAG-shaped cardinality tests. |
| Read-only release safety too vague | Added no-mutation GET tests, no-migration assertion, startup read-only assertion, no scheduler/background path, and live pre/post row-count smoke. |
| Frontend drift risk | Requires centralized browser API helpers, explicit TS interfaces, `npx tsc --noEmit`, and future OpenAPI migration if introduced. |

## Current checkpoint

- Branch created.
- Live production baseline sampled.
- Gate 1 design doc created.
- Gate 1 reviewer blockers patched into explicit API/domain/test/release contracts.
- Next: focused Gate 1 re-review; only after approval, implement backend browser read models.
