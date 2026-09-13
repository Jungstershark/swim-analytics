# Swim Analytics — Independent Engineering and Product Relook

**Date:** 2026-09-12
**Reviewed source:** `25040df9e9b397057ce612c5f912b165925532e5` on `main`
**Live product:** `http://swim.sharklet.lan`
**Review mode:** Read-only product/code/runtime audit. No application code or live data was changed.

## Executive decision

Swim Analytics is a credible **searchable meet-results prototype**, but it is not yet a trusted analytics product or a safe operator-ready ingestion platform.

The strongest pieces are already present: HY-TEK parsing, a useful browser read model, swimmer/meet/event deep links, upload preview, provenance columns, migrations, private Sharklet deployment, and a clean visual foundation. The weak point is not a lack of more screens. It is that the product currently claims more trust than the deployed evidence system can support.

**Director recommendation:** pause new analytics features for one trust-and-domain-normalization cycle. Then grow the source corpus and ship a personal target-event experience. Do not build prediction, training advice, recovery analytics, social features, or broad public rankings yet.

The durable product wedge should be:

> **The source-backed Singapore swimming competition record, with a personal target-event view that tells an athlete what happened, how it compares with their recorded history, and how far they are from a versioned qualification standard.**

The archive/data pipeline is the acquisition moat. The personal target-event experience is the retention product.

The intended production target is now a public cloud service. The current local/Sharklet database should therefore be treated as disposable development/staging state, not migrated as unquestioned production truth. The cloud database must be rebuildable from immutable source files, competition manifests, parser/resolver versions, and versioned curation decisions. The competition-only domain and rebuild contract are specified in `docs/competition-domain-and-rebuild-architecture.md`.

## Release-candidate status

The trust slice is now integrated in the working tree and is being released to the private Sharklet deployment. The historical findings below remain the evidence for prioritization.

**Implemented in the current candidate**

- Added `CompetitionEdition → CompetitionSegment → CompetitionDay → CompetitionSession`, with nullable session links on individual and relay performances while preserving legacy API contracts.
- Added a manifest-authoritative importer that confines file paths, binds SHA verification to the exact parsed bytes, canonicalizes HTTP(S) source identity once, validates the complete package, and promotes relational rows transactionally.
- Repaired zero-to-head Alembic bootstrap and verified fresh and deployed-revision upgrade/downgrade/re-upgrade behavior on SQLite and PostgreSQL.
- Made performance identity session/date/source-event/status aware and database-unique for both individual and relay results.
- Preserved official result statuses and row-level rounds through parser, relational model, API, and UI; relay distance now means total event distance and relay count remains separate.
- Made metadata conflicts sticky and critical confidence checks fail closed; non-positive or out-of-range day/session evidence cannot fabricate a race date.
- Quarantined malformed relay-leg evidence instead of creating false swimmers. Parent relay results remain available with explicit `complete | partial | unavailable` leg-parse status and browser warnings.
- Made preview and confirmation share one complete-bundle preflight; confirmation consumes the prepared parser output exactly once; replacement rolls back all relational and newly created archive state after any later failure.
- Added request, PDF-magic, ZIP member-count, expanded-size, and compression-ratio limits.
- Made legacy attachment require full source-evidence equality, including exact date missingness, and reject stale meet date ranges.
- Added an athlete-first longitudinal view organized as `LCM/SCM → canonical event → chronological competition performances`, with a course-specific fastest recorded time and source-backed split visibility.

**Release gates**

- Backend full suite, frontend typecheck/production build, PostgreSQL clone migration, live-data import, and browser evidence are recorded from the final release process rather than inferred from this historical review.
- Clean 17-document rebuild target: 1 edition, 2 segments, 9 days, 17 sessions, 10,905 individual results, 348 relay results, and 11,253 performances. Immediate rerun must insert 0.
- Corpus documents remain separated into archived, parse-previewed, and safe-to-import states; historical bundles with aggregate/alternate-view or parser ambiguity are held rather than bulk promoted.

**Still blocks a public or multi-user release**

1. fail-closed authentication/authorization for upload, replacement, deletion, correction, and source operations;
2. off-node restore verification for source documents and PostgreSQL backups;
3. a real correction/reprocess queue and versioned curation decisions for held historical bundles;
4. immutable application images, noninteractive lint/tests, generated API contracts, observability, rate limits, and SQL-level pagination;
5. a preview token/hash contract if browser preview and confirmation become separate requests in a public multi-user deployment.

