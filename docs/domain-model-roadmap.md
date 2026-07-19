# Swim Analytics — Domain Model Roadmap

## Why This Exists

Swim Analytics needs to scale beyond “parse a PDF into rows.” The product should have stable concepts for:

- swimmers / athlete identities;
- competitions / meets;
- sessions and events;
- actual swim performances;
- official ranking/placement contexts;
- teams/clubs/eligibility;
- raw source documents and provenance.

This document records what the current implementation already supports, what assumptions it currently makes, and what should come next so future features are easy to add instead of forcing rewrites.

## Current Model Shape

Current core domain tables:

| Concept | Current table/model | Notes |
|---|---|---|
| Swimmer | `Swimmer` | Currently a simple parsed identity: `name`, `age`, `team`. Good for search/profile v0, but not yet a robust athlete identity model. |
| Competition / meet | `Meet` | Represents a parsed meet/competition with name, dates, location, parser format. |
| Individual swim | `Result` | Current canonical individual performance row from `overall_results`. |
| Relay swim | `RelayResult` + `RelayLeg` | Captures relay team result and swimmer legs. |
| Raw source file | `RawDocument` | Content-addressed source file metadata. |
| Source/upload reference | `SourceReference` | Tracks where/how raw file entered the system. |
| Document class | `DocumentClassification` | Classifies PDF as `overall_results`, `start_list`, `age_group_results`, etc. |
| Parser execution | `ParseJob` | Parser confidence/counts/diagnostics for a raw document. |
| Import batch | `IngestionRun` | Mutating import/rebuild run metadata. |

This is enough for a trustworthy v0, but not the full long-term domain model.

## Important Current Assumptions

### 1. `Swimmer` is currently parsed-person, not guaranteed real-world athlete identity

Today, `Swimmer` is keyed by parsed name/team/age behavior during import. This is okay for v0 search and profiles, but it should not be treated as a perfect permanent identity.

Future issue examples:

- same swimmer appears with slightly different name formatting;
- same name across different swimmers;
- team/club changes over time;
- age changes by meet/date;
- relay legs may include names before matching a canonical swimmer.

Do not overbuild identity resolution now, but do not assume it is solved.

Future likely model:

```text
AthleteIdentity / SwimmerProfile
  ├─ parsed swimmer aliases
  ├─ clubs over time
  ├─ date-of-birth / age evidence if available
  └─ manual merge/split decisions
```

### 2. `Meet` is current competition object, but may need richer hierarchy

Today, `Meet` covers the competition/meet concept.

Future competitions may need:

```text
Competition / Meet
  ├─ sessions / days
  ├─ source event page
  ├─ host organization
  ├─ venue
  ├─ course: LC/SC, if reliably available
  └─ document set / source library
```

Do not rename `Meet` casually. In swimming products, “meet” is natural, but “competition” may be clearer for external/business language. For now, treat `Meet` as the canonical competition table and document future expansion instead of changing names prematurely.

### 3. `Result` is an actual swim performance, not every official placement view

Current v0 policy:

- import `overall_results` into `Result` / `RelayResult`;
- archive `age_group_results`, but do not import them as duplicate results.

Reason: age-group result PDFs can describe the same underlying swims with different placement/ranking contexts.

Future likely model:

```text
SwimResult / Result
  └─ ResultRanking / PlacementContext
       ├─ context_type: race, age_group, medal, team_points, qualification
       ├─ placement
       ├─ eligibility/local/guest status
       └─ sourceDocumentSha256 / parseJobId
```

This avoids forcing one row to mean both “actual swim” and “all official ways that swim was ranked.”

### 4. Display grouping logic is product/domain behavior, not incidental UI

Existing grouping/display decisions may encode domain assumptions. Do not casually refactor them away.

Examples to preserve or verify before changing:

- event grouping in meet detail;
- round ordering and labels (`Final`, `Prelim`, `Timed Final`, `Results`);
- session/day-derived swim dates;
- DQ/guest/qualifier badges;
- placement display;
- swimmer display-name formatting.

If a grouping rule is uncertain, ask Jung Yi or record it as an open domain decision.

## What The Current Ingestion Slice Gives Us

