# Implementation Slice 1 — Shared Ingestion Core

## Goal

Create a small shared ingestion foundation that both website uploads and operator/SG Aquatics archive ingestion can use.

This slice should avoid large UI/product expansion. It should add provenance and reusable ingestion primitives while preserving the current upload behavior.

## Current State

- Backend upload endpoints directly extract uploaded PDFs to temp files.
- Preview parses temp PDFs and returns parsed summary without DB writes.
- Import parses temp PDFs and writes directly to `Meet`, `Swimmer`, `Result`, `RelayResult`, `RelayLeg`.
- Existing result rows have `contentHash` but no raw-document / parse-job / ingestion-run provenance.
- SG Aquatics scraper stores raw PDFs and a manifest locally, but is not connected to backend ingestion.

## Slice Boundary

### In scope

1. Add ingestion metadata models:
   - `RawDocument`
   - `SourceReference`
   - `DocumentClassification`
   - `ParseJob`
   - `IngestionRun`
2. Add provenance columns to `Result` and `RelayResult`:
   - `sourceDocumentSha256`
   - `parseJobId`
   - `ingestionRunId`
   - `parserVersion`
   - `sourceEventNumber`
3. Add pure/helper functions for:
   - classify document by filename/text hints;
   - decide import eligibility while allowing weak/generic filenames if parser confidence passes;
   - hash/archive uploaded PDF bytes;
   - create raw document/source reference/classification records idempotently;
   - record parse jobs for import.
4. Refactor upload import to use this shared helper path while keeping upload preview read-only/non-mutating.
5. Add CLI preview for archived SG Aquatics `overall_results` folder using the same parser/classifier primitives, without importing to DB yet unless explicitly approved later.
6. Add tests before production code.

### Out of scope for this slice

- Full UI redesign.
- Age-group ranking model/import.
- Start-list parser.
- Medal-tally parser.
- Swimmer identity disambiguation.
- Public privacy model.
- Full DB rebuild command.
- Proper object storage / Git LFS decision.
- Replacing runtime clone/build deployment.

## Testing Plan

Use TDD with small vertical tests:

1. Classification test:
   - filenames map to expected categories: `overall_results`, `start_list`, `age_group_results`, `medal_tally`, `event_information`.
2. Archive/idempotency test:
   - same uploaded PDF bytes create one `RawDocument` by SHA256 and two source references only if source differs.
3. Parse-job test:
   - successful import records parser name/version, confidence, event/result counts, and artifact status.
4. Upload preview regression test:
   - preview remains non-mutating and existing response fields still exist.
5. Upload import provenance test:
   - importing a synthetic parsed meet creates result rows with sourceDocumentSha256, parseJobId, ingestionRunId, parserVersion, sourceEventNumber.
6. Import eligibility test:
   - explicit non-result categories are skipped/rejected for result import; generic filenames can still import if parser confidence passes.
7. Regression tests:
   - existing parser tests pass.

## Design Constraints

- Many front doors, one ingestion engine.
- Database remains derived/rebuildable.
- Website upload remains first-class product flow.
- User uploads and scraped files must share provenance behavior.
- Do not import non-`overall_results` categories as results.
- Keep changes small enough to review.

## Domain Assumption Guardrails

Jung Yi noted that some current result grouping/display behavior was intentionally built to reflect swimming-domain logic. Do not casually normalize or simplify those paths.

Before changing domain-display assumptions, verify the intended meaning and user impact. Examples:

- event grouping in meet detail pages;
- round labels such as `Final`, `Prelim`, `Timed Final`, `Results`;
- session/day-derived swim dates;
- age-group/finals grouping semantics;
- display-name formatting for swimmer names;
- guest/DQ/qualifier badges and placement display.

If code must encode a domain assumption, add a short comment explaining the assumption and why it is safe for the current slice. If the assumption is uncertain, document it as an open question instead of silently changing behavior.

## Open Design Choices For Review

1. Should `RawDocument.sha256` be the primary key or a unique string column with integer ID? Proposed: unique string column, integer PK for easier SQLAlchemy relationships.
2. Should preview create DB records? **Decision after role review: no for public website preview in slice 1.** Preview remains read-only/non-mutating until retention/privacy semantics are defined. Operator-only audit preview can be revisited later.
3. Where should uploaded raw PDFs be archived? Proposed initial local path via `SWIM_RAW_ARCHIVE_ROOT`, defaulting to `data/raw-documents/sha256/<first2>/<sha>.pdf`, outside committed source data.
4. Should CLI preview use backend DB or just manifest/artifact files? Proposed for slice 1: CLI preview can run read-only without DB import, but use the same classification/parser primitives.
5. How much frontend should change? Proposed: minimal; add optional provenance/diagnostic fields to API responses later, but do not redesign UI in this slice.

## Guardrails From Role Review

- Website `/api/upload/preview` must remain non-mutating: no raw-document/provenance rows and no user-visible meet/result rows.
- Website `/api/upload` is the first mutating user-facing path: it archives raw documents, records parse jobs, creates an ingestion run, and attaches provenance to imported result rows.
- Explicit non-result categories (`age_group_results`, `start_list`, `medal_tally`, `event_information`) are archived but skipped for result import. Generic filenames (`other_pdf`) may still import if HY-TEK parsing and confidence pass.
- SG Aquatics/operator archive preview should remain read-only until import is explicitly requested.
- Schema changes require a real Alembic migration; `Base.metadata.create_all()` is not enough for existing deployed DBs.