The private Sharklet release deliberately ships the trusted longitudinal slice while keeping unsafe historical imports held. It does not claim that every archived result PDF has entered the relational serving database.

## What was verified

### Repository and checks

- Repository was clean on `main`, tracking `origin/main` before this report was created.
- Backend: **86 passed, 29 skipped, 2 warnings** in 2.53s.
  - Every skipped test was a real-PDF parser integration test with reason `Test PDF not found`.
  - The source PDFs exist elsewhere under `raw-data/`, so the integration fixture path is stale rather than the evidence being unavailable.
- Frontend TypeScript: `npx tsc --noEmit` passed.
- Frontend production build: `npm run build` passed.
- Frontend lint: `npm run lint` failed by opening Next.js's interactive ESLint setup prompt; lint is not a usable CI gate.
- There is one TypeScript parser test file, but `package.json` has no test runner or `test` script. There are no component, route, or browser regression tests.
- There is no generated OpenAPI client or contract freshness check; `frontend/lib/api.ts` is a large handwritten mirror of backend schemas.

### Live runtime

The deployed API reported:

- 2 meets
- 1,953 swimmer records
- 10,649 individual results
- 348 relay results
- 1,367 relay legs
- 17 raw-document rows
- 17 source references
- 51 parse jobs
- 3 ingestion runs
- 0 source events
- 0 monitor runs

The live frontend and backend both contained source commit `25040df9e9b397057ce612c5f912b165925532e5` at review time.

### Browser coverage

Desktop routes inspected:

- `/`
- `/swimmers`, including search
- `/swimmers/1879` for Ong, Jung Yi
- `/meets/2`
- `/meets/2/events/meet-2-src-501-men-15-over-50-lc-meter-butterfly`
- `/results`, including the source-evidence disclosure
- `/upload`
- `/admin/sources`
- invalid swimmer detail `/swimmers/999999`

Phone-width screenshots at 390 × 844 were inspected for the dashboard, swimmers, Jung Yi's profile, meet detail, event detail, global results, upload, and Sources.

The normal dashboard route produced no JavaScript console errors.

## What is good

1. **The browser hierarchy is understandable on desktop.** Meet → event → result and swimmer → event history are real, navigable information paths rather than disconnected mock screens.
2. **Search is useful now.** Jung Yi can be found immediately and has a stable profile route.
3. **Provenance is modeled at the row level.** Live individual and relay rows are populated with source-document hashes and parse-job/run IDs.
4. **The upload flow has the right broad choreography.** Select → preview → inspect counts/confidence → confirm is better than blind ingestion.
5. **The read model acknowledges derivation.** Event keys and normalization status avoid pretending raw event strings are already fully normalized domain objects.
6. **Entity-resolution hardening is visible in the latest commit history.** The implementation is actively addressing ambiguous identity matching rather than using unsafe name-only merges.
7. **The Sharklet service is healthy and private-first.** The app is reachable through private `.lan` ingress, workloads have main-container resource requests/limits, and PostgreSQL is pinned to apex NVMe.
8. **Missing values are not rendered as numeric zero.** The main failure is lost status semantics, not false zeros.

## Release blockers and major engineering gaps

### P0. The deployed source archive is not durable — and is already missing

**Evidence**

- `backend/app/main.py:92` defaults raw storage to `data/raw-documents`.
- All 17 live `RawDocument.storagePath` rows point under that relative directory.
- Inspection inside the live backend pod found neither `/workspace/backend/data/raw-documents` nor `/workspace/backend/data/raw-archive`; file count was zero.
- The backend Deployment mounts only a source-code `emptyDir`; there is no raw-document PVC or object-store mount.
- Local checkout contains 75 PDFs, but `git ls-files` reports **0 tracked raw PDFs** and only 3 tracked manifests.

**Impact**

Database rows claim source provenance, but the referenced bytes cannot be opened or hash-verified in the deployed system. A pod replacement destroys newly uploaded source files. This violates the project's core “raw PDFs are source of truth; Postgres is rebuildable” promise.

**Required outcome**

- Put raw documents on an apex-backed PVC or content-addressed object store.
- Copy/reconcile the existing corpus into it.
- Verify every `RawDocument` row resolves to bytes whose SHA-256 matches the row.
- Add a restore-tested backup outside the same PVC/node failure domain.
- Expose an authorized source-document retrieval/audit path.

