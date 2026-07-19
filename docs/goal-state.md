# Swim Analytics Goal State

## Core Product Framing

Swim Analytics is not just an internal scraper/parser project.

It should become a trusted swimming-results intelligence platform with two equally important ingestion front doors:

1. **Official-source ingestion** — maintainers/agents scrape official pages such as SG Aquatics, archive all linked PDFs, and rebuild the database from source material.
2. **User-upload ingestion** — coaches, admins, clubs, or other users upload PDFs/ZIPs through the website and get the same preview, validation, import, provenance, and analytics pipeline.

The website upload/parser interface is therefore a product surface, not a temporary dev tool.

## North Star

> A searchable, source-backed, rebuildable swimming results platform that turns official PDFs and user-uploaded meet files into trusted swimmer, meet, club, and performance intelligence.

## Non-Negotiable Architecture Principle

There should be **one shared ingestion core**.

```text
input source
  → raw document record
  → classification
  → parse preview
  → validation
  → import
  → provenance/rebuild metadata
  → analytics/UI
```

The input source can be:

- official event-page scraper;
- user-uploaded PDF;
- user-uploaded ZIP;
- future API/manual/admin source.

But after intake, all sources should go through the same pipeline.

## Why This Matters

Avoid building separate logic for:

- scraper imports;
- website uploads;
- future admin uploads;
- rebuild jobs.

If these paths diverge, the platform becomes hard to trust:

- different duplicate behavior;
- inconsistent parser confidence;
- missing provenance for user uploads;
- imports that cannot be rebuilt;
- different UI behavior depending on where the file came from.

The correct model is:

```text
many front doors, one ingestion engine
```

## Source-of-Truth Model

| Layer | Role |
|---|---|
| Raw PDFs/files | Source material; preserve exactly |
| Raw document metadata | URL/upload provenance, filename, hash, category, timestamp |
| Parse artifacts | Structured parser output, confidence, diagnostics |
| Database tables | Derived/rebuildable application state |
| UI/analytics | Interpretation layer for users |

Database rows should always be traceable back to raw source documents and parser/import runs.

## User-Facing Upload Goal State

The upload flow should eventually feel like this:

```text
User uploads PDF/ZIP
  → system detects document types
  → system archives files
  → system previews parsed output
  → system shows confidence/errors/duplicates
  → user confirms import
  → results become searchable with source links
```

Example output:

```text
Detected:
- 5 overall result PDFs — importable now
- 2 start lists — archived, not imported yet
- 1 medal tally — archived, not imported yet

Preview:
- 83 events
- 2,104 individual results
- 42 relay results
- parser confidence: 97–100%
- 1 possible duplicate source file
```

## Official-Source Ingestion Goal State

The scraper/operator flow should eventually feel like this:

```text
Maintainer enters event page URL
  → system discovers all PDFs
  → system archives all PDFs by hash
  → system classifies documents
  → system previews importable result PDFs
  → maintainer approves/imports
  → future rebuild can recreate DB from archive
```

## Current Import Policy

For 56th SNAG 2026:

- Archive all PDFs.
- Import only `overall_results` for now.
- Do not import `age_group_results` as normal results; model them later as ranking/placement contexts over existing swims.
- Do not import `start_list` or `medal_tally` yet; preserve them for later features.

## Near-Term Build Goal

Build a shared ingestion foundation, then connect both front doors to it.

### Slice 1 — Shared ingestion core

- Raw document records.
- Source reference/upload records.
- Document classification.
- Parse job records.
- Parser confidence/diagnostics.
- Result provenance fields.
- Preview-before-import behavior.

### Slice 2 — Apply it to current website upload

- Uploaded files become raw documents.
- Upload preview uses parse jobs.
- Import records provenance.
- Duplicate/revision warnings are shown.

### Slice 3 — Apply it to SG Aquatics archive

- Scraped PDFs become raw documents.
- `overall_results` can be imported through the same import path.
- Rebuild command reads archived raw documents, not the live website.

### Slice 4 — User-value UI

- Meet archive.
- Searchable results.
- Swimmer profiles.
- PB detection.
- Source-linked rows.
- Basic coach/parent-friendly summaries.

## Long-Term Product Goal

Swim Analytics should support:

- official PDF library;
- user-uploaded meet files;
- searchable meet/session/event results;
- swimmer profiles and PB histories;
- club/team views;
- qualification standards and near-cut intelligence;
- coach meet recaps;
- parent-friendly explanations;
- parser confidence and correction workflows;
- rebuildable database from raw files;
- scheduled discovery and ingestion monitoring.

## Design Principle

Build for external users from the beginning, even when we use internal/operator shortcuts.

Internal workflows may be flexible, scripted, and agent-driven, but they should exercise the same core pipeline that the product exposes to users. That keeps the product honest and maintainable.