The shared ingestion/provenance slice does **not** solve every domain concept, but it gives a safe foundation:

```text
source PDF/upload
  → RawDocument
  → SourceReference
  → DocumentClassification
  → ParseJob
  → IngestionRun
  → Result / RelayResult with provenance
```

This makes future scaling easier because:

- every imported performance can point back to a raw source;
- future models can add ranking/placement views without losing source traceability;
- official scrapes and user uploads can converge on one ingestion path;
- rebuild and correction workflows can be explained.

## Recommended Next Domain Objects

Do not implement all of these immediately. Use this as staged direction.

### Near-term: minimal additions

| Object | Why | When |
|---|---|---|
| `SourceSite` + `SourceRule` | Configures official sources, adapters, cadence, active/stale windows, categories, and import policy. | Before hidden cron; source monitoring should be visible in platform UI. |
| `SourceEvent` / `SourceCompetitionPage` | Represents an official event page and its discovered document set. | Before SG Aquatics automated monitoring/rebuild. |
| `RawDocumentSet` or source-page manifest | Groups PDFs from one competition/event page. | Before multi-meet scraper scaling. |
| `MonitorRun` / `SourceEventSnapshot` | Records each scrape/check result, added/changed/removed documents, and action-required state. | Before scheduled automation or frontend ingestion dashboard. |
| `ImportPolicy` / category gate metadata | Explains why some files are importable vs archive-only. | As importer grows beyond upload path. |

### Mid-term: domain-normalized swimming model

| Object | Why |
|---|---|
| `Session` | Day/session grouping, source file/session mapping, schedule context. |
| `MeetEvent` | Normalize event number/name/stroke/distance/gender/age/course instead of storing event as raw string only. |
| `AthleteIdentity` / `SwimmerProfile` | Merge aliases and handle long-term swimmer history. |
| `Club` / `Team` | Normalize teams/clubs and handle team name variants. |
| `ResultRanking` / `PlacementContext` | Model age-group, medal, race, points, and eligibility rankings separately from actual swim performance. |

### Later: product intelligence layer

| Object / Derived view | Why |
|---|---|
| Personal bests | Swimmer profiles and progression. |
| Qualification standards | Near-cut and qualifier intelligence. |
| Seed-vs-result analysis | Requires start lists. |
| Team/club dashboards | Requires club normalization and ranking contexts. |
| Correction/audit workflow | External-user trust and admin quality. |

## Recommended Sequence From Here

### Step 1 — Finish and stabilize ingestion slice

- Keep current branch focused on provenance/upload behavior.
- Do not add full swimmer identity or competition hierarchy in this branch.
- Commit this as a foundation once reviewed.

### Step 2 — Add SG Aquatics archive path through same core

- Introduce source-page/document-set concept if needed.
- Archive every file.
- Preview/import only `overall_results`.
- Keep age-group/start-list/medal files archive-only.

### Step 3 — Import 56th SNAG 2026 overall results with provenance

- Validate counts against manifest/parser preview.
- Ensure results have `sourceDocumentSha256`, `parseJobId`, and `ingestionRunId`.
- Preserve current display grouping.

### Step 4 — Add domain normalization carefully

Priority order:

1. `MeetEvent` normalization from event strings.
2. `Session` model from parsed session/day data.
3. `AthleteIdentity`/alias strategy.
4. `Club`/team normalization.
5. `ResultRanking` / `PlacementContext` for age-group/medal views.

## Open Questions For Jung Yi

These should be decided before implementing deeper domain models:

1. Should the user-facing language say **Meet**, **Competition**, or both?
2. What should be the default placement shown in search/profile views?
   - race/final placement;
   - age-group placement;
   - both, once modeled.
3. How important is club/team history versus swimmer history in the first useful product?
4. Should swimmer identity merges be manual-admin-first rather than automatic?
5. Should public views expose all swimmers immediately, or should we keep the early app private/internal until privacy positioning is clearer?

## Rule For Future Implementation

When changing domain model or display behavior:

1. Preserve current behavior unless the change is explicit.
2. Document any domain assumption in code or docs.
3. Add a focused test for the assumption.
4. Use role-agent review for data/domain + product/UX + ops if the change affects imported meaning, grouping, or user-visible interpretation.