### P0. Parser confidence reports 100% while accepting corrupted relay identities

A fresh scan of all 17 canonical SNAG overall-results PDFs produced:

- 355 event blocks
- 10,905 individual rows
- 348 relay rows
- 1,367 relay-leg rows
- **13 suspicious relay-leg rows** containing timing/ordinal fragments in names
- **12 invalid relay-leg ages**, including ages 1, 3, and 4
- confidence **1.0 / passed for every PDF**

Examples already persisted in production include:

- `Abdul Khair, Daria Suhayr3 W) r1:02.53 Mark, Ivan Royston`
- `Verwijmeren, Luuk Pieter3 M)` with age 1
- `Davidovich Weisberg, Me3r)o rn:` with age 1

`backend/app/parsers/hytek.py:812-850` scores broad document-level checks but does not validate relay-leg identity/age structure. The real-PDF regression tests that would check reasonable ages are currently all skipped.

**Impact**

Corrupted relay legs create false swimmer identities and inflate swimmer counts. “100% confidence” is materially misleading.

**Required outcome**

- Repair relay-leg parsing using regression fixtures for every reproduced corrupted line.
- Validate athlete age ranges and suspicious tokens in both individual and relay rows.
- Make anomaly checks reduce confidence or quarantine the document; do not import while still showing 100%.
- Rebuild from preserved source after repair, then prove no suspicious identity rows and no unreasonable ages.

### P0. Round, status, and relay-distance meaning can be corrupted

The parser recognizes `NS`, `DNS`, `DNF`, and `SCR` through `ParsedResult.is_ns`, but `Result` has only `time`, `isDQ`, and DQ fields. The status itself is not persisted.

Fresh parsing counted 241 non-swim status rows. The live database contains 227 rows where `time IS NULL` and `isDQ = false`. Those rows are indistinguishable from missing/failed time extraction in the API/UI.

Independent code/probe review also found:

- one mutable event-level `time_type` can cause mixed prelim/final rows to persist under the same round;
- relay split distances use `event.distance // split_count`. HY-TEK `4x50` is parsed with event distance 50, which can produce labels such as 12 m, 24 m, 36 m, and 48 m;
- duplicate relay-leg numbers are not rejected.

**Required outcome**

Add an explicit result status enum such as `finished | dq | ns | dns | dnf | scratched | unknown`, migrate/import it, and render it consistently. Make round a row-level source fact, normalize total relay distance separately from leg distance, constrain unique leg positions, and test mixed-round documents. Unknown and absent evidence must remain distinct from an official no-show.

### P0. Mutating and operator APIs have no authentication

- OpenAPI has no security scheme and no operation security on upload or source-monitor actions.
- An unauthenticated empty `POST /api/upload` reached request validation and returned 422 rather than 401/403.
- An unauthenticated `POST /api/admin/source-rules/999999/run-discovery-preview` reached the application and returned the domain error `SourceRule not found: 999999`.
- Destructive meet/result deletion routes have no auth dependency; an independent disposable-database probe confirmed unauthenticated deletion succeeds.
- Upload and Sources are exposed in ordinary primary navigation.
- Replace mode can delete all existing results for a meet before import.

Private LAN/Tailscale reachability reduces exposure; it does not authorize mutation.

**Required outcome**

- Decide viewer, contributor, and operator roles.
- Require fail-closed server-side authorization for upload, replace/rebuild, correction, and source monitoring.
- Hide operator destinations from viewer navigation.
- Keep public/read policy explicit before any broader exposure, especially because the corpus contains minors' names, ages, clubs, and results.

### P0. Upload trust boundaries are incomplete

- `backend/app/main.py:456` reads the entire upload into memory.
- ZIP members are read fully with no compressed-size, expanded-size, member-count, or ratio limits.
- File type is accepted by filename extension; PDF magic is not validated before parsing/archival.
- The frontend performs no size preflight.
- Preview explicitly creates no archival/database record (`main.py:333-336`), and confirm uploads and reparses the file independently. Confirmation is not bound to a server-side preview token/hash.
- Result deduplication uses select-then-insert and `contentHash` is indexed but not unique, so concurrent imports are not atomically idempotent.
- The content hash omits `swimDate` and `sourceEventNumber`; otherwise identical swims on separate days or repeated same-label source events can collapse as duplicates.
- A multi-PDF preview reports only the **last successfully parsed document's** confidence while combining rows from the full bundle.
- A multi-meet ZIP creates only the first `Meet` and then attaches later PDFs to it.
- Per-file parse failures are collected as warnings and the bundle still commits. In replace mode, this allows a partial bundle to delete the previous complete meet and commit only the successfully parsed subset.
- A post-archive database failure can roll back metadata while leaving an orphaned file on disk.

