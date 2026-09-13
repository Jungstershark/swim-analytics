# Swim Analytics — Competition Domain and Rebuild Architecture

**Status:** Directional architecture decision
**Date:** 2026-09-12
**Scope:** Competition results only. Training, Polar, Apple Health, recovery, and PPI are explicitly out of scope.

## Decision

Model the real competition first, then derive swimmer, competition, event, and team views from the same canonical performance facts.

Do not make every results PDF independently rediscover or redefine the competition. Competition identity and date range are resolved once from the best available official evidence, stored with provenance, and re-evaluated only when new or changed evidence appears.

Raw source files plus manifests and versioned curation decisions are the durable truth. PostgreSQL is a rebuildable serving projection. The current local database is development/staging state, not the future production authority.

## Real-world hierarchy

The system needs to separate five concepts that are currently compressed into `Meet`, raw event strings, and repeated dates.

```text
CompetitionEdition
  ├─ CompetitionSegment
  │    ├─ CompetitionDay
  │    │    └─ Session
  │    │         └─ EventRound
  │    │              └─ Performance
  │    └─ CompetitionEvent
  │         └─ EventDefinition
  └─ SourceDocumentSet
```

### 1. Competition edition

The umbrella real-world competition represented by an official event page.

Example:

```text
56th Singapore National Age Group Swimming Championships 2026
source page: /swimming/events/56th-snag-2026/
```

It owns:

- organizer;
- edition/title/year;
- venue when known;
- overall observed start/end bounds;
- official source page;
- source-document set;
- metadata resolution/provenance state.

### 2. Competition segment

A named competition part whose day numbering and date range are internally coherent.

For the current SNAG corpus:

```text
Competition: 56th SNAG 2026
  Segment: Juniors — 13 to 15 March 2026
  Segment: Seniors — 17 to 22 March 2026
```

This distinction matters because both segments can have `Day 1` and `Session 1`. Deriving a race date from the umbrella start date would be wrong for the Seniors segment.

A one-part competition simply has one default segment.

### 3. Competition day and session

`CompetitionDay` is a calendar date within a segment. `Session` is the scheduled block within that day.

Example:

```text
Seniors / Day 1 / Session 1 / 17 March 2026
Seniors / Day 1 / Session 2 / 17 March 2026
Seniors / Day 6 / Session 12 / 22 March 2026
```

The current result sheets already provide enough evidence to make this mapping:

- the official header states `56th SNAG Seniors - 17/3/2026 to 22/3/2026`;
- each sheet states `Results-Day N Session N`;
- filenames and the 46-document competition manifest independently carry day/session labels.

The PDF generation timestamp must not be treated as the race date. For example, a Day 1 result sheet can be generated on a later date.

### 4. Event definition, competition event, and round

Separate stable swimming discipline from source-specific event presentation.

`EventDefinition` is reusable across competitions:

```text
50 m butterfly / long course
200 m individual medley / long course
4 × 50 m freestyle relay / long course
```

Use explicit fields rather than a display string:

- distance;
- stroke;
- course;
- individual/relay;
- relay leg count and leg distance where applicable;
- sex/category dimensions where they are genuinely part of the comparable event definition.

`CompetitionEvent` preserves competition-specific meaning:

- competition segment;
- source event number;
- official event label;
- eligibility/age-group label;
- link to `EventDefinition`;
- normalization status and evidence.

`EventRound` represents prelim, semifinal, final, timed final, swim-off, or other stage and belongs to a session.

This lets the system preserve official labels while comparing like-for-like performances. Jung Yi's `Men 15 & Over 50 LC Meter Butterfly` prelim and `Men 50 LC Meter Butterfly` final can remain distinct source labels but map to the same canonical 50 m butterfly discipline and competition progression.

### 5. Performance

One actual swim by one athlete or relay team in one event round.

Store:

- athlete/team identity;
- event round;
- official status: `finished`, `dq`, `ns`, `dns`, `dnf`, `scratched`, `unknown`;
- time as integer source precision, preferably centiseconds for HY-TEK results;
- raw display time;
- placement within the specific round/context;
- seed time and reaction/splits with the same integer-plus-raw-text discipline;
- source row/page/block locator where practical;
- source document, parse run, and import batch foreign keys.

Never use `0` as missing time or missing identity. Never store `NaN`/infinity. A missing date, time, place, athlete match, or status remains null/unknown with a quality state.

## Competition metadata resolution

### Resolve once; verify on evidence change

Competition metadata should have a resolver, not repeated ad hoc parsing during every import.

