# SG Aquatics Raw Data Discovery — 56th SNAG 2026

Source page: https://www.sgaquatics.org.sg/swimming/events/56th-snag-2026/

## Raw Library Principle

Keep the PDF archive as immutable source material. The database is derived/rebuildable state.

Pipeline model:

```text
Discover event page → download all PDFs → classify + hash + manifest → parse selected categories → validate → import → rebuild DB when needed
```

## Local Archive

Full archive path:

```text
raw-data/sg-aquatics/56th-snag-2026-full/
```

Manifest:

```text
raw-data/sg-aquatics/56th-snag-2026-full/manifest.json
```

## Category Counts

| Category | Count | Current use |
|---|---:|---|
| `event_information` | 1 | Reference metadata/rules/schedule; not imported yet |
| `start_list` | 17 | Future: seed vs result, attendance/no-show, heat/lane analysis |
| `overall_results` | 17 | **Primary import target now** |
| `age_group_results` | 6 | Future/hold: finals-by-age-group; may overlap with finals sessions |
| `medal_tally` | 5 | Future: team medal summaries / validation |

## Parser Check — Overall Results

All 17 `overall_results` PDFs parse at 100% confidence with the current HY-TEK parser.

Totals from local parse check:

| Metric | Count |
|---|---:|
| Files | 17 |
| Events | 355 |
| Individual results | 10,905 |
| Relay results | 348 |

Sample validated file:

```text
56th-snag-seniors-2026-results-day-1-session-1.pdf
Meet: 56th SNAG Seniors
Events: 19
Results: 863
Swimmers: 672
Confidence: 100%
First result: WU, Dylan Jiaxu — 200 LC Meter IM — 2:18.62
```

## Initial Category Observations

### Overall results

HY-TEK result PDFs with prelim/final/session data. These are the right first import target because they represent the canonical meet session results.

### Age-group results

These are finals-by-age-group PDFs. They parse with the same parser, but they appear to overlap with final sessions (e.g. Day 1 Session 2). Do **not** import yet until we model whether they are duplicates, alternative ranking views, or additional derived placings.

### Start lists

HY-TEK meet program PDFs. Current parser detects event blocks but no results. Future value: seed times, heat/lane assignments, attendance/no-shows, seed-vs-result deltas.

### Medal tallies

Team-level summary PDFs. Current result parser is not intended for them. Future value: team leaderboard and validation against imported results.

## Near-Term Recommendation

1. Treat `overall_results` as import scope v0.
2. Keep all other PDFs archived but out of the import path.
3. Add ingestion metadata tables before importing:
   - source pages/events
   - raw files
   - parse runs
   - imported records / content hashes
4. Make DB rebuild a first-class command: raw archive → parse → import.
5. Defer age-group finals merge until we compare record identities against overall finals sessions.

## Open Questions

- Should raw PDFs be committed to Git, stored in object storage/NAS, or kept in a local data volume with manifest tracked in Git?
- Should `age_group_results` become a derived ranking view or a separate imported source table?
- How do we want to model athletes with name variations, teams with abbreviation/full-name variants, and foreign/guest swimmers?
- Do we want manual approval before importing new PDFs into production DB, or is preview/QA enough?