**Required outcome**

- Enforce byte limits at ingress, application request handling, expanded ZIP totals, member count, and client preflight.
- Validate PDF magic/content and sanitize archive members.
- Persist preview evidence and issue a short-lived preview ID bound to source hash, parser version, classification, and decision.
- Confirm only that exact preview.
- Validate a complete bundle before mutation; reject mixed-meet bundles unless an explicit multi-meet import contract exists.
- Make replacement a staged, all-or-nothing promotion rather than delete-then-continue.
- Include date/source-event identity in the canonical key, add database uniqueness/upsert protection, and exercise concurrent imports.
- Clean up or ledger archived bytes consistently when database work fails.

### P0. Alembic cannot bootstrap a fresh database

The first four migrations are no-op historical stubs, while the next revision reflects and alters tables such as `Result` that are assumed to exist. I independently ran `alembic upgrade head` against an empty disposable SQLite database; it failed with `sqlalchemy.exc.NoSuchTableError: Result`.

Every backend pod currently runs `alembic upgrade head` at startup. Existing-database upgrades may work, but the migration chain cannot reconstruct a new environment after total database loss.

**Required outcome**

- Create a tested baseline/squash or complete historical schema migration.
- Gate empty PostgreSQL → head and representative legacy PostgreSQL → head.
- Compare the resulting tables, indexes, constraints, and foreign keys with SQLAlchemy metadata.

### P0. Numeric evidence lacks finite and plausible-domain validation

`time_to_seconds()` accepts zero, negative values, `NaN`, and infinity because it delegates directly to `float()`. Database columns have no corresponding checks. Independent temporary-database probes found that persisted `NaN` can break the browser swimmer-detail route and be labeled a personal best by legacy projections; `0.00` can cause progression division by zero.

**Required outcome**

- Reject non-finite, zero, negative, malformed, and physically implausible race/split values before persistence.
- Validate persisted evidence again at projection boundaries so one bad row cannot return a 500 for an athlete profile.
- Store canonical numeric seconds separately from source display text, preserving raw text for audit.

### P0. Deployment and recovery are bootstrap-grade

- Frontend/backend init containers clone the unpinned GitHub default branch.
- Runtime containers install dependencies and build the frontend on each pod start.
- The live commit happened to match local `main`, but the manifest does not make that deterministic.
- There is no swim-owned CI workflow, immutable application image, scheduled source-monitor job, or database/raw-document backup job in the app manifests.
- PostgreSQL is a one-replica `Deployment` using the default RollingUpdate strategy against one RWO local-path PVC. It should not risk overlapping PostgreSQL writers during rollout.
- Clone init containers have no resource requests/limits.
- `npm audit --omit=dev` reported four production vulnerabilities: one critical and three high. Direct dependency Next.js 14.2.5 has a non-major remediation at 14.2.35; affected transitives include lodash, nanoid, and postcss.
- A disposable clean frontend build failed when `next/font/google` could not fetch Inter. The normal workspace build passed, but pod startup remains dependent on external network availability and caches.

**Required outcome**

- Build tested ARM64 images in CI and pin immutable commit-SHA tags in Fleet.
- Make verification noninteractive: backend tests, real-PDF regression, frontend tests, typecheck, lint, build, migration check.
- Use a stateful/recreate-safe PostgreSQL rollout model.
- Add logical database backup plus raw-document backup and restore drill.
- Add application-owned source-monitor scheduling only after the monitor path is authorized and observable.
- Upgrade dependencies, rerun audit, and self-host required fonts/assets so builds are hermetic.

## Product and UX gaps

### P1. “Personal best” is not truthful at current corpus depth

Jung Yi's profile contains only two swims from one meet, yet labels both event groups “Personal bests.” These are only the fastest times in the ingested dataset, not proven lifetime PBs.

Use **“Fastest in our records”** until source coverage is sufficient and scoped. Show coverage beside it: earliest/latest record, meets included, and source count.

### P1. Raw event strings split one real event into fake separate histories