```text
source evidence
  → metadata assertions
  → conflict checks
  → resolved competition/segment metadata
```

Recommended source priority:

1. official competition information/program document;
2. official event page structured text;
3. consistent result-sheet headers across multiple sessions;
4. filename/day/session metadata from the archived manifest;
5. explicit curator decision.

A lower-priority source can corroborate the resolved value but should not overwrite it silently.

Persist the resolution evidence:

- `value`;
- `resolution_status`: `verified`, `derived`, `conflicting`, `unknown`;
- source document/page/text or source page snapshot;
- resolver version;
- resolved timestamp;
- optional curator decision ID.

### When to re-check

Do not re-read every unchanged PDF on every database build.

- Hash source pages/documents at discovery time.
- Reuse existing parse and metadata artifacts when `document_sha256 + parser_version + resolver_version` are unchanged.
- Re-run resolution only when a source hash changes, a new source appears, the resolver version changes, or an operator records a correction.
- Periodic monitoring checks availability/hash, not all historical parsing logic.

The system may re-verify cheaply, but it should not continually mutate an already resolved competition date from repeated copies of the same evidence.

## Missing and problematic source policy

A missing source file is not automatically a data error and must never force fabricated values.

Distinguish:

```text
not yet published
published and archived
currently unavailable upstream, archived locally
currently unavailable upstream, no local copy
fetch failed / response incomplete
source explicitly corrected or replaced
```

Rules:

1. Upstream absence is not deletion intent.
2. One failed or empty scrape changes no historical availability state.
3. A result sheet may be unavailable while the competition and other sessions remain valid.
4. If day/session can be resolved from verified competition metadata plus an archived manifest, use that derivation and label it `derived`.
5. If the date truly cannot be resolved, store it as unknown. Import may continue when the core performance is valid, but date-dependent analytics must exclude or visibly label it.
6. Never substitute `datetime.now()` for unknown competition evidence.
7. A corrected PDF at the same URL becomes a new immutable source revision identified by hash; it does not overwrite the old bytes.

## Source and derived-data layers

### Immutable source layer

`CompetitionSourcePageSnapshot`

- source URL;
- fetched timestamp;
- HTTP outcome;
- content hash;
- extraction status.

`RawDocument`

- SHA-256 identity;
- private object-storage key;
- byte size and content type;
- original filename;
- first/last seen;
- validity state.

`SourceReference`

- competition/source page;
- direct URL;
- observed filename/category;
- source authority: official publication, user upload, secondary source;
- source revision relationship.

`CompetitionDocumentManifest`

- competition ID;
- expected/observed documents;
- category;
- segment/day/session hints;
- source URL and hash;
- completeness state.

### Parse and decision layer

`ParseArtifact`

- raw document ID;
- parser name/version;
- structured output location/hash;
- diagnostics and anomaly counts;
- confidence dimensions;
- status.

`MetadataAssertion`

- subject: competition, segment, day, session, or event;
- field/value;
- source locator;
- extraction method/version;
- confidence.

`CurationDecision`

- versioned competition binding, event normalization, athlete merge/split, source classification, or correction;
- previous/new value;
- reason and actor;
- created timestamp;
- never destructively edits raw evidence.

`ImportBatch`

- exact source document and parse-artifact hashes;
- schema/importer version;
- validation report;
- all-or-nothing promotion status;
- deterministic counts.

### Canonical domain layer

- `CompetitionEdition`
- `CompetitionSegment`
- `CompetitionDay`
- `Session`
- `EventDefinition`
- `CompetitionEvent`
- `EventRound`
- `Athlete`
- `AthleteAlias`
- `Team`
- `TeamAlias`
- `Performance`
- `RelayPerformance` and `RelayLegPerformance`
- `PlacementContext` for age-group/final/medal/points views over the same performance

## Views are projections, not separate stores

### Competition view

Query by competition ID:

```text
competition
  → segment
  → day
  → session
  → event/round
  → result rows
```

It should answer:

- what happened on each competition day/session;
- which documents are present, missing, changed, or held;
- events, rounds, results, placements, DQ/no-show status;
- whether the competition import is complete and source-verifiable.

### Swimmer view

Query canonical `athlete_id`, then join the same `Performance` rows through event/session/competition.

It should answer:

- performances across competitions;
- fastest in the declared corpus;
- prelim-to-final and seed-to-result changes;
- target-event history by canonical discipline;
- source coverage and identity confidence.

The swimmer page must not own or duplicate race facts. It is a read model over competition performances.

### Event/discipline view

Query `event_definition_id` across competitions. This supports longitudinal comparison without grouping by raw labels.

