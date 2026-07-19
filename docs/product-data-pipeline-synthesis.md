# Swim Analytics — Product + Data Pipeline Synthesis

## Thesis

Swim Analytics should become the searchable, permanent, Singapore-focused swimming results intelligence layer on top of official result PDFs.

Do not start by competing with meet-management/live-results products. Start by solving the pain that official results are fragmented across event pages, PDFs, sessions, and years.

## Core Principle

Raw PDFs are source of truth. Postgres is derived/rebuildable state.

```text
source page → discover → download all PDFs → classify/hash/archive → parse selected categories → validate → import → rebuild DB
```

## Current 56th SNAG 2026 Findings

Full raw library: `raw-data/sg-aquatics/56th-snag-2026-full/`

| Category | Count | Use |
|---|---:|---|
| event_information | 1 | rules/schedule/reference metadata |
| start_list | 17 | future seed/heat/lane/DNS analysis |
| overall_results | 17 | v0 canonical swim-performance import |
| age_group_results | 6 | future placement/ranking annotations, not duplicate swims |
| medal_tally | 5 | future aggregate validation/team summaries |

Overall result parser preview:

| Metric | Count |
|---|---:|
| files | 17 |
| event blocks | 355 |
| individual results | 10,905 |
| relay results | 348 |
| parser confidence | 100% each |

## Important Data-Model Decision

Use `overall_results` as canonical source for actual swim performances.

Do **not** import `age_group_results` as normal results. They represent official age-group ranking/placement views over the same senior finals swims. For day 1, the domain agent found 284/284 rows matched between overall finals and age-group finals by event number + athlete/team + time, but placements/event groupings differed.

The model should eventually split:

- `SwimResult`: one row per actual swim/performance.
- `ResultRanking` / `PlacementContext`: one-to-many official ranking contexts for that swim, e.g. race-section placement, age-group medal placement, team points context.

## Product Direction

Early wedge:

1. official PDF archive;
2. parsed overall results;
3. swimmer search;
4. swimmer profiles/PBs;
5. source-linked result rows;
6. basic standards/near-qualifier layer;
7. coach meet-recap reports.

Avoid early:

- full meet management;
- entries/declarations/payments;
- complex social features;
- public national rankings without privacy/positioning thinking;
- overbuilt predictive analytics.

## Roles / Agent Team

| Role | Responsibility |
|---|---|
| Source-discovery agent | find/monitor event pages and new PDFs |
| Ingestion-maintenance agent | scraper/downloader/classifier/parser/rebuild command |
| Data QA agent | parser regression, duplicates, confidence, sampled PDF comparisons |
| Domain analyst | finals/prelims/age groups/relays/DQ/DNS/team normalization |
| Product/UX agent | swimmer/parent/coach/admin flows and UI acceptance criteria |
| Market/comparable-products agent | Meet Mobile, SwimCloud, SwimPhone, SwimTopia, local gaps |
| Ops/SRE agent | Sharklet health, PVC/backups, Flux, ingress, rebuild drills |
| Synthesis/product lead | sequence roadmap and prevent feature sprawl |

## Upload Interface Is Also Product, Not Just Internal Tooling

The existing website parser/upload flow remains important. It should not be treated as irrelevant just because internal operators can scrape/code directly.

There are two complementary ingestion paths:

| Path | Primary user | Purpose |
|---|---|---|
| Operator/source-page ingestion | project maintainers / agents | scrape official pages, archive PDFs, rebuild database |
| User upload ingestion | coaches / admins / external users | upload meet PDFs or ZIPs from their side and get parsed/imported results |

Both paths should share the same underlying ingestion engine:

```text
input source → raw document record → parse preview → validation → import → provenance/rebuild metadata
```

The difference is the front door, not the core pipeline.

So the user-facing upload flow should eventually support:

- preview before import;
- parser confidence;
- clear file/category detection;
- duplicate/revision warnings;
- source/provenance tracking;
- admin-friendly error messages;
- safe import into the same rebuildable data model.

## Recommended Next Implementation Slice

Build the ingestion foundation before importing more data, while keeping both future upload and operator scrape flows in mind:

1. Track raw documents and source references.
2. Track parse jobs and parser confidence.
3. Add provenance fields to derived result rows.
4. Implement a preview/import path for `overall_results` only.
5. Make that path reusable by both:
   - CLI/operator ingestion from archived SG Aquatics PDFs;
   - website upload/preview/import from user-provided PDFs or ZIPs.
6. Add idempotency/rebuild checks.
7. Then import 56th SNAG 2026 overall results.

## Open Decisions

- Where should raw PDFs live durably: Git LFS, Sharklet PVC/NAS, object-store-like local path, or repo only for manifests?
- Should v0 expose public swimmer search, or keep it private/internal until privacy stance is clearer?
- Should default placement shown to users be race placement, age-group medal placement, or both?
- How should guest/foreign swimmers and local-affiliate eligibility be represented?
- When a source PDF changes with same filename but different hash, should UI show both versions or only latest with revision history?