Jung Yi's 50 m butterfly appears as two event histories:

- Prelim: `Men 15 & Over 50 LC Meter Butterfly` — 25.31, place 6
- Final: `Men 50 LC Meter Butterfly` — 24.51, place 4

The UI therefore reports 2 events and two “PBs” instead of one 50 m butterfly history. It hides the useful story: **0.80 s faster from prelim to final and fourth place**.

This is the clearest evidence that `MeetEvent`/discipline normalization must come before more analytics.

### P1. The data corpus is too shallow for progression

There are only two competitions, both parts of the 56th SNAG in March 2026. A progression chart over one meet is not longitudinal analytics.

The next value step is not a fancier chart. It is ingesting multiple seasons of trustworthy official data after event/status/identity normalization.

### P1. Dashboard language is operator-centric and sometimes wrong

- The homepage prioritizes Upload in hero, quick actions, and navigation instead of the athlete's current performance/targets.
- “Recent Uploads” is implemented as `recentMeets.length`; it shows 2 although there are 17 documents and 3 ingestion runs.
- “Total Results” shows only 10,649 individuals and omits 348 relays without saying so.
- The legacy dashboard helper totals only the five meets returned by `listMeets({limit: 5})`; the label will silently undercount once the corpus exceeds five meets.
- “View all” under Recent Meets routes to the global Results table because no complete `/meets` archive destination exists.
- “Singapore Swimming Association” branding, page title `SSA`, and `© 2026 SSA` imply official ownership/affiliation. Keep this only if authorization is explicit; otherwise rebrand and describe SG Aquatics as the source.

### P1. Data-quality UI gives false reassurance

`GET /api/browser/data-quality` returned an empty summary, zero records, and total 0 while corrupted swimmer identities were directly searchable with `warning_count: 0`.

Relay-only swimmer records also report zero meets/events/latest meet because those aggregates only reflect individual results, despite a nonzero relay count.

The quality surface should be an operator queue built from real invariants, not an empty cosmetic page.

### P1. Provenance labels can overstate evidence authority

`sourceDocumentSha256` is a nullable free string rather than a foreign key to `RawDocument.sha256`. Browser warnings consider any nonempty hash plus parse-job ID sufficient without verifying that the document exists or that the parse job belongs to it. The UI then calls the row “source linked.”

Read projections also omit `SourceReference.sourceType`, so a user-uploaded document can be presented under copy describing “official-source” histories.

**Required outcome:** enforce relational provenance integrity and expose a human source classification: official publication, user upload, corrected/reprocessed derivative, or unknown. “Source linked” must mean the evidence actually resolves and hash-verifies.

### P1. Aggregate and detail surfaces disagree

- Relay-only swimmers can show a nonzero relay count but zero meets, zero events, and no latest meet.
- Legacy meet totals/details omit relays while newer browser views include them.
- Same-date meets are keyed only by date in one swimmer projection, so one meet can overwrite another.
- Progression `meet_count` counts result rows rather than distinct meets.
- A legacy relay serializer substitutes swimmer ID `0` when identity is missing, converting absent evidence into a fake identifier; newer browser types correctly allow null.

Define one shared participation/counting contract and regression-test it across overview, meet, swimmer, event, and global-result projections.

### P1. Mobile results are technically scrollable, not genuinely usable

At 390 px:

- top navigation is a horizontal strip; Sources falls beyond the initial viewport with no menu cue;
- global Results and event tables expose only the first columns until horizontal scrolling;
- an athlete cannot compare event, swimmer, time, place, status, and context in one scan;
- upload/source tables repeat the same issue.

For athlete-facing results, use prioritized mobile cards or two-line rows. Keep dense tables for desktop/operator use.

### P2. Implementation language leaks into the product

Meet and swimmer pages visibly show `derived · raw_event_string`. Source evidence emphasizes hashes and parser/run IDs, but the source file itself is unavailable. This is useful for internal debugging, not normal athlete interpretation.

Translate into human trust language such as “Imported from official results PDF,” “Event label not yet standardized,” and “View source.” Keep hashes/IDs inside an operator disclosure.

### P2. Accessibility is partial

Some newer controls have good `aria-label`s and column scopes, but the global Results filters rely on placeholders, Results table headers omit `scope`, and several upload tables do the same. Horizontal tables also lack a clear mobile alternative. Add keyboard/focus/component coverage rather than relying on static markup review.

