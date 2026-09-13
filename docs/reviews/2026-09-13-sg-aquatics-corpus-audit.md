# Singapore Aquatics archived-corpus audit

Audit date: 2026-09-13

## Scope and safety

- Refreshed the official Singapore Aquatics competitive-swimming event index.
- Archived all PDFs exposed by the ten discovered event pages.
- Verified every manifest entry against its immutable by-SHA copy.
- Previewed every result-classified document with the current parser.
- Compared session, combined, full-result, age-group, and cumulative-ranking views before proposing canonical promotion.
- Did not import, migrate, or modify production data.

## Archive result

- Event bundles: **10**
- Result-ready event pages: **10**
- Manifest entries: **250**
- Unique SHA-256 documents: **250**
- Hash/source verification failures: **0**
- Local raw-library size at audit time: **289 MB**

The previous July discovery snapshot had 241 links and classified the August Invitational as not yet result-ready. The refreshed snapshot has 250 links and all ten pages result-ready.

## Strict canonical performance envelope

These are source-level canonical counts after removing combined-document duplication, cumulative ranking reprints, age-group alternate views, and known timed-final carryovers. They are **expected post-fix counts**, not a claim that the current importer can safely promote all rows today.

| Competition | Course | Canonical individual | Canonical relay | Strict total | Current disposition |
|---|---:|---:|---:|---:|---|
| 56th SNAG 2026 | LCM | 10,905 | 348 | 11,253 | Previously rebuild-verified; relay legs retain quality states |
| SAQ ETP Championships 2026 | SCM | 410 | 0 | 410 | Parses cleanly; single results report has no session header by source design |
| Singapore Short-Course Invitational 2026 | SCM | 1,419 | 42 | 1,461 | Four sessions canonical; meet-wide report corroborating only; includes one source-marked exhibition swim recovered by `hytek-v2` |
| 21st SNSC 2026 | LCM | 3,475 | 53 | 3,528 | Hold: 54 cumulative distance-event reprints and parser gaps |
| Singapore Swim Series 2026 | LCM | 9,204 | 0 | 9,204 | Hold: two segments, alphanumeric final event IDs, duplicate full/A-final views |
| 11th SNSC 25m 2025 | SCM | 2,153 | 88 | 2,241 | Hold: Session 5 misclassified; first-row and Judge's Decision relay loss |
| 47th SEA Age Group swimming 2025 | LCM | 1,410 | 48 | 1,458 | Hold: date format and relay-leg completeness; non-swimming disciplines excluded |
| 20th SNSC 2025 | LCM | 2,636 | 67 | 2,703 | Hold: first-row loss, one distinct no-age layout, and 38 carryovers |
| Singapore Swim Series 2025 | LCM | 9,043 | 0 | 9,043 | Hold: two omitted result files, one broken PDF character map, round/status gaps |
| 55th SNAG 2025 | LCM | 10,876 | 315 | 11,191 | Hold: two segments, extensive alternate/full reports, 207 reprints |
| **Total** |  |  |  | **52,492** | **48,380 LCM + 4,112 SCM** |

Two additional 55th SNAG relay statuses occur only in an aggregate report and could raise the curated total to **52,494**, but they are excluded from the strict source/session-backed total pending an explicit curation decision.

## Canonical classification by bundle

### 21st SNSC 2026

All eight result PDFs are official session reports, but Sessions 2 and 8 contain cumulative standings for long-distance events started in Sessions 1 and 7.

- Parsed occurrences: 3,529 individual + 53 relay.
- Strict facts: 3,475 individual + 53 relay.
- Reprints: 54 individual performances.
- Preserve the original morning session as race context; attach the evening placement as a ranking context.
- One official `NT` row is currently dropped and should remain an unknown-status observation.

### Singapore Swim Series 2026

One umbrella edition contains two independent LCM segments with restarting day/session numbers:

- Series I: 16–18 January 2026 — 4,486 performances.
- Series II: 6–8 February 2026 — 4,718 performances.

The current 18,115-row preview is noncanonical because it includes full-result duplicates while missing standalone `101F`-style A-final sections. Strict total: 9,204.

### 11th SNSC 25m 2025

- Five physical sessions, 7–9 November 2025.
- Session 5 is a valid result PDF misclassified as `other_pdf`.
- Full-results PDF is corroborating only.
- Ten timed-final rows are reprinted in later consolidated finals standings.
- Strict total: 2,153 individual + 88 relay.

### 47th SEA Age Group Aquatics Championships

The page is a multi-discipline umbrella, not one swimming bundle:

- Artistic swimming: 6 PDFs.
- Diving: 20 PDFs.
- Competitive swimming: 11 PDFs.
- Water polo: 5 PDFs.
- Umbrella summons: 1 PDF.

The fourteen HY-TEK preview failures are artistic-swimming or diving results, not competitive-swimming parser failures. For swimming, three daily files are canonical and the meet-wide report is an exact duplicate. Strict swimming total: 1,410 individual + 48 relay.

### 20th SNSC 2025

Use four heats and four finals reports as atomic evidence; retain the full-results report for correction/reconciliation.

- Strict total: 2,636 individual + 67 relay.
- Session files contain 38 timed-final reprints that must be attributed once.
- One heats document uses a materially different no-age layout and currently parses only two malformed rows.

### Singapore Swim Series 2025

One umbrella edition contains January and February LCM segments.

- Ten session result PDFs are canonical.
- Two January files are results despite generic filenames.
- One February PDF has a broken private-use character map requiring deterministic text normalization.
- Strict total: 9,043 individual performances.

### 55th SNAG 2025

Two segments:

- Juniors: 14–16 March, five sessions.
- Seniors: 18–23 March, twelve sessions.

Full, age-group, and A/B/Super-Final reports substantially overlap. Strict total is 10,876 individual + 315 directly session-backed relays. Two aggregate-only relay statuses remain held for curation. Senior session views contain 207 known reprints.

## Cross-corpus parser and model blockers

Do not wholesale-import the seven newly archived historical bundles until these are addressed:

1. **Source-role curation**
   - Select explicit canonical documents/rows; `overall_results` filename classification alone is unsafe.
   - Keep full, combined, cumulative, and age-group views as linked ranking/correction evidence.

2. **Row-level overlap reconciliation**
   - Suppress long-distance cumulative standings and timed-final reprints without collapsing genuinely distinct equal-time swims from different rounds/sessions.

3. **HY-TEK layout coverage**
   - Support textual-month and US-style date ranges.
   - Preserve alphanumeric event IDs such as `101F`.
   - Stop time-standard rows from consuming the first result.
   - Support no-age result layouts, optional trailing `Points`, and private-use-font normalization.

4. **Outcome and placement semantics**
   - Preserve `XDQ`, `J` Judge's Decision markers, exhibition status, unknown `NT` rows, and A/B/C/Super-Final context.
   - Keep timed final distinct from ordinary final when source evidence supports it.

5. **Relay safety**
   - Parent relay performance may remain usable while incomplete/contaminated legs are quarantined.
   - Normalize medley relay stroke and mixed gender.

6. **Segment-aware hierarchy**
   - Swim Series and SNAG pages contain multiple segments whose day/session numbering restarts. Identity must include segment and session scope.

## Release recommendation

Treat **52,492** as the current strict source-backed coverage target, not the current production row count. Implement and regression-test the blockers against the archived PDFs, then require:

1. package-specific canonical allowlists/curation decisions;
2. exact post-parse counts above;
3. zero unexplained result-like unmatched rows;
4. explicit relay extraction quality;
5. fresh-database transactional rebuild;
6. immediate idempotent second import with zero new canonical rows;
7. readback reconciliation by competition, segment, course, date, session, status, and source hash.