### Team view

Join performances through team membership/representation as observed at that competition. This comes later because club identity and transfers require explicit modeling.

## Rebuild contract

The production database must be disposable and reproducible.

The actual rebuild input is not raw PDFs alone. It is:

```text
immutable source files
+ competition manifests/source snapshots
+ parser/resolver/importer versions
+ versioned curation decisions
+ schema migrations
```

Raw PDFs are necessary but not sufficient: manual athlete merges, competition bindings, event normalization, and accepted corrections must also replay deterministically.

Required command shape:

```text
create empty database
→ migrate to head
→ register competition manifests
→ verify all referenced raw hashes
→ reuse/regenerate parse artifacts
→ resolve competition/segment/day/session metadata
→ apply versioned curation decisions
→ validate complete import batches
→ promote canonical facts
→ build/cache read projections
→ compare logical counts and invariants
```

Rebuild acceptance:

- empty PostgreSQL migrates successfully;
- every manifest raw hash resolves;
- repeated rebuild produces identical canonical IDs/keys or stable public identifiers;
- immediate rerun adds zero duplicates;
- partially invalid competition packages promote nothing;
- known same-time swims on different days remain distinct;
- unknown dates remain unknown;
- competition and swimmer projections agree on counts;
- stored source locators can explain every public performance.

## Local and cloud deployment boundary

### Local

Use local PostgreSQL only for development, parser work, disposable rebuilds, and staging verification. It must run the same migrations and constraints as production but is not production state.

### Cloud production

```text
Official sources / authorized uploads
        ↓
Private immutable object storage
        ↓
Authenticated ingestion worker + validation/staging
        ↓
Managed PostgreSQL canonical serving database
        ↓
Public read API / cached frontend

Private admin API and correction UI remain authenticated.
```

Production requirements before public launch:

- managed PostgreSQL with point-in-time recovery or equivalent backups;
- private versioned object storage for raw documents and parse artifacts;
- authenticated operator/admin mutations;
- anonymous public reads only for explicitly approved official-result fields;
- rate limiting and abuse protection;
- no direct public database access;
- migration and rebuild gates in CI;
- immutable application releases;
- source attribution, privacy policy, and explicit handling of minors' official results;
- neutral branding unless formal SSA authorization exists.

Cloud migration becomes an import of reproducible state, not a one-off copy of the current local database.

## Migration from the current schema

1. Freeze current writes and preserve the local raw library.
2. Canonicalize duplicate raw-library folders by SHA without deleting source references.
3. Create `CompetitionEdition` for the 56th SNAG 2026 umbrella event.
4. Convert current Juniors and Seniors `Meet` rows into `CompetitionSegment` records.
5. Create days/sessions from the verified segment ranges and manifest labels.
6. Link each of the 17 imported overall-result documents to its segment/day/session.
7. Add explicit result status and integer duration fields.
8. Repair relay parsing and event/round normalization against source fixtures.
9. Build canonical event definitions and competition-event mappings.
10. Rebuild into a new empty PostgreSQL database; do not mutate the current production-shaped tables in place as the first proof.
11. Reconcile competition, session, event, athlete, individual, relay, and status counts against the raw package.
12. Cut the frontend to new competition/swimmer read contracts only after parity and browser verification.

## Near-term implementation sequence

### Slice A — Competition package and metadata resolver

- `CompetitionEdition`, `CompetitionSegment`, day/session models;
- document manifest registration;
- metadata assertions and resolution status;
- no fabricated dates;
- changed-hash re-resolution only.

### Slice B — Canonical performance model

- canonical event definition;
- competition event and row-level round;
- explicit result status;
- integer times/splits;
- relational provenance constraints.

### Slice C — Deterministic rebuild

- repair fresh migrations;
- validate complete package before promotion;
- replay curation decisions;
- clean rebuild and immediate rerun gates.

### Slice D — Competition and swimmer read models

- `/competitions` archive;
- competition → segment → day/session → event results;
- swimmer history built from the same performances;
- event/discipline history;
- mobile-first cards and URL-owned filters.

### Slice E — Cloud production cutover

- object storage;
- managed PostgreSQL;
- private worker/admin plane;
- public read plane;
- backups, restore, rate limiting, observability, and launch policy.

## Explicit non-goals

- Today/training-session workflows;
- Apple Health, Polar, HRV, sleep, or recovery;
- AI coaching or physiological predictions;
- meet entries/payments/management;
- importing alternate age-group/medal documents as duplicate performance rows.

This repository remains exclusively a swimming competition-results and analytics system.