### P2. Results query will not scale with corpus growth

`GET /api/results/all` loads all matching individual and relay rows, combines and sorts them in Python, then slices one page. At the current ~11,000-row corpus, a request for **one row** took **2.289–2.430 seconds** across three live measurements.

Move canonical sorting/filtering/pagination into SQL before importing multiple seasons.

### P2. Unknown and date-only evidence can become false dates

- Upload initializes a missing/unparseable meet date with `datetime.now()` and can persist a blank meet name. Unknown source evidence therefore becomes falsely precise current-date evidence.
- The frontend constructs `new Date("YYYY-MM-DD")`; an independent runtime check rendered `2026-03-17` as 17 March in Singapore but 16 March in `America/Los_Angeles`.

Resolve competition identity and start/end bounds once from the strongest official evidence, then re-resolve only when a source hash, resolver version, or curator decision changes. Model the umbrella competition, named segments such as Juniors/Seniors, competition day, session, event, round, and performance separately. Day numbering must be scoped to its segment because Juniors and Seniors can each have a Day 1/Session 1.

Never fabricate a missing date. If competition binding itself is unknown, hold the document for review. If the performance is otherwise valid but its exact day genuinely cannot be established, preserve the date as unknown with evidence status; date-dependent analytics can exclude or label it without rejecting the result. Store/render calendar dates without UTC-to-local day shifts.

## Recommended feature sequence

### Phase 0 — Trust release gate

**Goal:** make “source-backed and rebuildable” true.

1. Durable content-addressed source storage and restore-tested backups.
2. Competition-package registration: source page/manifest, umbrella competition, segment, day/session hints, immutable document revisions, and explicit completeness state.
3. Repair fresh-database migrations and gate empty/legacy PostgreSQL upgrades.
4. Relay parser fixes, row-level round/status preservation, finite-time validation, anomaly-based confidence, and a clean rebuild.
5. Authenticated operator mutations and separated navigation/roles.
6. Bundle validation, all-or-nothing replacement, upload limits, preview-hash binding, and atomic import idempotency.
7. Relational provenance integrity and source-authority labeling.
8. Immutable image release, dependency upgrades, hermetic assets, CI, real-PDF fixtures, lint, frontend/API contract tests.
9. SQL-level combined-results pagination and cross-surface aggregate parity.

Do not add user-facing analytics until these gates pass.

### Phase 1 — Canonical competition and performance model

**Goal:** make one race mean one thing everywhere.

Add in this order:

1. `CompetitionEdition` umbrella plus `CompetitionSegment` for internally coherent parts such as Juniors/Seniors;
2. `CompetitionDay` and `Session`, using date-only values and evidence-backed resolution state;
3. canonical discipline/event dimensions: distance, stroke, course, individual/relay, and sex/category only where required for comparison;
4. competition event plus source event number/official label, with round modeled separately;
5. performance with explicit result status, integer source-precision time, and relational provenance;
6. athlete alias/source-identity evidence and admin merge/split decisions;
7. club/team aliases over time.

**Concrete acceptance case:** Jung Yi's profile shows one canonical 50 LC butterfly history with two swims, labels prelim/final correctly, shows 25.31 → 24.51 (**−0.80 s**), and calls 24.51 “fastest in our records,” not a universal PB.

### Phase 2 — Corpus growth and source operations

**Goal:** create actual longitudinal value.

1. Ingest all obtainable official overall-results PDFs across multiple seasons through the same pipeline.
2. Turn source discovery into a scheduled, authorized, observable job.
3. Add source coverage manifests and reconciliation: expected documents, imported documents, failures, revisions, and hash changes. A single empty/partial discovery response must not mark all known events absent; require complete-run evidence and bulk-disappearance circuit breakers.
4. Add a real correction/reprocess queue for parser, identity, event, and source anomalies.

Success should be measured by **coverage and correctness**, not document count alone: target athletes/events with multiple canonical meets, every imported row source-resolvable, and zero unresolved critical parser anomalies.

### Phase 3 — Athlete home and target-event intelligence

**Goal:** answer “where am I, what changed, and what is the next target?”

Replace the generic upload-first dashboard for normal users with:

- saved/followed athlete profile;
- target events;
- fastest recorded time and corpus coverage;
- last result and change from prior result;
- prelim-to-final and seed-to-result deltas;
- placement/round/meet context;
- split comparison where source evidence supports it;
- next relevant meet/standard, if configured.

This should be a responsive card/sequence experience, not another wide table.

### Phase 4 — Versioned qualification standards and meet recaps

**Goal:** convert records into decisions without speculative prediction.

1. Versioned standards with organization, competition, event, sex/category, course, effective dates, source document, and provenance.
2. Gap-to-standard shown in seconds and percentage, with clear eligibility caveats.
3. Athlete meet recap: best recorded swims, prelim-final changes, seed-vs-result, placements, DQ/status, and source-backed split observations.
4. Coach/team recap and export only after club identity is normalized.

### Explicit product boundary

This repository is only Swim Analytics: official competition evidence, canonical race performances, competition browsing, swimmer history, standards, and source-backed analytics. Training sessions, Polar, Apple Health, recovery, wellness, and PPI are not part of this system or roadmap.

## Team execution model

Use one integrator and three dependency-aware lanes:

### Integrator / tech lead

Own the domain contract, migration order, acceptance dataset, and release gate. No parallel changes to event identity, result status, and dedup keys without this owner.

### Lane A — Evidence and platform

- durable raw storage;
- auth/roles;
- upload boundaries;
- backups/restore;
- immutable CI/image deployment;
- source scheduler;
- private object storage and managed PostgreSQL cloud cutover;
- public read/private admin boundary, rate limiting, and launch observability.

### Lane B — Parser and domain integrity

- relay regressions;
- status preservation;
- confidence/anomaly policy;
- canonical event/session model;
- rebuild and reconciliation.

### Lane C — Product/browser

Start against frozen Phase 1 contracts:

- truthful fastest-in-records/profile coverage;
- athlete-first home;
- mobile result cards;
- standards and recap;
- correction queue UI.

### Independent gates

For each slice, require:

1. domain/data review;
2. privacy/security review;
3. phone-width browser journey;
4. migration/rebuild/idempotent-rerun proof;
5. Fleet source/image/live coherence check.

## Acceptance gates before calling the platform trusted

- Every database source reference resolves to immutable bytes and hash-verifies.
- Empty PostgreSQL and representative legacy PostgreSQL both migrate to the same expected head schema.
- A disposable full rebuild from raw sources reproduces expected logical counts.
- Rebuild inputs include competition manifests/source snapshots and versioned curation decisions; raw PDFs alone are not treated as sufficient for replaying identity/event corrections.
- Immediate rerun adds zero duplicates, including under concurrency, while legitimate same-time swims on different dates/source events remain distinct.
- A mixed-meet or partially invalid bundle makes zero result/meet mutations; replace mode never promotes a partial dataset.
- No imported athlete has an impossible age or timing/ordinal fragments in their name.
- Confidence fails or quarantines every known corrupted relay fixture.
- `NS`, `DNS`, `DNF`, `SCR`, `DQ`, finished, and unknown remain distinct through parser → DB → API → UI.
- Prelim/final round meaning and relay split distances survive parser → DB → API → UI unchanged.
- Zero, negative, non-finite, malformed, or physically implausible race times cannot become PBs or crash read routes.
- Unauthenticated mutation requests fail before validation/domain lookup.
- Normal users do not see Upload, Replace, or Sources as primary destinations.
- Jung Yi's 50 butterfly prelim/final map to one canonical history.
- Competition, segment, day, session, event, and performance dates/identities remain distinct; resolved metadata is reused until its evidence or resolver version changes.
- A genuinely unresolved performance date remains unknown rather than becoming the current date or blocking unrelated valid competition data.
- Competition and swimmer views are projections over the same canonical performance rows and agree on counts/statuses.
- “PB” is either evidence-scoped or backed by sufficiently complete declared coverage.
- Combined results paginate in SQL and respond within an agreed Pi-class latency budget at the multi-season target corpus.
- Backend, real-PDF, frontend unit/component, typecheck, lint, build, migration, and browser smoke gates run noninteractively in CI.
- PostgreSQL and raw sources pass an actual restore drill.

## Do not build next

- AI coaching or race prediction
- training-load/recovery features in this repository
- social feed or athlete messaging
- entries, payments, or meet management
- national-ranking claims before identity/eligibility/privacy policy
- complex comparative analytics before event normalization and multi-season coverage

Those would decorate uncertain evidence. The immediate leverage is to make the current evidence trustworthy, broaden it, and turn it into one excellent athlete target-event journey.
